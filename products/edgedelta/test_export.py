import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('ed_export', Path(__file__).with_name('export.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def rows():
    return [
        {'id': 'first', 'createdAt': '2026-01-01T00:00:00Z', 'role': 'agent', 'senderId': 'sre', 'state': 'done',
         'parts': [{'type': 'text', 'text': 'Earlier hypothesis'}, {'type': 'tool', 'output': 'x' * 6000 + 'END'}]},
        {'id': 'final', 'createdAt': '2026-01-01T00:01:00Z', 'role': 'agent', 'senderId': 'system', 'state': 'done',
         'parts': [{'type': 'text', 'text': 'Final delivered answer'}]}]


class ExportTests(unittest.TestCase):
    def test_capture_preserves_bytes_and_exports_standard_record(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); capture = root/'capture'
            raw = json.dumps({'items': rows(), 'total_items': 2}, indent=3).encode() + b'\n'
            metadata = json.dumps({'id': 'thread', 'state': 'resolved', 'updatedAt': 'stable'}).encode()
            with patch.object(m.subprocess, 'run', side_effect=[SimpleNamespace(returncode=0, stdout=b, stderr=b'') for b in [metadata, raw]]) as run, patch('builtins.print'):
                m.capture({'profile': 'test', 'org': 'org', 'channel': 'channel'}, 'thread', capture)
            self.assertEqual(run.call_count, 2)
            self.assertFalse((capture/'thread-after.json').exists())
            self.assertEqual((capture/'messages.json').read_bytes(), raw)
            self.assertIn('--all', run.call_args_list[1].args[0])
            config = root/'arena.json'; config.write_text(json.dumps({'suite':'full', 'scenario':'oom', 'run_id':'test'}))
            output = root/'archive.json'
            m.export(capture, 'final', str(config), output)
            record = json.loads(output.read_text())
            self.assertEqual(record['sources']['final_answer'], 'Final delivered answer')
            self.assertEqual(record['sources']['intermediate'], 'Earlier hypothesis')
            self.assertIn('x'*6000+'END', record['sources']['actions'])
            self.assertEqual(record['capture']['final_message_id'], 'final')
            self.assertEqual(record['detection']['status'], 'not_measured')
            with self.assertRaises(FileExistsError): m.export(capture, 'final', str(config), output)
            (capture/'messages.json').write_text('[]')
            with self.assertRaisesRegex(ValueError, 'changed'): m.export(capture, 'final', str(config), root/'other.json')

    def test_incomplete_or_ambiguous_final_rejected(self):
        for mutation in ['unfinished', 'followup', 'alert', 'delegation', 'wrong_sender']:
            r = rows()
            if mutation == 'unfinished': r[0]['state'] = 'in-progress'
            if mutation == 'followup': r.append(dict(r[-1], id='later', createdAt='2026-01-02'))
            if mutation == 'alert': r[-1]['parts'].append({'type':'trigger-details'})
            if mutation == 'delegation': r[-1]['parts'][0]['text'] = 'mention_agent:sre'
            if mutation == 'wrong_sender': r[-1]['senderId'] = 'sre'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): m.extract(r, 'final')

    def test_missing_actions_and_duplicate_or_partial_pages(self):
        r = rows(); r[0]['parts'] = []
        self.assertEqual(m.extract(r, 'final')['actions'], '')
        for payload in [{'items': rows(), 'total_items': 3}, {'items': rows(), 'nextCursor':'next'}, rows()+[rows()[0]]]:
            with self.assertRaises(ValueError): m.messages(payload)

