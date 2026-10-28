"""Opt-in PySide6 workflow check with real Ollama and test-file operations."""
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog
from organizer import cache, config, file_manager, qt_interface


def run():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(dir=config.ROOT, prefix='organizer-qt-workflow-') as temp:
        base = Path(temp).resolve()
        root = base / 'files'
        root.mkdir()
        (root / 'document.txt').write_text('This document is a beginner guide to Python programming and functions.', encoding='utf-8')
        with patch.object(file_manager, 'PROJECT', base), \
             patch.object(file_manager, 'HISTORY_DB', base / 'history.db'), \
             patch.object(cache, 'PROJECT', base), patch.object(cache, 'DB_PATH', base / 'cache.db'), \
             patch.object(qt_interface.QMessageBox, 'information') as info, \
             patch.object(qt_interface.QMessageBox, 'warning') as warning, \
             patch.object(qt_interface.QMessageBox, 'critical') as error, \
             patch.object(qt_interface.ClassificationSummary, 'exec', return_value=1) as summary, \
             patch.object(qt_interface.ApprovalDialog, 'exec', return_value=QDialog.DialogCode.Accepted) as review, \
             patch.object(qt_interface.QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes), \
             patch.object(qt_interface.QInputDialog, 'getText', return_value=('YES', True)):
            window = qt_interface.OrganizerWindow(root=root)
            try:
                window.refresh()
                assert len(window.files) == 1 and not window.classified
                print('Scan: ambiguous test document found', flush=True)
                window.categories = config.CATEGORIES
                window.analyze()
                assert not window.progress_row.isHidden() and window.spinner.timer.isActive()
                deadline = time.monotonic() + 240
                while window.busy and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(.05)
                assert not window.busy, 'Ollama analysis timed out'
                assert window.progress_row.isHidden() and summary.called
                assert not warning.called, warning.call_args_list
                assert window.proposals[0]['issue'] is None, window.proposals[0]
                print('Ollama: real analysis produced a ready proposal', flush=True)
                assert (root / 'document.txt').exists() and window.selected_rows() == [0]
                destination = window.proposals[0]['dst']
                window.confirm_apply()
                assert review.called
                assert not error.called, error.call_args_list
                assert destination.is_file() and not (root / 'document.txt').exists()
                print('Preview and approved move: real file moved', flush=True)
                window.close()
                window = qt_interface.OrganizerWindow(root=root)
                window.confirm_undo()
                assert not error.called, error.call_args_list
                assert (root / 'document.txt').read_text(encoding='utf-8').startswith('This document')
                assert not destination.exists()
                print('Reopened window and Undo: original restored', flush=True)
            finally:
                window.close()


if __name__ == '__main__':
    run()
