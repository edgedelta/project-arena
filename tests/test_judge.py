"""Exercise provider formats and reject invalid judgments without real API calls."""
import json
import io
import urllib.error
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bench import judge
from bench.scoring import packet
from helpers import archive, judgment


class JudgeTests(unittest.TestCase):
    def response(self, provider, decision):
        text = json.dumps(decision)
        if provider == 'openai':
            return {'model': 'actual-model', 'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}]}
        if provider == 'anthropic':
            return {'model': 'actual-model', 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': text}]}
        return {'model': 'actual-model', 'choices': [{'finish_reason': 'stop', 'message': {'content': text}}]}

    def test_provider_requests_and_validated_response_retention(self):
        for provider, suffix in [('openai', '/responses'), ('anthropic', '/messages'), ('openai-compatible', '/chat/completions')]:
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as d:
                p = packet(archive())
                response = self.response(provider, judgment(p))
                with patch('bench.judge.post', return_value=response) as post:
                    output = Path(d) / 'judgment.json'
                    result = judge.run(p, {'provider': provider, 'model': 'requested-model', 'base_url': 'https://example.test/v1'}, output)
                url, body, config = post.call_args.args
                self.assertTrue(url.endswith(suffix))
                self.assertNotIn('tools', body)
                self.assertNotIn('private-label', json.dumps(body))
                self.assertEqual(result['judge']['model_or_reviewer'], 'actual-model')
                self.assertEqual(result['judge']['provider'], provider)
                self.assertEqual(result['judge']['settings']['model'], 'requested-model')
                attempt = next((Path(d) / 'judge-attempts').iterdir())
                self.assertEqual(json.loads((attempt / 'response.json').read_text()), response)
                self.assertTrue(json.loads((attempt / 'status.json').read_text())['valid'])
                self.assertEqual(output.stat().st_mode & 0o777, 0o600)
                with patch('bench.judge.post') as retry:
                    with self.assertRaises(FileExistsError): judge.run(p, config, output)
                    retry.assert_not_called()

    def test_invalid_citation_retained_but_never_published_or_retried(self):
        p = packet(archive()); decision = judgment(p)
        decision['final_quality']['evidence'][0]['quote'] = 'Invented evidence'
        response = self.response('openai', decision)
        with tempfile.TemporaryDirectory() as d, patch('bench.judge.post', return_value=response) as post:
            output = Path(d) / 'judgment.json'
            with self.assertRaises(ValueError): judge.run(p, {'provider': 'openai', 'model': 'test'}, output)
            post.assert_called_once()
            self.assertFalse(output.exists())
            attempt = next((Path(d) / 'judge-attempts').iterdir())
            self.assertEqual(json.loads((attempt / 'response.json').read_text()), response)
            self.assertFalse(json.loads((attempt / 'status.json').read_text())['valid'])

    def test_truncation_and_refusal_are_not_scores(self):
        responses = [('openai', {'status': 'incomplete'}),
                     ('openai', {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'refusal'}]}]}),
                     ('anthropic', {'stop_reason': 'max_tokens'}),
                     ('openai-compatible', {'choices': [{'finish_reason': 'length'}]})]
        for provider, response in responses:
            with self.subTest(provider=provider, response=response), self.assertRaises(ValueError):
                judge.output_text(response, provider)

    def test_credentials_sent_only_as_headers(self):
        config = judge.settings({'provider': 'openai', 'model': 'test'})
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-secret'}), patch('urllib.request.build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = b'{}'
            judge.post('https://example.test/v1/responses', {'model': 'test'}, config)
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.get_header('Authorization'), 'Bearer test-secret')
            self.assertNotIn(b'test-secret', request.data)
            self.assertNotIn('test-secret', json.dumps(config))
        for url in ['http://remote.test/v1', 'https://user:secret@example.test/v1', 'https://example.test/v1?key=secret']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                judge.settings({'provider': 'openai', 'model': 'test', 'base_url': url})

    def test_quota_error_is_actionable_without_echoing_provider_message(self):
        error = urllib.error.HTTPError('https://example.test', 429, 'Too many requests', {}, io.BytesIO(b'{"error":{"code":"insufficient_quota","message":"private provider detail"}}'))
        config = judge.settings({'provider': 'openai', 'model': 'test', 'api_key_env': ''})
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = error
            with self.assertRaisesRegex(RuntimeError, 'insufficient_quota.*billing') as caught:
                judge.post('https://example.test', {}, config)
        error.close()
        self.assertNotIn('private provider detail', str(caught.exception))
