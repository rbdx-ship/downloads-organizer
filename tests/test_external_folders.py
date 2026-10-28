"""Real Windows handle operations on disposable fixtures; no AI or user data."""
from contextlib import ExitStack
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from organizer import cache, categories, classifier, config, file_manager, folder_access
from organizer import windows_moves
from organizer.ai_settings import AIConfig


@unittest.skipUnless(os.name == 'nt', 'Windows handle safety checks')
class ExternalFolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=config.ROOT, prefix='external-safety-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.first, self.second = self.base/'first', self.base/'second'
        self.first.mkdir()
        self.second.mkdir()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for module, name, value in [(file_manager, 'PROJECT', self.base),
                                    (file_manager, 'HISTORY_DB', self.base/'history.db'),
                                    (cache, 'PROJECT', self.base), (cache, 'DB_PATH', self.base/'cache.db')]:
            self.stack.enter_context(patch.object(module, name, value))
        # Exercise the real external move engine, while fixtures stay inside test-downloads.
        self.stack.enter_context(patch.object(file_manager, 'is_test_folder', return_value=False))
        file_manager.history_init()

    def proposal(self, root):
        (root/'invoice.txt').write_text('Synthetic invoice example', encoding='utf-8')
        return file_manager.build_proposals(classifier.scan(root), 'Organize only', root)

    def test_real_moves_folder_categories_shared_cache_and_scoped_undo(self):
        for root, names in [(self.first, ('Finance', 'Other')), (self.second, ('Learning', 'Finance', 'Other'))]:
            categories.save(root, names)
            self.assertEqual(categories.load(root), names)
            p = self.proposal(root)
            self.assertIn('MOVED', file_manager.apply_proposals(p, root)[0][1])
        self.assertIn('RESTORED', file_manager.undo_last_batch(self.first)[0][1])
        self.assertTrue((self.first/'invoice.txt').is_file())
        self.assertTrue((self.second/'Finance'/'invoice.txt').is_file())
        self.assertIn('RESTORED', file_manager.undo_last_batch(self.second)[0][1])
        # Identical bytes can reuse a result across folders, with the same category policy.
        a, b = classifier.scan(self.first)[0], classifier.scan(self.second)[0]
        cfg = AIConfig()
        result = {'category':'Finance', 'suggested_name':'invoice.txt', 'reason':'fixture'}
        self.assertTrue(cache.content_cache_write(a, result, ('Finance', 'Other'), cfg))
        self.assertEqual(cache.content_cache_read(b, ('Finance', 'Other'), cfg), result)
        self.assertIsNone(cache.content_cache_read(b, ('Learning', 'Other'), cfg))

    def test_changed_content_and_replaced_identity_are_blocked(self):
        p = self.proposal(self.first)[0]
        p['src'].unlink()
        p['src'].write_text('Synthetic invoice example', encoding='utf-8')
        with self.assertRaises(OSError):
            windows_moves.move_verified(p['src'], p['dst'], self.first, p['sha256'], p['identity'])
        p['src'].write_text('Changed content', encoding='utf-8')
        with self.assertRaises(OSError):
            windows_moves.move_verified(p['src'], p['dst'], self.first, p['sha256'])
        self.assertTrue(p['src'].is_file())
        self.assertFalse(p['dst'].exists())

    def test_exact_unicode_names_in_all_modes(self):
        for index, mode in enumerate(config.MODES):
            root = self.base / str(index)
            root.mkdir()
            name = 'invoice_' + ('a' * index) + '_\u00e6\u00f8\u00e5.txt'
            (root/name).write_text('Synthetic invoice', encoding='utf-8')
            p = file_manager.build_proposals(classifier.scan(root), mode, root,
                                            {name: 'renamed_\u00e6\u00f8\u00e5.txt'})
            self.assertIn('MOVED', file_manager.apply_proposals(p, root)[0][1])
            self.assertTrue(p[0]['dst'].is_file())
            self.assertEqual([f.name for f in p[0]['dst'].parent.iterdir() if f.is_file()], [p[0]['dst'].name])
            self.assertIn('RESTORED', file_manager.undo_last_batch(root)[0][1])
            self.assertTrue((root/name).is_file())

    def test_real_open_writer_blocks_move_without_changing_content(self):
        p = self.proposal(self.first)[0]
        before = p['src'].read_bytes()
        with p['src'].open('r+b'):
            with self.assertRaises(OSError):
                windows_moves.move_verified(p['src'], p['dst'], self.first, p['sha256'], p['identity'])
        self.assertEqual(p['src'].read_bytes(), before)
        self.assertFalse(p['dst'].exists())

    def test_collision_including_race_never_overwrites(self):
        p = self.proposal(self.first)[0]
        original = windows_moves._rename
        def race(dll, handle, destination):
            destination.write_bytes(b'Concurrent file')
            return original(dll, handle, destination)
        with patch.object(windows_moves, '_rename', side_effect=race):
            with self.assertRaises(OSError):
                windows_moves.move_verified(p['src'], p['dst'], self.first, p['sha256'], p['identity'])
        self.assertEqual(p['dst'].read_bytes(), b'Concurrent file')
        self.assertTrue(p['src'].exists())

    def test_open_source_and_directory_are_locked_during_rename(self):
        p = self.proposal(self.first)[0]
        original = windows_moves._rename
        def check(dll, handle, destination):
            with self.assertRaises(OSError):
                p['src'].write_bytes(b'Concurrent change')
            with self.assertRaises(OSError):
                self.first.rename(self.base/'replaced')
            return original(dll, handle, destination)
        with patch.object(windows_moves, '_rename', side_effect=check):
            windows_moves.move_verified(p['src'], p['dst'], self.first, p['sha256'], p['identity'])
        self.assertTrue(p['dst'].is_file())

    def test_permission_failure_and_interruption_keep_pending_history(self):
        p = self.proposal(self.first)
        with patch.object(windows_moves, 'move_verified', side_effect=PermissionError('File is open or access denied')):
            self.assertIn('CHECK MANUALLY', file_manager.apply_proposals(p, self.first)[0][1])
        self.assertTrue(p[0]['src'].exists())
        self.assertTrue(file_manager.history_pending())
        with self.assertRaises(RuntimeError):
            file_manager.undo_last_batch(self.first)

    def test_failure_recording_completed_rename_leaves_recoverable_pending(self):
        p = self.proposal(self.first)
        with patch.object(file_manager, 'history_set', side_effect=RuntimeError('Simulated database failure')):
            with self.assertRaises(RuntimeError):
                file_manager.apply_proposals(p, self.first)
        self.assertFalse(p[0]['src'].exists())
        self.assertTrue(p[0]['dst'].is_file())
        self.assertTrue(file_manager.history_pending())
        with self.assertRaises(RuntimeError):
            file_manager.apply_proposals([], self.second)

    def test_revalidation_permission_failure_is_reported_without_moving(self):
        p = self.proposal(self.first)
        with patch.object(file_manager, 'revalidate', side_effect=PermissionError('Access denied')):
            self.assertIn('SKIPPED', file_manager.apply_proposals(p, self.first)[0][1])
        self.assertTrue(p[0]['src'].exists())
        self.assertFalse(file_manager.history_pending())

    def test_changed_undo_and_changed_batch_are_blocked(self):
        p = self.proposal(self.first)
        file_manager.apply_proposals(p, self.first)
        with self.assertRaises(RuntimeError):
            file_manager.undo_last_batch(self.first, expected_batch='stale-preview')
        p[0]['dst'].write_bytes(b'User edited content')
        self.assertIn('content was modified', file_manager.undo_last_batch(self.first)[0][1])

    def test_external_permission_is_session_scoped_and_identity_checked(self):
        with patch.object(folder_access, 'is_test_folder', return_value=False), \
             patch.object(folder_access, 'validate_external_folder', side_effect=lambda p: Path(p)):
            folder_access._approved.pop(str(self.first), None)
            with self.assertRaises(ValueError):
                folder_access.validate_operation_folder(self.first)
            folder_access.authorize_folder(self.first)
            self.assertEqual(folder_access.validate_operation_folder(self.first), self.first)
            folder_access._approved[str(self.first)] = (-1, -1)
            with self.assertRaises(ValueError):
                folder_access.validate_operation_folder(self.first)
            folder_access._approved.pop(str(self.first), None)

    def test_downloads_project_and_links_are_blocked(self):
        with self.assertRaises(ValueError):
            folder_access.validate_external_folder(config.PROJECT)
        with patch.object(config, 'validate_preview_folder', side_effect=ValueError('Downloads blocked')):
            with self.assertRaises(ValueError):
                folder_access.authorize_folder(self.first)
        with patch.object(Path, 'is_junction', autospec=True, side_effect=lambda p: p == self.first):
            with self.assertRaises(ValueError):
                folder_access.authorize_folder(self.first)
