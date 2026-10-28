"""Opt-in external-folder safety smoke test, using only generated fixtures.

Creates a disposable sibling folder outside the checkout, with isolated databases
inside test-downloads. Dialog answers are automated; no AI calls or user files.
"""
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
import shiboken6
from organizer import cache, categories, config, file_manager, folder_access, qt_interface
from organizer.ai_settings import AIConfig


def run():
    app = QApplication([])
    parent = config.PROJECT.parent.resolve()
    with tempfile.TemporaryDirectory(dir=parent, prefix='organizer-external-smoke-') as outside, \
         tempfile.TemporaryDirectory(dir=config.ROOT, prefix='external-smoke-data-') as data, ExitStack() as stack:
        base, data = Path(outside).resolve(), Path(data).resolve()
        assert base.parent == parent and base.name.startswith('organizer-external-smoke-')
        first, second = base/'first', base/'second'
        for folder in (first, second):
            folder.mkdir()
            (folder/'invoice.txt').write_text('Synthetic invoice fixture', encoding='utf-8')
        for module, name, value in [(file_manager, 'PROJECT', data), (file_manager, 'HISTORY_DB', data/'history.db'),
                                    (cache, 'PROJECT', data), (cache, 'DB_PATH', data/'cache.db')]:
            stack.enter_context(patch.object(module, name, value))
        stack.enter_context(patch.object(qt_interface.QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes))
        stack.enter_context(patch.object(qt_interface.QInputDialog, 'getText', return_value=('YES', True)))
        review = stack.enter_context(patch.object(qt_interface.ApprovalDialog, 'exec', return_value=QDialog.DialogCode.Accepted))
        stack.enter_context(patch.object(qt_interface.ClassificationSummary, 'exec', return_value=1))
        stack.enter_context(patch.object(qt_interface.QMessageBox, 'information'))
        errors = stack.enter_context(patch.object(qt_interface.QMessageBox, 'critical'))
        window = qt_interface.OrganizerWindow(ai_config=AIConfig('rules', ''))

        def choose(folder):
            with patch.object(qt_interface.QFileDialog, 'getExistingDirectory', return_value=str(folder)):
                window.choose_folder()
            assert window.selected_root == folder and not window.read_only
            assert window.mode_badge.text() == 'Approved folder'

        try:
            for folder, names in [(first, 'Finance\nOther'), (second, 'Finance\nLearning\nOther')]:
                choose(folder)
                with patch.object(qt_interface.QInputDialog, 'getMultiLineText', return_value=(names, True)):
                    assert window.edit_categories()
                window.analyze()
                assert window.proposals[0]['issue'] is None
                window.confirm_apply()
                assert (folder/'Finance'/'invoice.txt').is_file()
                assert not (folder/'invoice.txt').exists()
            assert review.call_count == 2
            choose(first)
            window.confirm_undo()
            assert (first/'invoice.txt').is_file()
            assert (second/'Finance'/'invoice.txt').is_file()
            assert categories.load(first) == ('Finance', 'Other')
            assert categories.load(second) == ('Finance', 'Learning', 'Other')
            window.close()
            shiboken6.delete(window)
            folder_access._approved.clear()  # Simulate a fresh process: reapproval required.
            window = qt_interface.OrganizerWindow(ai_config=AIConfig('rules', ''))
            choose(second)
            window.confirm_undo()
            assert (second/'invoice.txt').is_file()
            assert not file_manager.history_pending()
            assert not errors.called, errors.call_args_list
            print('PASS: external selection, classification, review, real moves, separate categories, shared history, and folder-specific Undo after reopening.')
        finally:
            window.close()
            shiboken6.delete(window)
            folder_access._approved.clear()
    app.processEvents()
    shiboken6.delete(app)


if __name__ == '__main__':
    run()
