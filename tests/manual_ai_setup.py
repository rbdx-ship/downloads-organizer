"""Opt-in wizard check using installed local Ollama; no installs or cloud calls."""
import sys
from pathlib import Path
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
import shiboken6
from organizer import config, ai_settings
from organizer.ai_setup_dialog import AISetupDialog


def wait_for_task(app, dialog):
    deadline = time.monotonic() + 240
    while dialog.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.05)
    if dialog.busy:
        raise RuntimeError('Setup task timed out.')


def run():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(dir=config.ROOT, prefix='organizer-setup-workflow-') as directory:
        path = Path(directory) / 'settings.json'
        dialog = AISetupDialog(settings_path=path)
        try:
            dialog.check_local()
            wait_for_task(app, dialog)
            assert 'Ollama is running' in dialog.status.text(), dialog.status.text()
            print('Wizard: installed local models detected', flush=True)
            dialog.test_selection()
            wait_for_task(app, dialog)
            assert dialog.save_btn.isEnabled(), dialog.status.text()
            assert dialog.verified.provider == 'ollama'
            print('Wizard: real structured classification test passed', flush=True)
            dialog.save_selection()
            assert ai_settings.load(path) == dialog.saved_config
            print('Wizard: configuration saved and reloaded in disposable test settings', flush=True)
        finally:
            dialog.close()
            shiboken6.delete(dialog)
    shiboken6.delete(app)


if __name__ == '__main__':
    run()
