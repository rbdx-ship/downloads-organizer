import importlib.util
import json
import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
import tempfile
import tkinter as tk
import httpx
import ollama
import types
import unittest
from unittest.mock import patch

from organizer import cache, classifier, config, file_manager, interface, database_migration, categories


class OrganizerTests(unittest.TestCase):
    def setUp(self):
        # All test files, including temporary databases, stay in the test folder.
        self.temp = tempfile.TemporaryDirectory(dir=config.ROOT, prefix='organizer-tests-')
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'files'
        self.root.mkdir()
        self.patches = [
            patch.object(classifier, 'ROOT', self.root),
            patch.object(file_manager, 'ROOT', self.root),
            patch.object(file_manager, 'PROJECT', self.base),
            patch.object(file_manager, 'HISTORY_DB', self.base / 'history.db'),
            patch.object(cache, 'PROJECT', self.base),
            patch.object(cache, 'DB_PATH', self.base / 'cache.db'),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(self.temp.cleanup)
        for p in self.patches:
            self.addCleanup(p.stop)

    def file(self, name, data=b'example'):
        (self.root / name).write_bytes(data)
        return classifier.scan()[0]

    def simulated_link(self, src, dst, **kwargs):
        # Sandbox denies hard links; exclusive creation preserves collision behavior.
        with open(src, 'rb') as source, open(dst, 'xb') as target:
            shutil.copyfileobj(source, target)

    def test_policy_matches_original(self):
        spec = importlib.util.spec_from_file_location('original_app', Path(__file__).resolve().parents[1] / 'downloads_organizer_app_step10_part2_repaired.py')
        original = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(original)
        self.assertEqual(config.POLICY_HASH, original.POLICY_HASH)
        self.assertEqual(config.MODEL, original.MODEL)

    def test_database_rename_copies_once_without_changing_original(self):
        old, new = self.base / 'old.db', self.base / 'new.db'
        with closing(sqlite3.connect(old)) as conn, conn:
            conn.execute('CREATE TABLE items (value TEXT)')
            conn.execute("INSERT INTO items VALUES ('original')")
        self.assertTrue(database_migration.copy_legacy_database(old, new))
        with closing(sqlite3.connect(new)) as conn, conn:
            self.assertEqual(conn.execute('SELECT value FROM items').fetchall(), [('original',)])
            conn.execute("INSERT INTO items VALUES ('new')")
        self.assertFalse(database_migration.copy_legacy_database(old, new))
        with closing(sqlite3.connect(old)) as conn, conn:
            self.assertEqual(conn.execute('SELECT value FROM items').fetchall(), [('original',)])
        with closing(sqlite3.connect(new)) as conn, conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM items').fetchone()[0], 2)

    def test_rules_and_filename_validation(self):
        self.assertEqual(classifier.rule_classify('invoice.pdf'), 'Finance')
        self.assertEqual(classifier.rule_classify('pic.JPG'), 'Images')
        self.assertIsNone(classifier.rule_classify('invoice_course.pdf'))
        for name in ('../bad.pdf', 'CON.pdf', 'bad?.pdf', 'name.txt'):
            self.assertFalse(file_manager.valid_filename(name, 'source.pdf'))
        self.assertTrue(file_manager.valid_filename('good.pdf', 'source.pdf'))

    def test_content_cache_reuse_and_policy_model_invalidation(self):
        f = self.file('first.txt')
        result = {'category': 'Learning', 'suggested_name': 'notes.txt', 'reason': 'test'}
        self.assertTrue(cache.content_cache_write(f, result))
        (self.root / 'second.txt').write_bytes(b'example')
        second = next(x for x in classifier.scan() if x['filename'] == 'second.txt')
        self.assertEqual(cache.content_cache_read(second), result)
        with patch.object(cache, 'POLICY_HASH', 'changed'):
            self.assertIsNone(cache.content_cache_read(second))
        with patch.object(cache, 'MODEL', 'changed'):
            self.assertIsNone(cache.content_cache_read(second))

    def test_folder_categories_partition_cache_and_support_undo(self):
        f = self.file('document.txt')
        file_manager.history_init()
        chosen = categories.save(self.root, ['Projects', 'Other'])
        result = {'category': 'Projects', 'suggested_name': 'notes.txt', 'reason': 'test'}
        self.assertTrue(cache.content_cache_write(f, result, chosen))
        self.assertEqual(cache.content_cache_read(f, chosen), result)
        self.assertIsNone(cache.content_cache_read(f, ('Work', 'Other')))
        proposal = file_manager.build_proposals([f], 'Rename + Organize', self.root, categories=chosen)
        self.assertEqual(proposal[0]['category'], 'Projects')
        with patch.object(file_manager.os, 'link', side_effect=self.simulated_link):
            self.assertIn('MOVED', file_manager.apply_proposals(proposal, self.root)[0][1])
            categories.save(self.root, ['Work', 'Other'])
            self.assertIn('RESTORED', file_manager.undo_last_batch(self.root)[0][1])
        self.assertTrue((self.root / 'document.txt').exists())

    def test_custom_category_names_are_validated(self):
        for names in (['../outside', 'Other'], ['CON', 'Other'], ['Work', 'work', 'Other'], ['Work']):
            with self.assertRaises(ValueError):
                categories.validate_categories(names)

    def test_batch_uses_numeric_ids(self):
        files = [self.file('a.txt')]
        response = types.SimpleNamespace(message=types.SimpleNamespace(content=json.dumps({'results': [
            {'file_id': 0, 'category': 'Finance', 'suggested_name': 'bill.txt', 'reason': 'test'}]})))
        with patch('ollama.chat', return_value=response) as chat:
            result = classifier.analyze_files(files)
        self.assertEqual(result['a.txt']['suggested_name'], 'bill.txt')
        payload = json.loads(chat.call_args.kwargs['messages'][1]['content'])
        self.assertEqual(payload[0]['file_id'], 0)

    def test_batch_uses_folder_categories(self):
        files = [self.file('a.txt')]
        response = types.SimpleNamespace(message=types.SimpleNamespace(content=json.dumps({'results': [
            {'file_id': 0, 'category': 'Projects', 'suggested_name': 'notes.txt', 'reason': 'test'}]})))
        with patch('ollama.chat', return_value=response) as chat:
            result = classifier.analyze_files(files, categories=('Projects', 'Other'))
        self.assertEqual(result['a.txt']['category'], 'Projects')
        self.assertIn('Projects, Other', chat.call_args.kwargs['messages'][0]['content'])

    def test_extraction_failure_is_reported(self):
        path = self.root / 'broken.pdf'
        path.write_bytes(b'not a PDF')
        warnings = []
        self.assertEqual(classifier.extract_content(path, warnings=warnings), '')
        self.assertIn('broken.pdf', warnings[0])
        self.assertIn('filename', warnings[0])

    def test_actionable_ollama_errors(self):
        self.assertIn('Start Ollama', classifier.analysis_error_message(httpx.ConnectError('offline')))
        self.assertIn('ollama list', classifier.analysis_error_message(ollama.ResponseError('missing', status_code=404)))

    def test_pending_operation_message_includes_paths(self):
        file_manager.history_init()
        file_manager.history_insert('id', 'batch', self.root / 'source.txt', self.root / 'Finance' / 'source.txt', 'hash')
        app = interface.OrganizerApp.__new__(interface.OrganizerApp)
        message = app.operation_error('Blocked')
        self.assertIn(str(self.root / 'source.txt'), message)
        self.assertIn('inspect', message.lower())

    def test_approved_move_and_undo(self):
        self.file('invoice.pdf')
        file_manager.history_init()
        proposals = file_manager.build_proposals(classifier.scan(), 'Organize only')
        self.assertIsNone(proposals[0]['issue'])
        self.assertTrue((self.root / 'invoice.pdf').exists())  # preview did not move it
        with patch.object(file_manager.os, 'link', side_effect=self.simulated_link):
            self.assertIn('MOVED', file_manager.apply_proposals(proposals)[0][1])
            self.assertTrue((self.root / 'Finance' / 'invoice.pdf').exists())
            self.assertIn('RESTORED', file_manager.undo_last_batch()[0][1])
        self.assertEqual((self.root / 'invoice.pdf').read_bytes(), b'example')

    def test_collision_and_modified_undo(self):
        self.file('invoice.pdf')
        file_manager.history_init()
        (self.root / 'Finance').mkdir()
        (self.root / 'Finance' / 'invoice.pdf').write_bytes(b'other')
        self.assertEqual(file_manager.build_proposals(classifier.scan(), 'Organize only')[0]['issue'], 'Destination already exists')
        (self.root / 'Finance' / 'invoice.pdf').unlink()
        proposals = file_manager.build_proposals(classifier.scan(), 'Organize only')
        with patch.object(file_manager.os, 'link', side_effect=self.simulated_link):
            file_manager.apply_proposals(proposals)
        (self.root / 'Finance' / 'invoice.pdf').write_bytes(b'changed')
        self.assertIn('content was modified', file_manager.undo_last_batch()[0][1])
        self.assertFalse((self.root / 'invoice.pdf').exists())

    def test_interrupted_undo_blocks_future_actions(self):
        self.file('invoice.pdf')
        file_manager.history_init()
        with patch.object(file_manager.os, 'link', side_effect=self.simulated_link):
            file_manager.apply_proposals(file_manager.build_proposals(classifier.scan(), 'Organize only'))
        with patch.object(file_manager.os, 'link', side_effect=OSError('interrupted')):
            self.assertIn('CHECK MANUALLY', file_manager.undo_last_batch()[0][1])
        self.assertTrue(file_manager.history_pending())
        with self.assertRaises(RuntimeError):
            file_manager.undo_last_batch()

    def test_destination_is_rechecked_before_link(self):
        self.file('invoice.pdf')
        file_manager.history_init()
        proposals = file_manager.build_proposals(classifier.scan(), 'Organize only')
        with patch.object(file_manager, 'revalidate', side_effect=[(True, 'OK'), (False, 'path changed')]), \
             patch.object(file_manager.os, 'link') as link:
            outcome = file_manager.apply_proposals(proposals)
        link.assert_not_called()
        self.assertIn('CHECK MANUALLY', outcome[0][1])
        self.assertTrue(file_manager.history_pending())
        self.assertTrue((self.root / 'invoice.pdf').exists())

    def test_linked_category_rejected(self):
        self.file('invoice.pdf')
        category = self.root / 'Finance'
        with patch.object(Path, 'is_junction', autospec=True, side_effect=lambda p: p == category):
            self.assertFalse(file_manager.safe_destination(category / 'invoice.pdf'))

    def test_folder_boundary_and_folder_specific_undo(self):
        first, second = self.root / 'first', self.root / 'second'
        first.mkdir()
        second.mkdir()
        for folder in (first, second):
            (folder / 'invoice.pdf').write_bytes(b'content')
        file_manager.history_init()
        with self.assertRaises(ValueError):
            config.validate_test_folder(config.ROOT.parent)
        with patch.object(file_manager.os, 'link', side_effect=self.simulated_link):
            for folder in (first, second):
                proposals = file_manager.build_proposals(classifier.scan(folder), 'Organize only', folder)
                self.assertTrue((folder / 'invoice.pdf').exists())
                self.assertIn('MOVED', file_manager.apply_proposals(proposals, folder)[0][1])
            self.assertIn('RESTORED', file_manager.undo_last_batch(first)[0][1])
        self.assertTrue((first / 'invoice.pdf').exists())
        self.assertTrue((second / 'Finance' / 'invoice.pdf').exists())
        self.assertFalse((second / 'invoice.pdf').exists())

    def test_switch_folder_clears_preview_and_requires_preview(self):
        self.file('invoice.pdf')
        other = self.root / 'other'
        other.mkdir()
        with patch.object(interface, 'ROOT', self.root), patch.object(interface, 'history_init'):
            window = tk.Tk()
            window.withdraw()
            try:
                app = interface.OrganizerApp(window)
                app.refresh()
                app.tree.selection_set('file:0')
                with patch.object(interface.messagebox, 'showinfo') as info, \
                     patch.object(interface, 'apply_proposals') as apply:
                    app.confirm_apply()
                self.assertEqual(info.call_args.args[0], 'Preview required')
                apply.assert_not_called()
                with patch.object(interface.messagebox, 'showinfo'):
                    app.show_preview()
                self.assertEqual(app.preview_root, self.root)
                with patch.object(interface.filedialog, 'askdirectory', return_value=str(other)), \
                     patch.object(interface.simpledialog, 'askstring', return_value='no'):
                    app.choose_folder()
                self.assertEqual(app.selected_root, self.root)
                self.assertEqual(app.preview_root, self.root)
                self.assertTrue(app.tree.get_children())
                with patch.object(interface.filedialog, 'askdirectory', return_value=str(other)), \
                     patch.object(interface.simpledialog, 'askstring', return_value='YES'):
                    app.choose_folder()
                self.assertEqual(app.selected_root, other)
                self.assertIsNone(app.preview_root)
                self.assertFalse(app.tree.get_children())
            finally:
                window.destroy()

    def test_readonly_mode_disables_changes_and_ai(self):
        self.file('invoice.pdf')
        with patch.object(interface, 'ROOT', self.root), patch.object(interface, 'history_init'):
            window = tk.Tk()
            window.withdraw()
            try:
                app = interface.OrganizerApp(window)
                app.read_only = True
                app.set_busy(False)
                app.refresh()
                self.assertEqual(app.proposals[0]['issue'], 'Read-only preview')
                self.assertTrue(app.apply_btn.instate(['disabled']))
                self.assertTrue(app.ai_btn.instate(['disabled']))
                self.assertTrue(app.undo_btn.instate(['disabled']))
                with patch.object(interface.messagebox, 'showinfo'):
                    app.show_preview()
                with patch.object(interface, 'apply_proposals') as apply, \
                     patch.object(interface, 'undo_last_batch') as undo, \
                     patch.object(interface, 'analyze_files') as analyze:
                    app.confirm_apply()
                    app.confirm_undo()
                    app.analyze()
                apply.assert_not_called()
                undo.assert_not_called()
                analyze.assert_not_called()
                self.assertEqual((self.root / 'invoice.pdf').read_bytes(), b'example')
                self.assertFalse(cache.DB_PATH.exists())
            finally:
                window.destroy()

    def test_edited_name_checks_collisions(self):
        self.file('invoice.pdf')
        (self.root / 'Finance').mkdir()
        (self.root / 'Finance' / 'taken.pdf').write_bytes(b'other')
        proposals = file_manager.build_proposals(classifier.scan(), 'Rename + Organize', self.root,
                                                  {'invoice.pdf': 'taken.pdf'})
        self.assertEqual(proposals[0]['issue'], 'Destination already exists')
        proposals = file_manager.build_proposals(classifier.scan(), 'Rename + Organize', self.root,
                                                  {'invoice.pdf': '../bad.pdf'})
        self.assertEqual(proposals[0]['issue'], 'Unsafe filename or changed extension')

    def test_edit_name_invalidates_gui_preview(self):
        self.file('invoice.pdf')
        with patch.object(interface, 'ROOT', self.root), patch.object(interface, 'history_init'):
            window = tk.Tk()
            window.withdraw()
            try:
                app = interface.OrganizerApp(window)
                app.refresh()
                with patch.object(interface.messagebox, 'showinfo'):
                    app.show_preview()
                app.tree.selection_set('file:0')
                with patch.object(interface.simpledialog, 'askstring', return_value='bill.pdf'):
                    app.edit_name()
                self.assertIsNone(app.preview_root)
                self.assertEqual(app.proposals[0]['dst'].name, 'bill.pdf')
                self.assertTrue((self.root / 'invoice.pdf').exists())
            finally:
                window.destroy()

    def test_table_shows_files_not_folders(self):
        self.file('invoice.pdf')
        (self.root / 'Existing folder').mkdir()
        (self.root / 'Existing folder' / 'nested.txt').write_text('nested')
        self.assertEqual([f['filename'] for f in classifier.scan()], ['invoice.pdf'])
        with patch.object(interface, 'ROOT', self.root), patch.object(interface, 'history_init'):
            window = tk.Tk()
            window.withdraw()
            try:
                app = interface.OrganizerApp(window)
                app.refresh()
                self.assertEqual(app.tree.get_children(), ('file:0',))
                self.assertEqual(app.tree.item('file:0', 'values')[0], 'invoice.pdf')
                self.assertTrue((self.root / 'invoice.pdf').exists())
            finally:
                window.destroy()


if __name__ == '__main__':
    unittest.main()
