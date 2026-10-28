from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog
import shiboken6

from organizer import config, ai_settings, ai_setup_dialog


class AISetupDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.app.processEvents()
        shiboken6.delete(cls.app)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=config.ROOT, prefix='organizer-setup-tests-')
        self.path = Path(self.temp.name) / 'settings.json'
        self.addCleanup(self.temp.cleanup)
        self.dialog = ai_setup_dialog.AISetupDialog(settings_path=self.path)
        self.addCleanup(self.dispose)

    def dispose(self):
        self.dialog.close()
        shiboken6.delete(self.dialog)

    def wait_for_task(self):
        deadline = time.monotonic() + 5
        while self.dialog.busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertFalse(self.dialog.busy)

    def test_rules_can_finish_without_downloading_or_testing(self):
        self.dialog.provider_combo.setCurrentIndex(2)
        self.assertTrue(self.dialog.save_btn.isEnabled())
        self.dialog.save_selection()
        self.assertEqual(ai_settings.load(self.path).provider, 'rules')
        self.assertEqual(self.dialog.result(), QDialog.DialogCode.Accepted)

    def test_local_test_is_required_and_model_changes_invalidate_it(self):
        self.dialog.save_selection()
        self.assertFalse(self.path.exists())
        with patch.object(ai_setup_dialog.ai_setup_tasks, 'test_config', return_value='Test passed'):
            self.dialog.test_selection()
            self.wait_for_task()
        self.assertTrue(self.dialog.save_btn.isEnabled())
        self.dialog.local_model.setCurrentText('different-model')
        self.assertFalse(self.dialog.save_btn.isEnabled())
        self.assertIsNone(self.dialog.verified)

    def test_cloud_requires_consent_before_any_test(self):
        self.dialog.provider_combo.setCurrentIndex(1)
        self.dialog.key_edit.setText('fake-test-key')
        with patch.object(ai_setup_dialog.ai_setup_tasks, 'test_config') as test:
            self.dialog.test_selection()
        test.assert_not_called()
        self.assertFalse(self.dialog.busy)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.dialog.key_edit.echoMode(), self.dialog.key_edit.EchoMode.Password)

    def test_first_run_cancel_is_temporary_and_existing_setup_is_reused(self):
        with patch.object(ai_setup_dialog.ai_settings, 'load', return_value=None), \
             patch.object(ai_setup_dialog, 'AISetupDialog') as setup:
            setup.return_value.exec.return_value = QDialog.DialogCode.Rejected
            result = ai_setup_dialog.startup_config()
        self.assertEqual(result.provider, 'rules')
        chosen = ai_settings.AIConfig()
        with patch.object(ai_setup_dialog.ai_settings, 'load', return_value=chosen), \
             patch.object(ai_setup_dialog, 'AISetupDialog') as setup:
            self.assertEqual(ai_setup_dialog.startup_config(), chosen)
        setup.assert_not_called()


if __name__ == '__main__':
    unittest.main()
