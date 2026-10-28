from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import MagicMock, patch

from organizer import ai_settings, ai_setup_tasks, providers, cache, classifier, config


class AIProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=config.ROOT, prefix='organizer-ai-tests-')
        self.base = Path(self.temp.name).resolve()
        self.addCleanup(self.temp.cleanup)

    def test_settings_roundtrip_has_no_key_and_rejects_invalid_consent(self):
        path = self.base / 'settings.json'
        self.assertIsNone(ai_settings.load(path))
        chosen = ai_settings.AIConfig('openai', 'gpt-4o-mini', True)
        ai_settings.save(chosen, path)
        self.assertEqual(ai_settings.load(path), chosen)
        self.assertNotIn('api_key', path.read_text())
        with self.assertRaises(ValueError):
            ai_settings.AIConfig('openai', 'gpt-4o-mini', False)
        with self.assertRaises(ValueError):
            ai_settings.AIConfig('ollama', '../bad model')

    def test_credential_rollback_on_settings_failure(self):
        store = MagicMock()
        store.get_password.return_value = 'old-test-key'
        with patch.object(ai_settings, 'credential_store', return_value=store), \
             patch.object(ai_settings, 'save', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                ai_settings.commit(ai_settings.AIConfig('openai', 'gpt-4o-mini', True), 'new-test-key')
        self.assertEqual(store.set_password.call_args_list[-1].args[-1], 'old-test-key')

    def test_provider_model_and_rules_cache_isolation(self):
        path = self.base / 'a.txt'
        path.write_bytes(b'content')
        stat = path.stat()
        f = {'path': str(path), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns,
             'sha256': classifier.file_sha256(path), 'extension': '.txt'}
        result = {'category': 'Learning', 'suggested_name': 'notes.txt', 'reason': 'test'}
        local = ai_settings.AIConfig()
        cloud = ai_settings.AIConfig('openai', local.model, True)
        with patch.object(cache, 'DB_PATH', self.base / 'cache.db'), patch.object(cache, 'PROJECT', self.base):
            self.assertTrue(cache.content_cache_write(f, result, ai_config=local))
            self.assertEqual(cache.content_cache_read(f, ai_config=local), result)
            self.assertIsNone(cache.content_cache_read(f, ai_config=cloud))
            self.assertIsNone(cache.content_cache_read(f, ai_config=ai_settings.AIConfig('rules', '')))
            self.assertIsNone(cache.content_cache_read(f, ai_config=ai_settings.AIConfig('ollama', 'different')))

    def test_openai_adapter_uses_official_endpoint_and_disables_response_storage(self):
        parsed = ai_setup_tasks.ProbeResults(results=[ai_setup_tasks.ProbeResult(
            file_id=0, category='Learning', suggested_name='notes.txt', reason='test')])
        client = MagicMock()
        client.responses.parse.return_value = types.SimpleNamespace(output_parsed=parsed)
        with patch('openai.OpenAI') as factory:
            factory.return_value.__enter__.return_value = client
            result = providers.classify([{'file_id': 0}], ai_setup_tasks.ProbeResults, ('Learning', 'Other'),
                                       ai_settings.AIConfig('openai', 'gpt-4o-mini', True), 'fake-test-key')
        self.assertEqual(result, parsed)
        self.assertEqual(factory.call_args.kwargs['base_url'], 'https://api.openai.com/v1')
        self.assertFalse(client.responses.parse.call_args.kwargs['store'])
        self.assertEqual(client.responses.parse.call_args.kwargs['text_format'], ai_setup_tasks.ProbeResults)

    def test_rules_only_does_not_extract_or_contact_a_provider(self):
        with patch.object(classifier, 'extract_content') as extract, patch.object(providers, 'classify') as call:
            self.assertEqual(classifier.analyze_files([{}], ai_config=ai_settings.AIConfig('rules', '')), {})
        extract.assert_not_called()
        call.assert_not_called()

    def test_model_download_progress_and_cancellation(self):
        events = [types.SimpleNamespace(status='pulling', digest='a', total=100, completed=50),
                  types.SimpleNamespace(status='success', digest=None, total=None)]
        client = MagicMock()
        client.pull.return_value = iter(events)
        progress = MagicMock()
        with patch.object(providers, 'ollama_client', return_value=client):
            ai_setup_tasks.pull_model('test-model', progress, threading.Event())
        self.assertEqual(progress.call_args.args[1], 100)
        cancel = threading.Event()
        cancel.set()
        client.pull.return_value = iter(events)
        with patch.object(providers, 'ollama_client', return_value=client):
            with self.assertRaises(ai_setup_tasks.Cancelled):
                ai_setup_tasks.pull_model('test-model', progress, cancel)

    def test_setup_probe_uses_only_synthetic_text(self):
        parsed = ai_setup_tasks.ProbeResults(results=[ai_setup_tasks.ProbeResult(
            file_id=0, category='Learning', suggested_name='notes.txt', reason='test')])
        with patch.object(providers, 'classify', return_value=parsed) as call:
            ai_setup_tasks.test_config(ai_settings.AIConfig())
        payload = call.call_args.args[0]
        self.assertNotIn('path', payload[0])
        self.assertEqual(payload[0]['file_id'], 0)
        self.assertIn('beginner tutorial', payload[0]['content_excerpt'])

    def test_local_option_blocks_remote_model_before_inference(self):
        response = MagicMock()
        response.json.return_value = {'remote_host': 'https://ollama.com', 'model_info': {'general.architecture': 'test'}}
        with patch('httpx.Client') as client, patch.object(providers, 'ollama_client') as engine:
            client.return_value.__enter__.return_value.post.return_value = response
            with self.assertRaises(providers.LocalModelRequired):
                providers.classify([], ai_setup_tasks.ProbeResults, ('Other',), ai_settings.AIConfig())
        engine.assert_not_called()

    def test_installer_signature_failure_never_launches_installer(self):
        response = MagicMock()
        response.history = []
        response.url = types.SimpleNamespace(scheme='https', host='ollama.com')
        response.headers = {'Content-Length': '4'}
        response.iter_bytes.return_value = iter([b'test'])
        with patch.object(ai_setup_tasks, 'PROJECT', self.base), \
             patch.object(ai_setup_tasks.httpx, 'stream') as stream, \
             patch.object(ai_setup_tasks, 'verify_ollama_signature', side_effect=RuntimeError('Unverified publisher')), \
             patch.object(ai_setup_tasks.subprocess, 'run') as launch:
            stream.return_value.__enter__.return_value = response
            with self.assertRaises(RuntimeError):
                ai_setup_tasks.install_ollama(MagicMock(), threading.Event())
        launch.assert_not_called()
        self.assertFalse(list(self.base.rglob('*.exe')))


if __name__ == '__main__':
    unittest.main()
