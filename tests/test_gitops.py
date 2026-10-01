import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bench import gitops
from bench.cluster_ops import require_direct


class GitOpsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = {'gitops': {
            'app_repo': {'url': 'https://example.test/apps.git', 'checkout': self.temp.name + '/apps', 'revision': 'main', 'path': 'arena'},
            'fault_repo': {'url': 'https://example.test/faults.git', 'checkout': self.temp.name + '/faults', 'revision': 'main', 'path': 'arena'}},
            'registry': 'example.test/faults', 'tag': 'test'}

    @unittest.skipUnless(shutil.which('kubectl'), 'kubectl needed for local render')
    def test_export_keeps_fault_repo_separate_and_credentials_out_of_git(self):
        result = gitops.export(self.config)
        apps = gitops.target(self.config['gitops']['app_repo'])
        faults = gitops.target(self.config['gitops']['fault_repo'])
        children = json.loads((apps / 'apps/applications.json').read_text())['items']
        for child in children:
            source = child['spec']['source']
            is_fault = child['metadata']['name'] in ['batch-jobs', 'flagd-values', 'arena-control']
            self.assertEqual(source['repoURL'], 'https://example.test/' + ('faults' if is_fault else 'apps') + '.git')
        text = '\n'.join(p.read_text() for p in apps.rglob('*.json'))
        self.assertNotIn('GENERATED_AT_BOOTSTRAP', text)
        self.assertNotIn('"kind": "Secret"', text)
        self.assertIn('catalog-database', text)
        self.assertIn('$SHOP_PASSWORD', text)
        self.assertEqual(json.loads((faults / 'batch-active/kustomization.yaml').read_text())['resources'], [])
        self.assertIn('batch-jobs', result['applications'])
        # Kustomize every component and library; this does not contact a cluster.
        for path in [*apps.glob('components/*'), *faults.glob('library/*'), apps / 'apps', faults / 'flagd-values', faults / 'control']:
            self.assertTrue(gitops.command(['kubectl', 'kustomize', str(path)]))

    @unittest.skipUnless(shutil.which('kubectl'), 'kubectl needed for local render')
    def test_fault_and_reset_preserve_original_activation_shapes(self):
        gitops.export(self.config)
        root = gitops.target(self.config['gitops']['fault_repo'])
        gitops.prepare(self.config, 'payment-failure')
        flags = json.loads(json.loads((root / 'flagd-values/configmap.json').read_text())['data']['flags.json'])['flags']
        self.assertEqual(flags['paymentStrictTokenCheck']['defaultVariant'], '100%')
        self.assertEqual(json.loads((root / 'batch-active/kustomization.yaml').read_text())['resources'], [])
        with self.assertRaisesRegex(ValueError, 'reset'): gitops.prepare(self.config, 'oom')
        gitops.prepare(self.config, '')
        gitops.prepare(self.config, 'oom')
        self.assertEqual(json.loads((root / 'batch-active/kustomization.yaml').read_text())['resources'], ['../library/oom'])
        self.assertIn('thumbnailer', gitops.command(['kubectl', 'kustomize', str(root / 'batch-active')]))
        gitops.prepare(self.config, '')
        self.assertEqual(json.loads((root / 'control/state.json').read_text())['data']['scenario'], '')

    def test_sync_requires_exact_commit_but_not_healthy_during_fault(self):
        apps = {'batch-jobs': {'status': {'sync': {'status': 'Synced', 'revision': 'old'}, 'health': {'status': 'Healthy'}}}}
        self.assertEqual(gitops.sync_matches(apps, {'batch-jobs': 'new'}), ['batch-jobs'])
        apps['batch-jobs']['status'] = {'sync': {'status': 'Synced', 'revision': 'new'}, 'health': {'status': 'Degraded'}}
        self.assertEqual(gitops.sync_matches(apps, {'batch-jobs': 'new'}), [])

    def test_direct_mutations_refuse_argo_managed_deployment(self):
        with patch('bench.cluster_ops.obj', return_value={'data': {'deployment_mode': 'gitops'}}):
            with self.assertRaisesRegex(ValueError, 'Argo'): require_direct('context')

    def test_initial_healthy_sync_performs_no_data_repairs(self):
        with patch('bench.retirement.wait_pruned'), patch('bench.retirement.restore', return_value=[]) as restore, patch('bench.retirement.wait_baseline', return_value={'passed': True}), patch('bench.gitops.cluster.verify', return_value={'observed': True}):
            self.assertTrue(gitops.cleanup({'context': 'test'})['observed'])
        restore.assert_called_once_with('test', '')

    def test_incomplete_pruning_blocks_cleanup_mutations(self):
        with patch('bench.retirement.wait_pruned', side_effect=ValueError('injector remains')), patch('bench.retirement.restore') as restore:
            with self.assertRaisesRegex(ValueError, 'injector remains'):
                gitops.cleanup({'context': 'test'}, 'pg-lock-hold')
        restore.assert_not_called()

    def test_argo_sync_policies_match_parent_distinctions(self):
        repo = self.config['gitops']['app_repo']
        component = gitops.app('frontend', repo, 'components/frontend', 'shop')['spec']['syncPolicy']
        self.assertEqual(component, {'automated': {'prune': True, 'selfHeal': True}, 'syncOptions': ['CreateNamespace=true']})
        batch = gitops.app('batch-jobs', repo, 'batch-active', 'batch')['spec']['syncPolicy']
        self.assertTrue(batch['automated']['allowEmpty'])
        flags = gitops.app('flagd-values', repo, 'flagd-values', 'shop')['spec']['syncPolicy']
        self.assertNotIn('allowEmpty', flags['automated']); self.assertNotIn('syncOptions', flags)

    def test_trigger_is_once_and_failed_delete_remains_explicitly_uncertain(self):
        saved = {}
        pod = {'metadata': {'name': 'recommendation-one', 'uid': 'pod-uid'}}
        def receipt(context, operation_id, data, create=False): saved.update(data)
        def kube(*args, **kwargs):
            if 'get' in args: return json.dumps({'items': [pod]})
            return ''
        operation = 'a' * 24
        with patch.object(gitops, 'operation_receipt', side_effect=lambda *args: {'data': saved} if saved else None), patch.object(gitops, 'receipt', side_effect=receipt), patch('bench.gitops.cluster.kube', side_effect=kube) as calls:
            gitops.trigger_once('ctx', operation, 'commit')
            gitops.trigger_once('ctx', operation, 'commit')
        self.assertEqual(sum('delete' in c.args for c in calls.call_args_list), 1)
        saved.clear()
        def failing_kube(*args, **kwargs):
            if 'get' in args: return json.dumps({'items': [pod]})
            raise RuntimeError('delete did not complete')
        with patch.object(gitops, 'operation_receipt', side_effect=lambda *args: {'data': saved} if saved else None), patch.object(gitops, 'receipt', side_effect=receipt), patch('bench.gitops.cluster.kube', side_effect=failing_kube):
            with self.assertRaises(RuntimeError): gitops.trigger_once('ctx', operation, 'commit')
            self.assertEqual(saved['phase'], 'trigger_started')
            with self.assertRaisesRegex(ValueError, 'uncertain'): gitops.trigger_once('ctx', operation, 'commit')

    def test_repo_path_and_embedded_credentials_rejected(self):
        self.config['gitops']['fault_repo']['path'] = '../other'
        with self.assertRaises(ValueError): gitops.settings(self.config)
        self.config['gitops']['fault_repo']['path'] = 'arena'
        self.config['gitops']['fault_repo']['url'] = 'https://token@example.test/repo'
        with self.assertRaises(ValueError): gitops.settings(self.config)


if __name__ == '__main__': unittest.main()
