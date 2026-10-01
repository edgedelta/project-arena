"""Capture Kubernetes state to help check that a scenario happened as intended.

The answer key describes the expected fault; this snapshot records observed pod
state, events, image IDs, configuration, and recent logs. For example, it helps
distinguish an OOMKilled pod from one that never started because its image was
unavailable. records.py saves snapshots alongside benchmark operation records.

Snapshots support debugging and run review. They do not replace the product's
investigation text or the answer key, and are not required for rescoring that text.
Collection is read-only and limited to the benchmark namespaces plus supporting
cluster resources. Logs are bounded and may still contain sensitive app output.
"""
import json
from .records import now
from .cluster_ops import kube

NAMESPACED = 'pods,deployments,statefulsets,daemonsets,jobs,services,endpoints,events,pvc,resourcequotas,networkpolicies,configmaps'


def scrub(value):
    """Omit common sensitive fields from resource JSON; this does not scrub logs."""
    if isinstance(value, list): return [scrub(v) for v in value]
    if not isinstance(value, dict): return value
    result = {}
    for key, item in value.items():
        if key in ['managedFields', 'annotations']: continue
        if key == 'env':
            result[key] = [{**e, 'value': '<redacted>'} if 'value' in e else scrub(e) for e in item]
        elif key in ['command', 'args']: result[key] = ['<omitted>']
        elif key in ['data', 'binaryData'] and value.get('kind') == 'ConfigMap':
            # Flags are part of this fixture; generic ConfigMaps can contain credentials.
            result[key] = item if value.get('metadata', {}).get('name') in ['shop-flags', 'suite-state'] else {k: '<omitted>' for k in item}
        else: result[key] = scrub(item)
    return result


def capture(context, suite):
    """Return a snapshot, recording unavailable resources/logs explicitly.

    This is a point-in-time collection, not a complete incident history. A pod
    may already have disappeared, and previous-container logs may not exist.
    """
    namespaces = ['benchmark-control', 'shop', 'datastore', 'batch', 'platform-ops'] if suite == 'full' else ['incident-bench']
    result = {'captured_at': now(), 'context': context, 'suite': suite, 'resources': {}, 'logs': [], 'errors': [],
              'limitations': ['Secret resources are not collected. Literal environment values, container commands/arguments and generic ConfigMap values are omitted. Logs may still contain application-emitted sensitive data.',
                             'Logs are bounded snapshots, not continuous telemetry. Missing previous-container logs are recorded as unavailable.']}
    def get(args):
        try: return json.loads(kube(context, *args))
        except (RuntimeError, ValueError) as error:
            result['errors'].append({'request': args, 'error_type': type(error).__name__}); return None
    result['kubernetes_version'] = get(['version', '-o', 'json'])
    for namespace in namespaces:
        value = get(['-n', namespace, 'get', NAMESPACED, '-o', 'json'])
        if value is None: continue
        result['resources'][namespace] = scrub(value)
        for pod in value.get('items', []):
            if pod.get('kind') != 'Pod': continue
            for container in pod.get('spec', {}).get('containers', []) + pod.get('spec', {}).get('initContainers', []):
                for previous in [False, True]:
                    item = {'namespace': namespace, 'pod': pod['metadata']['name'], 'container': container['name'], 'previous': previous}
                    try:
                        item['text'] = kube(context, '-n', namespace, 'logs', pod['metadata']['name'], '-c', container['name'],
                                            '--tail=200', '--limit-bytes=65536', '--timestamps=true', *(['--previous'] if previous else []))
                    except RuntimeError:
                        item['unavailable'] = True
                    result['logs'].append(item)
    nodes = get(['get', 'nodes', '-o', 'json'])
    if nodes:
        result['nodes'] = [{'name': n['metadata']['name'], 'labels': n['metadata'].get('labels', {}),
                            'node_info': n.get('status', {}).get('nodeInfo', {}), 'capacity': n.get('status', {}).get('capacity', {})}
                           for n in nodes.get('items', [])]
    if suite == 'full':
        for kind, name in [('persistentvolume', 'index-store'), ('validatingwebhookconfiguration', 'pod-policy')]:
            value = get(['get', kind, name, '--ignore-not-found', '-o', 'json'])
            if value: result['resources'][kind] = scrub(value)
        result['storage_classes'] = scrub(get(['get', 'storageclasses', '-o', 'json']))
    result['finished_at'] = now()
    return result
