"""Prepare Git changes and observe Argo CD deployments of the full suite.

Application manifests and fault activation can live in different user-owned repos.
Commands edit local checkouts; committing and pushing remain explicit operator steps.
Cluster bootstrap stores generated credentials only in Kubernetes, never in Git.
"""
import argparse
import datetime
import json
import re
import secrets
import time
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from .__main__ import command
from .app_manifests import FLAG_FAULTS, NAMESPACES, OWNER, flag_config, meta, resources, secret
from . import cluster_ops as cluster
from .records import write
from . import retirement


def settings(config):
    value = config.get('gitops', {})
    if not isinstance(value, dict): raise ValueError('gitops must be an object')
    for key in ['app_repo', 'fault_repo']:
        repo = value.get(key, {})
        if not all(isinstance(repo.get(k), str) and repo[k] for k in ['url', 'checkout', 'revision', 'path']):
            raise ValueError('gitops.' + key + ' needs url, checkout, revision, path')
        path = PurePosixPath(repo['path'])
        if path.is_absolute() or '..' in path.parts: raise ValueError('repository path must be relative; use . for the repository root')
        url = urlsplit(repo['url'])
        if url.scheme in ['https', 'http'] and (url.username or url.password or url.query):
            raise ValueError('repository URL must not contain credentials or query parameters')
    a, f = value['app_repo'], value['fault_repo']
    if Path(a['checkout']).resolve() == Path(f['checkout']).resolve():
        if a['url'] != f['url'] or a['revision'] != f['revision']: raise ValueError('one checkout must use one repository URL and revision')
        ap, fp = PurePosixPath(a['path']), PurePosixPath(f['path'])
        if ap == fp or ap in fp.parents or fp in ap.parents: raise ValueError('app and fault repository paths must not overlap')
    return value


def target(repo): return Path(repo['checkout']) / repo['path']


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def kustomization(paths):
    return {'apiVersion': 'kustomize.config.k8s.io/v1beta1', 'kind': 'Kustomization', 'resources': paths}


def app(name, repo, relative, namespace, argo_namespace='argocd'):
    policy = {'automated': {'prune': True, 'selfHeal': True}}
    if name == 'batch-jobs': policy['automated']['allowEmpty'] = True
    if name not in ['platform-root', 'flagd-values', 'arena-control']:
        policy['syncOptions'] = ['CreateNamespace=true']
    destination = {'server': 'https://kubernetes.default.svc', 'namespace': namespace} if name == 'platform-root' else {'name': 'in-cluster', 'namespace': namespace}
    return {'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'Application', 'metadata': meta(name, argo_namespace),
            'spec': {'project': 'default', 'source': {'repoURL': repo['url'], 'targetRevision': repo['revision'], 'path': str(PurePosixPath(repo['path']) / relative)},
                     'destination': destination, 'syncPolicy': policy}}


def export(config):
    cfg = settings(config); apps, faults = cfg['app_repo'], cfg['fault_repo']
    existing_state = target(faults) / 'control/state.json'
    if existing_state.exists() and json.loads(existing_state.read_text())['data'].get('scenario'):
        raise ValueError('retire the active scenario before re-exporting application manifests')
    for repo in [apps, faults]:
        directory = target(repo)
        if directory.exists() and any(p.name != '.git' for p in directory.iterdir()) and not (directory / '.arena-gitops.json').exists():
            raise ValueError('refusing nonempty unmanaged export path: ' + str(directory))
    for repo in [apps, faults]: put(target(repo) / '.arena-gitops.json', {'format': 'arena-gitops-v1'})
    groups = {}
    for obj in resources('GENERATED_AT_BOOTSTRAP', 'GENERATED_AT_BOOTSTRAP')['items']:
        if obj['kind'] in ['Secret', 'Namespace'] or obj['metadata']['name'] == 'flagd-config': continue
        name = obj['metadata']['name']
        group = 'postgres' if obj['metadata']['namespace'] == 'datastore' and name.startswith('postgres') else name
        if group == 'kafka': group = 'checkout'
        if group == 'otel-collector': group = 'telemetry'
        if name == 'postgres-init':
            sql = obj['data']['init.sql'].replace("'GENERATED_AT_BOOTSTRAP'", ":'app_password'").replace("'monitoring_password'", ":'monitoring_password'")
            obj['data'] = {'init.sh': '#!/bin/sh\nset -eu\npsql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v app_password="$SHOP_PASSWORD" -v monitoring_password="$MONITORING_PASSWORD" <<\'SQL\'\n' + sql + '\nSQL\n'}
        for c in obj.get('spec', {}).get('template', {}).get('spec', {}).get('containers', []):
            for e in c.get('env', []):
                if e['name'] == 'DB_CONNECTION_STRING':
                    e.pop('value', None); e['valueFrom'] = {'secretKeyRef': {'name': 'catalog-database', 'key': 'url'}}
            if name == 'postgres':
                c.setdefault('env', []).extend([{'name': name, 'valueFrom': {'secretKeyRef': {'name': 'postgres', 'key': name}}} for name in ['SHOP_PASSWORD', 'MONITORING_PASSWORD']])
        groups.setdefault(group, []).append(obj)
    children = []
    for name, objects in sorted(groups.items()):
        folder = target(apps) / 'components' / name
        put(folder / 'resources.json', {'apiVersion': 'v1', 'kind': 'List', 'items': objects})
        put(folder / 'kustomization.yaml', kustomization(['resources.json']))
        children.append(app(name, apps, 'components/' + name, objects[0]['metadata']['namespace'], cfg.get('namespace', 'argocd')))
    for name, path, namespace in [('flagd-values', 'flagd-values', 'shop'), ('batch-jobs', 'batch-active', 'batch'), ('arena-control', 'control', 'benchmark-control')]:
        children.append(app(name, faults, path, namespace, cfg.get('namespace', 'argocd')))
    put(target(apps) / 'apps' / 'applications.json', {'apiVersion': 'v1', 'kind': 'List', 'items': children})
    put(target(apps) / 'apps' / 'kustomization.yaml', kustomization(['applications.json']))
    from .scenarios import catalog, render
    for scenario in catalog():
        if scenario in FLAG_FAULTS: continue
        folder = target(faults) / 'library' / scenario
        # Kustomize emits YAML; keep exactly its rendered content.
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'resources.yaml').write_text(render(scenario, config.get('registry', 'fixture.local'), config.get('tag', 'v1')))
        put(folder / 'kustomization.yaml', kustomization(['resources.yaml']))
    prepare(config, '')
    return {'mode': 'gitops', 'prepared': True, 'applications': [c['metadata']['name'] for c in children],
            'next': 'Review, commit and push both local checkouts, configure Argo repository authentication, then bootstrap.'}


def prepare(config, scenario):
    cfg = settings(config); folder = target(cfg['fault_repo'])
    if not (folder / '.arena-gitops.json').exists(): raise ValueError('export GitOps manifests first')
    from .scenarios import catalog
    if scenario and scenario not in catalog(): raise ValueError('unknown scenario')
    previous = folder / 'control' / 'state.json'
    previous_state = json.loads(previous.read_text())['data'] if previous.exists() else {}
    if scenario and previous_state.get('scenario'):
        raise ValueError('prepare, commit, push and sync reset before another fault')
    put(folder / 'batch-active' / 'kustomization.yaml', kustomization(['../library/' + scenario] if scenario and scenario not in FLAG_FAULTS else []))
    flag_path = folder / 'flagd-values' / 'configmap.json'
    current_flags = json.loads(flag_path.read_text()) if flag_path.exists() else flag_config()
    if scenario in FLAG_FAULTS or not scenario or not flag_path.exists():
        put(flag_path, retirement.flags(current_flags, scenario))
    put(folder / 'flagd-values' / 'kustomization.yaml', kustomization(['configmap.json']))
    retired = previous_state.get('scenario') or previous_state.get('retired_scenario', '') if not scenario else ''
    state = {'registry': config.get('registry', 'fixture.local'), 'tag': config.get('tag', 'v1'), 'scenario': scenario,
             'deployment_mode': 'gitops', 'retired_scenario': retired, 'operation_id': secrets.token_hex(12),
             'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')}
    put(folder / 'control' / 'state.json', {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': meta('suite-state', 'benchmark-control'), 'data': state})
    put(folder / 'control' / 'kustomization.yaml', kustomization(['state.json']))
    return {'mode': 'gitops', 'scenario': scenario, 'prepared': True, 'next': 'Review, commit and push the fault repository, then run sync.'}


def heads(config):
    result = {}
    for key in ['app_repo', 'fault_repo']:
        repo = settings(config)[key]
        checkout = str(Path(repo['checkout']).resolve())
        if command(['git', '-C', checkout, 'status', '--porcelain']).strip(): raise ValueError('commit all local changes before bootstrap/sync: ' + key)
        result[key] = command(['git', '-C', checkout, 'rev-parse', 'HEAD']).strip()
    return result


def bootstrap(config):
    cfg = settings(config); context = config['context']; commits = heads(config)
    cluster.guard(context, False)
    existing = cluster.obj(context, 'configmap', 'suite-state', 'benchmark-control')
    if existing and existing.get('data', {}).get('deployment_mode') != 'gitops':
        raise ValueError('existing direct deployment: retire it and its disposable namespaces before bootstrapping Argo')
    for name in ['platform-root'] + [a['metadata']['name'] for a in json.loads((target(cfg['app_repo']) / 'apps' / 'applications.json').read_text())['items']]:
        existing_app = cluster.obj(context, 'application', name, cfg.get('namespace', 'argocd'))
        if existing_app and not cluster.owned(existing_app): raise ValueError('refusing existing unmanaged Argo application: ' + name)
    for ns in NAMESPACES: cluster.apply(context, {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': meta(ns)})
    if not cluster.obj(context, 'secret', 'postgres', 'datastore'):
        admin, password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        cluster.apply(context, {'apiVersion': 'v1', 'kind': 'List', 'items': [
            secret('postgres', 'datastore', {'POSTGRES_PASSWORD': admin, 'SHOP_PASSWORD': password, 'MONITORING_PASSWORD': secrets.token_urlsafe(32)}),
            secret('db-maintenance', 'batch', {'PGUSER': 'shop', 'PGPASSWORD': admin}),
            secret('catalog-database', 'shop', {'url': 'postgres://shop_user:' + password + '@postgres.datastore.svc.cluster.local:5432/shop_db?sslmode=disable'})]})
    else:
        existing_secret = cluster.obj(context, 'secret', 'postgres', 'datastore')
        if not all(k in existing_secret.get('data', {}) for k in ['POSTGRES_PASSWORD', 'SHOP_PASSWORD', 'MONITORING_PASSWORD']):
            raise ValueError('existing database credentials were not created by this GitOps bootstrap')
        for namespace, name in [('batch', 'db-maintenance'), ('shop', 'catalog-database')]:
            if not cluster.obj(context, 'secret', name, namespace): raise ValueError('incomplete bootstrap credentials; restore all bootstrap secrets consistently')
    local_state = json.loads((target(cfg['fault_repo']) / 'control/state.json').read_text())
    if not existing: cluster.apply(context, local_state)
    root = app('platform-root', cfg['app_repo'], 'apps', 'default', cfg.get('namespace', 'argocd'))
    cluster.apply(context, root)
    return {'mode': 'gitops', 'commits': commits, 'root_application': 'platform-root', 'next': 'Run sync to verify Argo applied these commits.'}


def sync_matches(applications, expected):
    failures = []
    for name, sha in expected.items():
        item = applications.get(name, {})
        status = item.get('status', {})
        if status.get('sync', {}).get('status') != 'Synced' or status.get('sync', {}).get('revision') != sha:
            failures.append(name)
    return failures


def operation_receipt(context, operation_id):
    if not re.fullmatch(r'[a-f0-9]{24,64}', operation_id): raise ValueError('invalid or missing GitOps operation identity; prepare a new operation')
    return cluster.obj(context, 'configmap', 'operation-' + operation_id, 'benchmark-control')


def receipt(context, operation_id, data, create=False):
    value = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': meta('operation-' + operation_id, 'benchmark-control'), 'data': {k: str(v) for k, v in data.items()}}
    if create: cluster.kube(context, 'create', '-f', '-', stdin=json.dumps(value))
    else: cluster.apply(context, value)


def trigger_once(context, operation_id, commit):
    existing = operation_receipt(context, operation_id)
    if existing:
        if existing['data'].get('phase') == 'trigger_done': return existing['data']
        raise ValueError('an earlier trigger attempt has an uncertain result; inspect its recorded pod before retrying')
    pods = json.loads(cluster.kube(context, '-n', 'shop', 'get', 'pods', '-l', 'app.kubernetes.io/name=recommendation', '-o', 'json'))['items']
    if len(pods) != 1: raise ValueError('expected exactly one recommendation pod before admission trigger')
    pod = pods[0]['metadata']
    data = {'phase': 'trigger_started', 'commit': commit, 'pod': pod['name'], 'pod_uid': pod['uid'], 'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    # Atomic create reserves the operation before deletion. A crash/error leaves an
    # explicit uncertain receipt rather than silently deleting another replacement.
    receipt(context, operation_id, data, create=True)
    cluster.kube(context, '-n', 'shop', 'delete', 'pod', pod['name'], '--wait=false')
    data.update(phase='trigger_done', finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    receipt(context, operation_id, data)
    return data


def cleanup(config, retired_scenario='', operation_id=None):
    context = config['context']
    retirement.wait_pruned(context)
    existing = operation_receipt(context, operation_id) if operation_id else None
    actions = []
    if not existing or existing['data'].get('phase') != 'cleanup_done':
        actions = retirement.restore(context, retired_scenario)
        if operation_id:
            receipt(context, operation_id, {'phase': 'cleanup_done', 'retired_scenario': retired_scenario, 'finished_at': datetime.datetime.now(datetime.timezone.utc).isoformat()})
    checks = retirement.wait_baseline(context, timeout=retirement.recovery_timeout(retired_scenario))
    result = cluster.verify(context, 'healthy', 180)
    result.update(retirement=checks, cleanup_actions=actions)
    return result


def wait_healthy_applications(context, namespace, expected, timeout):
    deadline = time.monotonic() + timeout
    while True:
        apps = {v['metadata']['name']: v for v in json.loads(cluster.kube(context, '-n', namespace, 'get', 'applications', '-o', 'json'))['items']}
        failures = sync_matches(apps, expected)
        failures += [name for name in expected if apps.get(name, {}).get('status', {}).get('health', {}).get('status') != 'Healthy']
        if not failures: return apps
        if time.monotonic() >= deadline: raise ValueError('baseline Applications are not Synced and Healthy: ' + ', '.join(sorted(set(failures))))
        time.sleep(3)


def expected_revisions(config, commits):
    cfg = settings(config)
    children = json.loads((target(cfg['app_repo']) / 'apps' / 'applications.json').read_text())['items']
    expected = {'platform-root': commits['app_repo']}
    for item in children:
        expected[item['metadata']['name']] = commits['fault_repo'] if item['metadata']['name'] in ['batch-jobs', 'flagd-values', 'arena-control'] else commits['app_repo']
    return expected


def ready_to_inject(config):
    cfg = settings(config); context = config['context']
    state = cluster.state(context)
    if state.get('deployment_mode') != 'gitops' or state.get('scenario'):
        raise ValueError('complete the existing GitOps scenario retirement before preparing another fault')
    wait_healthy_applications(context, cfg.get('namespace', 'argocd'), expected_revisions(config, heads(config)), 0)
    retirement.wait_baseline(context, timeout=0)


def sync(config, timeout=300):
    cfg = settings(config); context = config['context']; commits = heads(config)
    expected = expected_revisions(config, commits)
    namespace = cfg.get('namespace', 'argocd')
    for name in expected:
        try: cluster.kube(context, '-n', namespace, 'annotate', 'application', name, 'argocd.argoproj.io/refresh=hard', '--overwrite')
        except RuntimeError: pass  # Root may still be creating children.
    deadline = time.monotonic() + timeout
    while True:
        applications = {v['metadata']['name']: v for v in json.loads(cluster.kube(context, '-n', namespace, 'get', 'applications', '-o', 'json'))['items']}
        failed = sync_matches(applications, expected)
        if not failed: break
        if time.monotonic() >= deadline: raise ValueError('Argo has not synced expected commits: ' + ', '.join(failed))
        time.sleep(3)
    state = cluster.state(context)
    scenario = state.get('scenario', '')
    operation_id = state.get('operation_id', commits['fault_repo'])
    trigger = trigger_once(context, operation_id, commits['fault_repo']) if scenario in ['quota-trap', 'admission-webhook-outage'] else None
    observed = cleanup(config, state.get('retired_scenario', ''), operation_id) if not scenario else cluster.verify(context, scenario, timeout)
    if not scenario: applications = wait_healthy_applications(context, namespace, expected, timeout)
    result = {'mode': 'gitops', 'commits': commits, 'scenario': scenario, 'trigger': trigger, 'synced_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'applications': {name: {'revision': applications[name]['status']['sync']['revision'], 'health': applications[name]['status'].get('health', {}).get('status'), 'operation_finished_at': applications[name]['status'].get('operationState', {}).get('finishedAt')} for name in expected}, 'verification': observed}
    return result


def main(argv=None):
    from .runconfig import load
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', default='arena.json')
    parser.add_argument('operation', choices=['export', 'bootstrap', 'fault', 'reset', 'sync'])
    args = parser.parse_args(argv); config = load(args.run); settings(config)
    if args.operation in ['bootstrap', 'sync', 'fault'] and not config.get('context'): raise ValueError('context is required')
    directory = Path(config.get('output_dir', 'runs')) / 'gitops' / (datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + args.operation + '-' + secrets.token_hex(3))
    directory.mkdir(parents=True, mode=0o700)
    write(directory / 'started.json', {'mode': 'gitops', 'operation': args.operation, 'context': config.get('context'), 'scenario': config.get('scenario')})
    try:
        if args.operation in ['bootstrap', 'sync']: write(directory / 'expected-commits.json', heads(config))
        if args.operation == 'fault': ready_to_inject(config)
        result = export(config) if args.operation == 'export' else bootstrap(config) if args.operation == 'bootstrap' else sync(config) if args.operation == 'sync' else prepare(config, config['scenario'] if args.operation == 'fault' else '')
        write(directory / 'result.json', result)
        print(json.dumps(result, indent=2))
        if args.operation == 'sync' and not result['verification']['observed']: raise ValueError('Git synced, but expected runtime outcome was not observed')
    except BaseException as error:
        write(directory / 'failed.json', {'error_type': type(error).__name__}); raise


if __name__ == '__main__':
    try: main()
    except (ValueError, RuntimeError, OSError) as error:
        raise SystemExit(str(error))
