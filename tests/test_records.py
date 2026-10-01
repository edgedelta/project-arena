"""Operation failures and partial cluster snapshots must remain reviewable."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bench.__main__ import main
from bench.scenarios import main as scenarios_main
from bench.evidence import capture


class RecordTests(unittest.TestCase):
    def config(self, d, suite='full'):
        value = {'suite': suite, 'scenario': 'oom' if suite == 'full' else 'crashloop', 'context': 'test-context', 'output_dir': d, 'run_id': 'test', 'product': 'test'}
        path = Path(d) / 'arena.json'; path.write_text(json.dumps(value))
        return path, value

    def test_explicit_evidence_collects_once_in_both_suites(self):
        for suite in ['full', 'smoke']:
            with self.subTest(suite=suite), tempfile.TemporaryDirectory() as d:
                path, config = self.config(d, suite)
                snapshot = {'resources': {}, 'errors': ['unavailable']}
                with patch('bench.cluster_ops.guard'), patch('bench.__main__.guard'), patch('bench.evidence.capture', return_value=snapshot) as collect:
                    main(['--run', str(path), 'evidence'])
                collect.assert_called_once_with('test-context', suite)
                case = Path(d) / config['scenario']
                op = next((case / 'operations').iterdir())
                self.assertEqual(json.loads((case / 'evidence.json').read_text()), json.loads((op / 'evidence.json').read_text()))

    def test_secondary_cli_records_success_and_verification_failure(self):
        for observed in [True, False]:
            with self.subTest(observed=observed), tempfile.TemporaryDirectory() as d:
                _, config = self.config(d)
                with patch('bench.runconfig.load', return_value=config), patch('bench.cluster_ops.verify', return_value={'observed': observed}) as verify, patch('bench.evidence.capture', return_value={}) as collect, patch('builtins.print'):
                    if observed: scenarios_main(['verify', 'oom', '--context', 'override'])
                    else:
                        with self.assertRaises(ValueError): scenarios_main(['verify', 'oom', '--context', 'override'])
                verify.assert_called_once_with('override', 'oom', 120)
                collect.assert_called_once_with('override', 'full')
                op = next((Path(d) / 'oom/operations').iterdir())
                self.assertEqual(json.loads((op / 'result.json').read_text()), {'observed': observed})
                self.assertEqual(json.loads((op / 'finished.json').read_text())['status'], 'completed' if observed else 'failed')

    def test_secondary_mutations_save_results_and_use_configured_directory(self):
        for command, controller in [('deploy', 'deploy'), ('start', 'start'), ('reset', 'reset')]:
            with self.subTest(command=command), tempfile.TemporaryDirectory() as d:
                _, config = self.config(d)
                argv = [command] + (['oom'] if command == 'start' else []) + ['--context', 'explicit']
                if command == 'reset': argv += ['--confirm-disposable']
                with patch('bench.runconfig.load', return_value=config), patch('bench.cluster_ops.' + controller, return_value={'ok': True}) as call, patch('bench.evidence.capture', return_value={}), patch('builtins.print'):
                    scenarios_main(argv)
                call.assert_called_once()
                op = next((Path(d) / 'oom/operations').iterdir())
                self.assertEqual(json.loads((op / 'result.json').read_text()), {'ok': True})
                self.assertEqual(json.loads((op / 'finished.json').read_text())['operation'], 'fault' if command == 'start' else command)

    def test_operation_error_survives_failed_evidence_collection(self):
        with tempfile.TemporaryDirectory() as d:
            path, _ = self.config(d)
            with patch('bench.cluster_ops.start', side_effect=RuntimeError('injection failed')), patch('bench.evidence.capture', side_effect=ValueError('capture failed')):
                with self.assertRaisesRegex(RuntimeError, 'injection failed'): main(['--run', str(path), 'fault'])
            op = next((Path(d) / 'oom/operations').iterdir())
            result = json.loads((op / 'finished.json').read_text())
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['evidence_error'], 'ValueError')
            self.assertIn('started_at', result)
            self.assertIn('finished_at', result)

    def test_capture_redacts_resources_and_reports_missing_logs(self):
        pod = {'kind': 'Pod', 'metadata': {'name': 'api', 'annotations': {'secret': 'hidden'}}, 'spec': {'containers': [{'name': 'api', 'env': [{'name': 'PASSWORD', 'value': 'hidden'}], 'args': ['hidden']}]}, 'status': {'containerStatuses': [{'imageID': 'sha256:actual'}]}}
        config = {'kind': 'ConfigMap', 'metadata': {'name': 'custom'}, 'data': {'password': 'hidden'}}
        def kube(context, *args):
            self.assertEqual(context, 'explicit')
            self.assertNotIn('secrets', ','.join(args))
            if 'logs' in args:
                self.assertIn('--limit-bytes=65536', args)
                if '--previous' in args: raise RuntimeError('unavailable')
                return 'current log'
            if args[:2] == ('version', '-o'): return '{}'
            if args[:2] == ('get', 'nodes'): raise RuntimeError('forbidden')
            return json.dumps({'items': [pod, config]})
        with patch('bench.evidence.kube', side_effect=kube): result = capture('explicit', 'smoke')
        self.assertNotIn('hidden', json.dumps(result['resources']))
        self.assertIn('sha256:actual', json.dumps(result['resources']))
        self.assertEqual(result['logs'][0]['text'], 'current log')
        self.assertTrue(result['logs'][1]['unavailable'])
        self.assertEqual(len(result['errors']), 1)
