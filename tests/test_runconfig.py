import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bench.__main__ import main
from bench.runconfig import load


class RunConfigTests(unittest.TestCase):
    def config(self, directory, **overrides):
        p = Path(directory) / 'arena.json'
        value = {'suite': 'smoke', 'scenario': 'crashloop', 'run_id': 'trial',
                 'product': 'any-product', 'output_dir': 'results'}
        value.update(overrides)
        p.write_text(json.dumps(value))
        return str(p)

    def test_import_packet_defaults_preserve_final_and_old_results(self):
        with tempfile.TemporaryDirectory() as d:
            config = self.config(d)
            final = Path(d) / 'final.txt'; final.write_text('Exact final answer.\n')
            main(['--run', config, 'archive', '--final', str(final)])
            output = Path(d) / 'results/crashloop/archive.json'
            a = json.loads(output.read_text())
            self.assertEqual(a['sources']['final_answer'], final.read_text())
            self.assertEqual(a['case_id'], 'trial-crashloop')
            self.assertEqual(a['detection']['status'], 'not_measured')
            main(['--run', config, 'packet'])
            self.assertTrue(output.with_name('packet.json').exists())
            original = output.read_bytes()
            with self.assertRaises(FileExistsError): main(['--run', config, 'archive', '--final', str(final)])
            self.assertEqual(output.read_bytes(), original)
            main(['--run', config, '--case', 'crashloop-attempt2', 'archive', '--final', str(final)])
            self.assertTrue(Path(d, 'results/crashloop-attempt2/archive.json').exists())

    def test_fullsuite_fault_uses_fullsuite_controller(self):
        with tempfile.TemporaryDirectory() as d:
            config = self.config(d, suite='full', scenario='oom')
            with patch('bench.cluster_ops.start', return_value={'applied': True}) as start, patch('builtins.print'), patch('bench.evidence.capture', return_value={}):
                main(['--run', config, 'fault', '--context', 'disposable'])
                start.assert_called_once_with('disposable', 'oom')

    def test_case_cannot_escape_output_directory(self):
        with tempfile.TemporaryDirectory() as d:
            config = self.config(d)
            with self.assertRaises(ValueError): main(['--run', config, '--case', '../escape', 'archive'])

    def test_wrong_suite_scenario_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as d:
            config = self.config(d, scenario='oom')
            with patch('bench.__main__.command', side_effect=AssertionError('external call')):
                with self.assertRaises(ValueError): main(['--run', config, 'fault', '--context', 'disposable'])

    def test_configuration_typos_and_shell_command_strings_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError): load(self.config(d, prodcut='typo'))
            with self.assertRaises(ValueError): load(self.config(d, judge_command='python judge.py'))

    def test_configured_context_and_evidence_defaults_with_overrides(self):
        with tempfile.TemporaryDirectory() as d:
            config = self.config(d, context='saved-context')
            with patch('bench.__main__.guard') as guard, patch('bench.__main__.command'), patch('builtins.print'), patch('bench.evidence.capture', return_value={}):
                main(['--run', config, 'deploy'])
                guard.assert_called_with('saved-context')
                main(['--run', config, 'deploy', '--context', 'override'])
                guard.assert_called_with('override')
            case = Path(d) / 'results/crashloop'; case.mkdir(parents=True, exist_ok=True)
            (case / 'final.txt').write_text('Final answer')
            (case / 'actions.txt').write_text('Recorded tool results')
            main(['--run', config, 'archive'])
            record = json.loads((case / 'archive.json').read_text())
            self.assertEqual(record['sources']['final_answer'], 'Final answer')
            self.assertEqual(record['sources']['actions'], 'Recorded tool results')
            self.assertEqual(record['sources']['intermediate'], '')

    def test_configured_smoke_deploy_and_reset_are_healthy(self):
        with tempfile.TemporaryDirectory() as d:
            config = self.config(d, context='test')
            for op, expected in [('deploy', 'healthy'), ('fault', 'crash'), ('reset', 'healthy')]:
                with patch('bench.__main__.guard'), patch('bench.__main__.command') as command, patch('bench.evidence.capture', return_value={}), patch('builtins.print'):
                    main(['--run', config, op])
                manifest = json.loads(command.call_args_list[0].args[1])
                deployment = next(item for item in manifest['items'] if item['kind'] == 'Deployment')
                container = deployment['spec']['template']['spec']['containers'][0]
                self.assertEqual(container['env'][0]['value'], expected)

    def test_smoke_truth_override_used_from_config_and_explicit_flag(self):
        from bench.scoring import packet, canonical_digest
        from helpers import archive
        with tempfile.TemporaryDirectory() as d:
            facts = {'cause': 'Custom cause', 'impact': 'Custom impact', 'mitigation': 'Custom repair',
                     'causal_change': {'eligible': False, 'reason': 'No change history'}}
            truth = Path(d) / 'truth.json'
            truth.write_text(json.dumps({'scenario': 'crashloop', 'ground_truth': facts}))
            config = self.config(d, truths={'crashloop': 'truth.json'})
            final = Path(d) / 'final.txt'; final.write_text('Custom final answer')
            main(['--run', config, 'archive', '--final', str(final)])
            main(['--run', config, 'packet'])
            p = json.loads(Path(d, 'results/crashloop/packet.json').read_text())
            self.assertEqual(p['scenario_truth'], facts)
            self.assertEqual(p['truth_sha256'], canonical_digest(facts))
            explicit = Path(d) / 'explicit.json'
            main(['--run', config, 'packet', '--truth', str(truth), '--out', str(explicit)])
            self.assertEqual(json.loads(explicit.read_text())['truth_sha256'], p['truth_sha256'])
            truth.write_text(json.dumps({'scenario': 'wrong', 'ground_truth': facts}))
            with self.assertRaisesRegex(ValueError, 'scenario mismatch'): packet(archive(), truth_path=truth)
            truth.write_text(json.dumps({'scenario': 'crashloop', 'ground_truth': {}}))
            with self.assertRaisesRegex(ValueError, 'truth needs'): packet(archive(), truth_path=truth)
