"""Retire an injected fault without replacing healthy services or their data.

Both direct and Argo runners use the parent benchmark's targeted cleanup order:
remove injectors, restore only their persistent effects, then check the baseline.
"""
import base64
import copy
import json
import re
import time
from urllib.parse import unquote, urlsplit
from .app_manifests import FLAG_FAULTS
from . import cluster_ops as cluster

BASELINE_FLAGS = {'paymentStrictTokenCheck': 'off', 'cartSecondaryStoreShare': 'off', 'browseJourneyConcurrency': '5'}
REQUIRED_FLAGS = dict(BASELINE_FLAGS, browseJourneyEnabled='on', homepagePrefetchBurst='off', cartDrainMode='off')
BATCH_RESOURCES = 'deployments,statefulsets,jobs,pods,pvc'
LOCK_FILTER = "l.granted AND l.mode='AccessExclusiveLock' AND l.relation='catalog.products'::regclass AND a.pid<>pg_backend_pid()"


def flags(current, scenario=''):
    """Change one injected flag, or reset the three parent scenario flags only."""
    result = copy.deepcopy(current)
    values = json.loads(result['data']['flags.json'])
    changes = dict([FLAG_FAULTS[scenario]]) if scenario in FLAG_FAULTS else BASELINE_FLAGS if not scenario else {}
    for name, variant in changes.items():
        flag = values['flags'][name]
        if variant not in flag['variants']: raise ValueError('flag variant is not available: ' + name)
        flag['defaultVariant'] = variant
    result['data']['flags.json'] = json.dumps(values, indent=2)
    return result


def wait_pruned(context, timeout=180):
    deadline = time.monotonic() + timeout
    while json.loads(cluster.kube(context, '-n', 'batch', 'get', BATCH_RESOURCES, '-o', 'json'))['items']:
        if time.monotonic() >= deadline: raise ValueError('batch workloads or claims remain; finish retirement before cleanup')
        time.sleep(2)


def psql(context, query):
    # SQL travels over stdin, including the restored password; never print it.
    return cluster.kube(context, '-n', 'datastore', 'exec', '-i', 'statefulset/postgres', '--', 'psql', '-U', 'shop', '-d', 'shop_db', '-v', 'ON_ERROR_STOP=1', '-tA', stdin=query + '\n').strip()


def consumer_password(context):
    deployment = cluster.obj(context, 'deployment', 'product-catalog', 'shop')
    env = [e for c in deployment['spec']['template']['spec']['containers'] if c['name'] == 'product-catalog' for e in c.get('env', [])]
    entry = next((e for e in env if e['name'] == 'DB_CONNECTION_STRING'), None)
    if not entry: raise ValueError('product-catalog DB_CONNECTION_STRING is missing')
    value = entry.get('value')
    if value is None:
        ref = entry.get('valueFrom', {}).get('secretKeyRef')
        if not ref: raise ValueError('DB_CONNECTION_STRING must be a literal or Secret reference')
        data = cluster.obj(context, 'secret', ref['name'], 'shop')
        if not data or ref['key'] not in data.get('data', {}): raise ValueError('catalog database Secret value is missing')
        value = base64.b64decode(data['data'][ref['key']], validate=True).decode()
    uri = urlsplit(value)
    if uri.username != 'shop_user' or not uri.password: raise ValueError('catalog connection must identify shop_user and a password')
    return unquote(uri.password)


def restore(context, scenario):
    """Run only the retired scenario's helper; callers must first wait_pruned."""
    actions = []
    if scenario in ['redis-pressure', 'multi-fault']:
        cluster.kube(context, '-n', 'datastore', 'exec', 'statefulset/redis', '--', 'redis-cli', 'config', 'set', 'maxmemory', '256mb')
        cluster.kube(context, '-n', 'datastore', 'exec', 'statefulset/redis', '--', 'sh', '-c', 'redis-cli --scan --pattern "warm:*" | xargs -r -n 500 redis-cli del')
        actions.append('restored Redis maxmemory before removing warm:* keys')
    if scenario == 'stale-db-credentials':
        password = consumer_password(context)
        psql(context, "ALTER USER shop_user WITH PASSWORD '" + password.replace("'", "''") + "';")
        actions.append('restored shop_user password from the actual catalog connection setting')
    if scenario == 'pg-lock-hold':
        count = int(psql(context, 'SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a ON a.pid=l.pid WHERE ' + LOCK_FILTER))
        if count:
            psql(context, 'SELECT count(pg_terminate_backend(l.pid)) FROM pg_locks l JOIN pg_stat_activity a ON a.pid=l.pid WHERE ' + LOCK_FILTER)
        remaining = int(psql(context, 'SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a ON a.pid=l.pid WHERE ' + LOCK_FILTER))
        if remaining: raise ValueError('maintenance table locks remain after cleanup')
        actions.append('released remaining exclusive catalog table locks after injector retirement')
    if scenario == 'volume-affinity-conflict':
        pv = cluster.obj(context, 'persistentvolume', 'index-store')
        if pv:
            metadata = pv.get('metadata', {})
            tracking = metadata.get('annotations', {}).get('argocd.argoproj.io/tracking-id', '')
            if not cluster.owned(pv) and not tracking.startswith('batch-jobs:') and metadata.get('labels', {}).get('app.kubernetes.io/instance') != 'batch-jobs':
                raise ValueError('refusing index-store PV without fixture/Argo ownership')
            cluster.kube(context, 'delete', 'persistentvolume', 'index-store', '--wait=true', '--timeout=120s')
        actions.append('removed retained index-store PV after claim retirement')
    return actions


def baseline_failures(context):
    """Read back the parent retired_ok invariants, without repairing them."""
    failures = []
    if json.loads(cluster.kube(context, '-n', 'batch', 'get', BATCH_RESOURCES, '-o', 'json'))['items']:
        failures.append('batch workloads or claims remain')
    if json.loads(cluster.kube(context, '-n', 'shop', 'get', 'resourcequotas,networkpolicies', '-o', 'json'))['items']:
        failures.append('shop quota or network policy remains')
    for kind, name in [('validatingwebhookconfiguration', 'pod-policy'), ('persistentvolume', 'index-store')]:
        if cluster.obj(context, kind, name): failures.append(kind + '/' + name + ' remains')
    current = cluster.obj(context, 'configmap', 'flagd-config', 'shop')
    values = json.loads(current['data']['flags.json'])['flags'] if current else {}
    for name, variant in REQUIRED_FLAGS.items():
        if values.get(name, {}).get('defaultVariant') != variant: failures.append(name + ' is not at baseline')
    memory = cluster.kube(context, '-n', 'datastore', 'exec', 'statefulset/redis', '--', 'redis-cli', '--raw', 'config', 'get', 'maxmemory').strip().splitlines()
    if not memory or memory[-1] != '268435456': failures.append('Redis maxmemory is not 256mb')
    warm = cluster.kube(context, '-n', 'datastore', 'exec', 'statefulset/redis', '--', 'sh', '-c', 'redis-cli --scan --pattern "warm:*" --count 1000 | head -1').strip()
    if warm: failures.append('Redis warm:* keys remain')
    if int(psql(context, "SELECT count(*) FROM pg_locks WHERE mode='AccessExclusiveLock' AND granted")):
        failures.append('granted exclusive locks remain')
    for namespace, workload in [('shop', 'deployment/frontend'), ('datastore', 'statefulset/postgres')]:
        logs = cluster.kube(context, '-n', namespace, 'logs', workload, '--since=2m')
        if re.search(r'authentication failed|password authentication', logs, re.I): failures.append(workload + ' has authentication failures in the last 2 minutes')
    for name in ['recommendation', 'load-generator']:
        workload = cluster.obj(context, 'deployment', name, 'shop')
        if not workload or workload.get('status', {}).get('availableReplicas') != 1: failures.append(name + ' is not 1/1 available')
    return failures


def recovery_timeout(scenario):
    # Failed admission creates can back off for 1000 seconds before the
    # ReplicaSet retries. Allow that retry plus startup without forcing it.
    return 1200 if scenario in ("quota-trap", "admission-webhook-outage") else 180


def wait_baseline(context, timeout=180):
    deadline = time.monotonic() + timeout
    while True:
        try: failures = baseline_failures(context)
        except (RuntimeError, ValueError, KeyError) as error: failures = ['baseline inspection failed: ' + type(error).__name__]
        if not failures: return {'passed': True, 'checks': 'parent retirement invariants'}
        if time.monotonic() >= deadline: raise ValueError('baseline recovery wait expired; recovery is not yet confirmed: ' + '; '.join(failures))
        time.sleep(3)
