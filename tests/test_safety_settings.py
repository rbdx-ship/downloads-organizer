"""Folder-name guard uses disposable settings, never a user's configuration."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from organizer import config, folder_access, safety_settings


class SafetySettingsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=config.ROOT, prefix='safety-settings-test-')
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        p = patch.object(safety_settings, 'SETTINGS_PATH', self.base/'safety_settings.json')
        p.start()
        self.addCleanup(p.stop)

    def test_default_accepts_leaf_name_at_any_path_and_ignores_case(self):
        self.assertEqual(safety_settings.required_name(), 'Downloads')
        for folder in (Path('D:/Personal/Downloads'), Path('E:/Work/downloads')):
            safety_settings.validate_folder_name(folder)
        for folder in (Path('D:/Downloads/Other'), Path('D:/MyDownloads'), Path('D:/Downloads-copy')):
            with self.assertRaises(ValueError):
                safety_settings.validate_folder_name(folder)

    def test_external_validation_enforces_name_before_approval(self):
        with patch.object(config, 'validate_preview_folder', return_value=Path('D:/Data/Other')), \
             patch.object(config, 'is_real_downloads', return_value=False):
            with self.assertRaisesRegex(ValueError, 'must be named "Downloads"'):
                folder_access.authorize_folder(Path('D:/Data/Other'))

    def test_save_persists_name_and_invalidates_session_approvals(self):
        with patch.object(folder_access, '_approved', {'fixture': (1, 2)}):
            safety_settings.save_name('Incoming')
            self.assertEqual(folder_access._approved, {})
        self.assertEqual(safety_settings.required_name(), 'Incoming')
        safety_settings.validate_folder_name(Path('D:/Data/Incoming'))
        with self.assertRaises(ValueError):
            safety_settings.validate_folder_name(Path('D:/Data/Downloads'))

    def test_invalid_names_do_not_replace_existing_settings(self):
        safety_settings.save_name('Incoming')
        for name in ('', '../Downloads', 'D:\\Downloads', ' Downloads', 'Downloads ',
                     'Downloads.', 'CON', 'NUL.txt', '.hidden', 'a/b', 'a:b', 'a\n'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                safety_settings.save_name(name)
        self.assertEqual(safety_settings.required_name(), 'Incoming')

    def test_corrupt_settings_fail_closed(self):
        for content in ('{', '[]', '{}', '{"version":2}',
                        '{"version":1,"required_folder_name":"../bad"}'):
            safety_settings.SETTINGS_PATH.write_text(content, encoding='utf-8')
            with self.subTest(content=content), self.assertRaises(ValueError):
                safety_settings.validate_folder_name(Path('D:/Data/Downloads'))

    def test_unreadable_settings_fail_closed(self):
        with patch.object(Path, 'read_text', side_effect=PermissionError('Access denied')):
            with self.assertRaises(ValueError):
                safety_settings.required_name()

    def test_failed_save_keeps_previous_policy_and_approvals(self):
        safety_settings.save_name('Downloads')
        with patch.object(safety_settings.os, 'replace', side_effect=PermissionError('Read only')), \
             patch.object(folder_access, '_approved', {'fixture': (1, 2)}):
            with self.assertRaises(OSError):
                safety_settings.save_name('Incoming')
            self.assertEqual(folder_access._approved, {'fixture': (1, 2)})
        self.assertEqual(safety_settings.required_name(), 'Downloads')
