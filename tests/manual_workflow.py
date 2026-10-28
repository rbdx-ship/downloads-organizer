"""Opt-in end-to-end check using real Ollama and file operations.

Run only with Ollama started. Creates disposable files under test-downloads.
"""
import sys
import subprocess
import tempfile
import time
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from organizer import cache, classifier, config, file_manager, interface


def run():
    with tempfile.TemporaryDirectory(dir=config.ROOT, prefix='organizer-workflow-') as temp:
        base = Path(temp).resolve()
        root = base / 'files'
        root.mkdir()
        (root / 'document.txt').write_text('This document is a beginner guide to Python programming and functions.', encoding='utf-8')
        patches = [patch.object(module, name, value) for module, name, value in [
            (classifier, 'ROOT', root), (file_manager, 'ROOT', root), (interface, 'ROOT', root),
            (file_manager, 'PROJECT', base), (file_manager, 'HISTORY_DB', base / 'history.db'),
            (cache, 'PROJECT', base), (cache, 'DB_PATH', base / 'cache.db'),
        ]]
        for item in patches:
            item.start()
        window = None
        try:
            with patch.object(interface.messagebox, 'showinfo') as info, \
                 patch.object(interface.messagebox, 'showwarning') as warning, \
                 patch.object(interface.messagebox, 'showerror') as error, \
                 patch.object(interface.messagebox, 'askyesno', return_value=True), \
                 patch.object(interface.simpledialog, 'askstring', return_value='YES'):
                window = tk.Tk()
                window.withdraw()
                app = interface.OrganizerApp(window)
                app.scan_btn.invoke()
                assert len(app.files) == 1 and app.proposals[0]['method'] == 'Needs AI'
                print('Scan: ambiguous test document found', flush=True)
                app.ai_btn.invoke()
                deadline = time.monotonic() + 240
                while app.busy and time.monotonic() < deadline:
                    window.update()
                    time.sleep(.05)
                assert not app.busy, 'Ollama analysis timed out'
                assert not warning.called, f'Analysis warning: {warning.call_args_list}'
                assert app.proposals[0]['issue'] is None, app.proposals[0]
                print('Ollama: real analysis produced a ready proposal', flush=True)
                app.preview_btn.invoke()
                assert info.called and (root / 'document.txt').exists()
                destination = app.proposals[0]['dst']
                app.tree.selection_set('file:0')
                app.apply_btn.invoke()
                assert not error.called, error.call_args_list
                assert destination.is_file() and not (root / 'document.txt').exists(), info.call_args_list
                print('Preview and approved move: real file moved', flush=True)
                window.destroy()
                window = None
                subprocess.run([sys.executable, '-B', __file__, '--undo', str(base)], check=True)
                assert (root / 'document.txt').read_text(encoding='utf-8').startswith('This document')
                assert not destination.exists()
                print('New process and Undo: original restored', flush=True)
        finally:
            if window is not None:
                window.destroy()
            for item in reversed(patches):
                item.stop()


def undo_in_new_process(base):
    base = Path(base).resolve()
    root = base / 'files'
    with patch.object(classifier, 'ROOT', root), patch.object(file_manager, 'ROOT', root), \
         patch.object(interface, 'ROOT', root), patch.object(cache, 'PROJECT', base), \
         patch.object(cache, 'DB_PATH', base / 'cache.db'), \
         patch.object(file_manager, 'PROJECT', base), \
         patch.object(file_manager, 'HISTORY_DB', base / 'history.db'), \
         patch.object(interface.messagebox, 'askyesno', return_value=True), \
         patch.object(interface.messagebox, 'showinfo'), \
         patch.object(interface.messagebox, 'showerror') as error:
        window = tk.Tk()
        window.withdraw()
        try:
            interface.OrganizerApp(window).undo_btn.invoke()
            assert not error.called, error.call_args_list
        finally:
            window.destroy()


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--undo':
        undo_in_new_process(sys.argv[2])
    else:
        run()
