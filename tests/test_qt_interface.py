import shutil
import tempfile
import unittest
import threading
import time
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox, QDialog
from PySide6.QtCore import Qt
import shiboken6
from organizer import cache, classifier, config, file_manager, qt_interface, categories, safety_settings, folder_access
from organizer.ai_settings import AIConfig


class QtInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.application.processEvents()
        shiboken6.delete(cls.application)
        cls.application = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=config.ROOT, prefix='organizer-qt-tests-')
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'files'
        self.root.mkdir()
        patches = [
            patch.object(file_manager, 'PROJECT', self.base),
            patch.object(file_manager, 'HISTORY_DB', self.base / 'history.db'),
            patch.object(cache, 'DB_PATH', self.base / 'cache.db'),
            patch.object(cache, 'PROJECT', self.base),
            patch.object(safety_settings, 'SETTINGS_PATH', self.base / 'safety_settings.json'),
            patch.object(qt_interface.QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(self.temp.cleanup)
        self.window = qt_interface.OrganizerWindow(root=self.root)
        summary = patch.object(self.window, 'show_classification_summary')
        summary.start()
        self.addCleanup(summary.stop)
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.close()
        shiboken6.delete(self.window)

    def test_safety_setting_requires_exact_confirmation(self):
        self.window.classified = True
        with patch.object(qt_interface.QInputDialog, 'getText', side_effect=[('Incoming', True), ('yes', True)]):
            self.window.edit_safety_settings()
        self.assertEqual(safety_settings.required_name(), 'Downloads')
        self.assertFalse(safety_settings.SETTINGS_PATH.exists())
        with patch.object(qt_interface.QInputDialog, 'getText', side_effect=[('Incoming', True), ('YES', True)]):
            self.window.edit_safety_settings()
        self.assertEqual(safety_settings.required_name(), 'Incoming')
        self.assertFalse(self.window.classified)

    def test_safety_setting_change_revokes_current_external_access(self):
        self.window.classified = True
        with patch.object(qt_interface, 'is_test_folder', return_value=False), \
             patch.object(qt_interface.QInputDialog, 'getText', side_effect=[('Incoming', True), ('YES', True)]):
            self.window.edit_safety_settings()
        self.assertTrue(self.window.read_only)
        self.assertIsNone(self.window.categories)
        self.assertFalse(self.window.apply_btn.isEnabled())

    def test_corrupt_safety_settings_can_be_repaired_to_default(self):
        safety_settings.SETTINGS_PATH.write_text('not valid JSON', encoding='utf-8')
        with patch.object(qt_interface.QMessageBox, 'warning'), \
             patch.object(qt_interface.QInputDialog, 'getText', side_effect=[('Downloads', True), ('YES', True)]):
            self.window.edit_safety_settings()
        self.assertEqual(safety_settings.required_name(), 'Downloads')

    @staticmethod
    def simulated_link(src, dst, **kwargs):
        with open(src, 'rb') as source, open(dst, 'xb') as target:
            shutil.copyfileobj(source, target)

    def test_review_approval_move_and_undo(self):
        (self.root / 'invoice.pdf').write_bytes(b'fixture')
        self.window.refresh()
        self.window.categories = config.CATEGORIES
        self.window.analyze()
        self.assertEqual(self.window.selected_rows(), [0])
        with patch.object(qt_interface.ApprovalDialog, 'exec', return_value=QDialog.DialogCode.Rejected), \
             patch.object(qt_interface, 'apply_proposals') as apply:
            self.window.confirm_apply()
        apply.assert_not_called()
        self.assertTrue((self.root / 'invoice.pdf').exists())
        with patch.object(qt_interface.QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes), \
             patch.object(qt_interface.ApprovalDialog, 'exec', return_value=QDialog.DialogCode.Accepted), \
             patch.object(qt_interface.ConfirmMoveDialog, 'exec', return_value=QDialog.DialogCode.Accepted), \
             patch.object(qt_interface.QMessageBox, 'information'), \
             patch.object(file_manager.os, 'link', side_effect=self.simulated_link):
            self.window.confirm_apply()
            self.assertTrue((self.root / 'Finance' / 'invoice.pdf').exists())
            self.window.confirm_undo()
        self.assertEqual((self.root / 'invoice.pdf').read_bytes(), b'fixture')

    def test_move_confirmation_requires_exact_yes(self):
        dialog = qt_interface.ConfirmMoveDialog(self.root, 1)
        try:
            self.assertFalse(dialog.confirm_button.isEnabled())
            dialog.answer.setText('yes')
            dialog.accept()
            self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertFalse(dialog.confirm_button.isEnabled())
            dialog.answer.setText('YES')
            self.assertTrue(dialog.confirm_button.isEnabled())
            dialog.accept()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        finally:
            dialog.close()

    def test_cancel_final_confirmation_never_moves(self):
        (self.root / 'invoice.pdf').write_bytes(b'fixture')
        self.window.refresh()
        self.window.categories = config.CATEGORIES
        self.window.analyze()
        with patch.object(qt_interface.ApprovalDialog, 'exec', return_value=QDialog.DialogCode.Accepted), \
             patch.object(qt_interface.ConfirmMoveDialog, 'exec', return_value=QDialog.DialogCode.Rejected), \
             patch.object(qt_interface, 'apply_proposals') as apply:
            self.window.confirm_apply()
        apply.assert_not_called()
        self.assertTrue((self.root / 'invoice.pdf').exists())

    def test_folder_confirmation_and_edit(self):
        (self.root / 'invoice.pdf').write_bytes(b'fixture')
        other = self.root / 'other'
        other.mkdir()
        self.window.refresh()
        self.window.categories = config.CATEGORIES
        self.window.analyze()
        self.window.table.selectRow(0)
        self.assertEqual(self.window.proposals[0]['dst'].name, 'invoice.pdf')
        self.assertTrue(self.window.edit_btn.isHidden())
        with patch.object(qt_interface.QFileDialog, 'getExistingDirectory', return_value=str(other)), \
             patch.object(qt_interface.QInputDialog, 'getText', return_value=('no', True)):
            self.window.choose_folder()
        self.assertEqual(self.window.selected_root, self.root)
        with patch.object(qt_interface.QFileDialog, 'getExistingDirectory', return_value=str(other)), \
             patch.object(qt_interface.QInputDialog, 'getText', return_value=('YES', True)):
            self.window.choose_folder()
        self.assertEqual(self.window.selected_root, other)
        self.assertEqual(self.window.table.rowCount(), 0)

    def test_readonly_disables_operations(self):
        (self.root / 'invoice.pdf').write_bytes(b'fixture')
        self.window.read_only = True
        self.window.set_busy(False)
        self.window.refresh()
        self.assertEqual(self.window.proposals[0]['issue'], 'Read-only preview')
        for button in (self.window.apply_btn, self.window.undo_btn, self.window.ai_btn, self.window.edit_btn):
            self.assertFalse(button.isEnabled())
        with patch.object(qt_interface, 'apply_proposals') as apply, \
             patch.object(qt_interface, 'undo_last_batch') as undo:
            self.window.confirm_apply()
            self.window.confirm_undo()
        apply.assert_not_called()
        undo.assert_not_called()
        self.assertTrue((self.root / 'invoice.pdf').exists())

    def test_category_setup_persists_and_invalidates_classification(self):
        (self.root / 'invoice.pdf').write_bytes(b'fixture')
        self.window.refresh()
        with patch.object(qt_interface.QInputDialog, 'getMultiLineText', return_value=('Finance\nPersonal\nOther', True)):
            self.assertTrue(self.window.edit_categories())
        self.assertEqual(categories.load(self.root), ('Finance', 'Personal', 'Other'))
        self.window.analyze()
        self.assertEqual(self.window.proposals[0]['category'], 'Finance')
        with patch.object(qt_interface.QInputDialog, 'getMultiLineText', return_value=('Personal\nOther', True)):
            self.assertTrue(self.window.edit_categories())
        self.assertFalse(self.window.classified)

    def test_external_folder_requires_mode_choice_and_exact_yes(self):
        other = self.root / 'external-mode-fixture'
        other.mkdir()
        with patch.object(qt_interface.QFileDialog, 'getExistingDirectory', return_value=str(other)), \
             patch.object(qt_interface, 'validate_test_folder', side_effect=ValueError('External')), \
             patch.object(qt_interface, 'validate_preview_folder', return_value=other), \
             patch.object(qt_interface, 'validate_external_folder', return_value=other), \
             patch.object(qt_interface.QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes), \
             patch.object(qt_interface.QInputDialog, 'getText', return_value=('yes', True)), \
             patch.object(qt_interface, 'authorize_folder') as authorize:
            self.window.choose_folder()
            self.assertEqual(self.window.selected_root, self.root)
            authorize.assert_not_called()
            with patch.object(qt_interface.QInputDialog, 'getText', return_value=('YES', True)):
                self.window.choose_folder()
            authorize.assert_called_once_with(other)
            self.assertEqual(self.window.selected_root, other)
            self.assertFalse(self.window.read_only)

    def test_external_readonly_choice_never_grants_write_access(self):
        other = self.root / 'readonly-fixture'
        other.mkdir()
        with patch.object(qt_interface.QFileDialog, 'getExistingDirectory', return_value=str(other)), \
             patch.object(qt_interface, 'validate_test_folder', side_effect=ValueError('External')), \
             patch.object(qt_interface, 'validate_preview_folder', return_value=other), \
             patch.object(qt_interface, 'validate_external_folder', return_value=other), \
             patch.object(qt_interface.QMessageBox, 'question', return_value=QMessageBox.StandardButton.No), \
             patch.object(qt_interface.QInputDialog, 'getText', return_value=('YES', True)), \
             patch.object(qt_interface, 'authorize_folder') as authorize:
            self.window.choose_folder()
            authorize.assert_not_called()
            self.assertTrue(self.window.read_only)
            # Selecting this same folder again can upgrade from read-only after consent.
            with patch.object(qt_interface.QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
                self.window.choose_folder()
            authorize.assert_called_once_with(other)
            self.assertFalse(self.window.read_only)

    def test_downloads_selection_previews_before_writable_confirmation(self):
        other = self.root / 'Downloads'
        other.mkdir()
        (other / 'invoice.txt').write_text('Synthetic fixture')
        with patch.object(folder_access, '_previewed_downloads', {}), \
             patch.object(folder_access, '_approved', {}), \
             patch.object(qt_interface.QFileDialog, 'getExistingDirectory', return_value=str(other)), \
             patch.object(qt_interface, 'validate_test_folder', side_effect=ValueError('External')), \
             patch.object(qt_interface, 'validate_preview_folder', return_value=other), \
             patch.object(qt_interface, 'is_real_downloads', return_value=True), \
             patch.object(config, 'is_real_downloads', return_value=True), \
             patch.object(qt_interface, 'validate_external_folder', return_value=other), \
             patch.object(folder_access, 'validate_external_folder', return_value=other), \
             patch.object(qt_interface.QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes) as question, \
             patch.object(qt_interface.QInputDialog, 'getText', return_value=('YES', True)):
            self.window.choose_folder()
            self.assertTrue(self.window.read_only)
            self.assertEqual(self.window.table.rowCount(), 1)
            question.assert_not_called()
            self.window.choose_folder()
            question.assert_called_once()
            self.assertFalse(self.window.read_only)

    def test_select_all_checks_only_ready_files(self):
        (self.root / 'invoice.pdf').write_bytes(b'finance')
        (self.root / 'course.txt').write_bytes(b'learning')
        (self.root / 'ambiguous.txt').write_bytes(b'unknown')
        self.window.refresh()
        self.window.categories = config.CATEGORIES
        self.window.classified = True
        self.window.prepare()
        self.assertEqual(len(self.window.selected_rows()), 2)
        self.window.select_all.setCheckState(Qt.CheckState.Unchecked)
        self.assertEqual(self.window.selected_rows(), [])
        self.window.select_all.setCheckState(Qt.CheckState.Checked)
        self.assertEqual(len(self.window.selected_rows()), 2)
        self.assertTrue(all(not self.window.proposals[row]['issue'] for row in self.window.selected_rows()))

    def test_classification_counts_include_unresolved_and_cached_results(self):
        counts = qt_interface.classification_counts([
            {'method': 'Python rules'}, {'method': 'Content cache'},
            {'method': 'Path cache'}, {'method': 'Needs AI'}])
        self.assertEqual(counts, {'Python rules': 1, 'AI / cached AI': 2, 'Unresolved': 1})
        dialog = qt_interface.ClassificationSummary(counts)
        self.assertIsNotNone(dialog.findChild(qt_interface.ClassificationChart))
        dialog.close()

    def test_progress_indicators_track_busy_state(self):
        self.window.set_busy(True)
        self.assertFalse(self.window.progress_row.isHidden())
        self.assertTrue(self.window.spinner.timer.isActive())
        self.assertEqual((self.window.progress_bar.minimum(), self.window.progress_bar.maximum()), (0, 0))
        self.window.set_busy(False)
        self.assertTrue(self.window.progress_row.isHidden())
        self.assertFalse(self.window.spinner.timer.isActive())

    def test_rule_only_classification_shows_summary(self):
        (self.root / 'invoice.pdf').write_bytes(b'fixture')
        self.window.refresh()
        self.window.categories = config.CATEGORIES
        self.window.analyze()
        self.window.show_classification_summary.assert_called_once()

    def test_classification_confirmation_has_time_and_cancel_preserves_state(self):
        (self.root / 'ambiguous.txt').write_text('Synthetic document')
        self.window.refresh()
        self.window.categories = config.CATEGORIES
        with patch.object(qt_interface.QMessageBox, 'question', return_value=QMessageBox.StandardButton.No) as question, \
             patch.object(qt_interface, 'analyze_files') as analyze:
            self.window.analyze()
        self.assertIn('Estimated duration:', question.call_args.args[2])
        self.assertIn('1 unique files will use AI', question.call_args.args[2])
        analyze.assert_not_called()
        self.assertFalse(self.window.classified)
        self.assertFalse(self.window.busy)
        self.assertFalse(cache.DB_PATH.exists())

    def test_live_eta_and_batch_progress_stop_after_worker_finishes(self):
        (self.root / 'ambiguous.txt').write_text('Synthetic document')
        self.window.refresh()
        self.window.categories = config.CATEGORIES
        gate = threading.Event()
        def analyze(*args, **kwargs):
            gate.wait(5)
            return {'ambiguous.txt': {'category':'Learning', 'suggested_name':'notes.txt', 'reason':'fixture'}}
        with patch.object(qt_interface, 'analyze_files', side_effect=analyze):
            try:
                self.window.analyze()
                self.assertTrue(self.window.busy)
                self.assertTrue(self.window.eta_timer.isActive())
                self.assertIn('Estimated remaining:', self.window.progress_label.text())
                self.assertEqual(self.window.progress_bar.maximum(), 1)
                self.window._run_timing.started -= 1000
                self.window.update_classification_eta()
                self.assertIn('Taking longer than estimated', self.window.progress_label.text())
            finally:
                gate.set()
                deadline = time.monotonic() + 5
                while self.window.busy and time.monotonic() < deadline:
                    self.application.processEvents()
                    time.sleep(.01)
        self.assertFalse(self.window.busy)
        self.assertFalse(self.window.eta_timer.isActive())
        self.assertEqual(self.window.progress_bar.value(), 1)
        self.assertEqual(len(self.window._timing_samples[self.window.ai_config.cache_model]), 1)

    def test_workflow_primary_action_tracks_classification_and_checks(self):
        self.assertFalse(self.window.ai_btn.isEnabled())
        self.assertTrue(self.window.apply_btn.isHidden())
        self.assertTrue(self.window.empty_label.isVisibleTo(self.window.centralWidget()))
        (self.root / 'invoice.pdf').write_bytes(b'fixture')
        self.window.refresh()
        self.assertTrue(self.window.ai_btn.isEnabled())
        self.assertFalse(self.window.ai_btn.isHidden())
        self.assertTrue(self.window.apply_btn.isHidden())
        self.assertTrue(self.window.table.isColumnHidden(2))
        self.assertFalse(self.window.undo_btn.isEnabled())

        self.window.categories = config.CATEGORIES
        self.window.analyze()
        self.assertTrue(self.window.ai_btn.isHidden())
        self.assertFalse(self.window.apply_btn.isHidden())
        self.assertTrue(self.window.apply_btn.isEnabled())
        self.assertIn('1 file', self.window.apply_btn.text())
        self.assertTrue(self.window.table.isColumnHidden(2))
        self.assertTrue(self.window.table.isColumnHidden(4))
        self.window.details_toggle.setChecked(True)
        self.assertFalse(self.window.table.isColumnHidden(4))
        self.assertEqual(self.window.selected_rows(), [0])
        self.assertTrue(self.window.mode_box.isHidden())
        self.assertFalse(self.window.edit_btn.isEnabled())
        self.window.table.selectRow(0)
        self.assertFalse(self.window.edit_btn.isEnabled())
        self.assertEqual(self.window.selected_rows(), [0])

        self.window.select_all.setCheckState(Qt.CheckState.Unchecked)
        self.assertFalse(self.window.apply_btn.isEnabled())
        self.assertIn('0 files', self.window.apply_btn.text())
        self.window.refresh()
        self.assertFalse(self.window.ai_btn.isHidden())
        self.assertTrue(self.window.apply_btn.isHidden())
        self.assertTrue(self.window.selection_bar.isHidden())

    def test_busy_state_locks_actions_and_readonly_has_no_forward_action(self):
        (self.root / 'invoice.pdf').write_bytes(b'fixture')
        self.window.refresh()
        self.window.set_busy(True)
        for control in (self.window.folder_btn, self.window.scan_btn, self.window.category_btn,
                        self.window.ai_btn, self.window.apply_btn, self.window.table):
            self.assertFalse(control.isEnabled())
        self.window.set_busy(False)
        self.window.read_only = True
        self.window.refresh()
        self.assertTrue(self.window.ai_btn.isHidden())
        self.assertTrue(self.window.apply_btn.isHidden())
        self.assertTrue(self.window.mode_box.isHidden())
        self.assertFalse(self.window.category_btn.isEnabled())

    def test_rules_only_classifies_rules_without_contacting_ai(self):
        (self.root / 'invoice.pdf').write_bytes(b'finance')
        (self.root / 'ambiguous.txt').write_bytes(b'unknown')
        self.window.ai_config = AIConfig('rules', '')
        self.window.categories = config.CATEGORIES
        self.window.refresh()
        with patch.object(qt_interface, 'analyze_files') as analyze:
            self.window.analyze()
        analyze.assert_not_called()
        self.assertEqual(len(self.window.selected_rows()), 1)
        self.assertFalse(self.window.busy)

    def test_rejecting_cloud_consent_sends_no_document(self):
        (self.root / 'ambiguous.txt').write_text('private document fixture')
        self.window.ai_config = AIConfig('openai', 'gpt-4o-mini', True)
        self.window.categories = config.CATEGORIES
        self.window.refresh()
        with patch.object(qt_interface.QMessageBox, 'question', return_value=QMessageBox.StandardButton.No), \
             patch.object(qt_interface, 'analyze_files') as analyze:
            self.window.analyze()
        analyze.assert_not_called()
        self.assertFalse(self.window.busy)
        self.assertFalse(cache.DB_PATH.exists())

    def test_changing_provider_clears_classification(self):
        (self.root / 'invoice.pdf').write_bytes(b'finance')
        self.window.categories = config.CATEGORIES
        self.window.refresh()
        self.window.analyze()
        with patch.object(qt_interface, 'AISetupDialog') as dialog:
            dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
            dialog.return_value.saved_config = AIConfig('rules', '')
            self.window.edit_ai_settings()
        self.assertFalse(self.window.classified)
        self.assertEqual(self.window.ai_config.provider, 'rules')


if __name__ == '__main__':
    unittest.main()
