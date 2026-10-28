from __future__ import annotations
import threading
import tkinter as tk
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox, simpledialog, ttk
from .config import *
from .classifier import scan, scan_readonly, analyze_files, analysis_error_message
from .cache import cached_result, content_cache_write
from .database_migration import migrate_legacy_databases
from .file_manager import history_init, history_pending, build_proposals, build_readonly_proposals, valid_filename, apply_proposals, undo_preview, undo_last_batch

class OrganizerApp:
    def __init__(self, window):
        self.root = window
        window.title('Downloads Organizer')
        window.geometry('1250x780')
        window.minsize(950, 600)
        window.configure(background='#103b37')
        style = ttk.Style(window)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10), background='#ffffff', foreground='#173b37')
        style.configure('Title.TLabel', font=('Segoe UI', 23, 'bold'), foreground='#143a35')
        style.configure('Eyebrow.TLabel', font=('Segoe UI', 9, 'bold'), foreground='#628077')
        style.configure('Subtitle.TLabel', foreground='#748982')
        style.configure('Section.TLabel', font=('Segoe UI', 12, 'bold'), foreground='#173b37')
        style.configure('Card.TFrame', background='#f1f6f4')
        style.configure('Card.TLabel', background='#f1f6f4', foreground='#526f68')
        style.configure('CardTitle.TLabel', background='#f1f6f4', foreground='#173b37',
                        font=('Segoe UI', 10, 'bold'))
        style.configure('TButton', padding=(15, 9), background='#eef4f1', foreground='#173b37',
                        borderwidth=0, focusthickness=1)
        style.map('TButton', background=[('disabled', '#f4f7f5'), ('active', '#dceae3')],
                  foreground=[('disabled', '#a4b4ad')])
        style.configure('Primary.TButton', background='#103d37', foreground='white', padding=(17, 9), borderwidth=0)
        style.map('Primary.TButton', background=[('disabled', '#bbcfc6'), ('active', '#245b50')],
                  foreground=[('disabled', '#f5f8f6')])
        style.configure('TCombobox', padding=6, fieldbackground='white', background='#e9f0ed',
                        foreground='#173b37', borderwidth=0)
        style.configure('Treeview', rowheight=40, background='#f6f9f7', fieldbackground='#f6f9f7',
                        foreground='#24433d', borderwidth=0)
        style.configure('Treeview.Heading', font=('Segoe UI', 9, 'bold'), padding=(10, 10),
                        background='#e9f1ed', foreground='#58746b', borderwidth=0)
        style.map('Treeview', background=[('selected', '#cde5d9')],
                  foreground=[('selected', '#123a32')])
        self.files = []
        self.proposals = []
        self.selected_root = validate_test_folder(ROOT)
        self.read_only = False
        self.scan_warnings = []
        self.edited_names = {}
        self.preview_root = None
        self.queue = Queue()
        self.busy = False
        self.mode = tk.StringVar(value='Organize only')
        history_init()

        main = ttk.Frame(window, padding=(34, 27, 34, 18))
        main.pack(fill='both', expand=True, padx=12, pady=12)
        ttk.Label(main, text='YOUR WORKSPACE  /  LOCAL ORGANIZER', style='Eyebrow.TLabel').pack(anchor='w')
        ttk.Label(main, text='Downloads, in order.', style='Title.TLabel').pack(anchor='w', pady=(6, 0))
        ttk.Label(main, text='Review suggestions and decide what happens to your files.',
                  style='Subtitle.TLabel').pack(anchor='w', pady=(2, 18))
        location = ttk.Frame(main, style='Card.TFrame', padding=(18, 13))
        location.pack(fill='x', pady=(0, 18))
        location_info = ttk.Frame(location, style='Card.TFrame')
        location_info.pack(side='left', fill='x', expand=True)
        ttk.Label(location_info, text='SELECTED FOLDER', style='CardTitle.TLabel').pack(anchor='w')
        self.folder_label = tk.StringVar(value=f'Test folder  ·  {self.selected_root}')
        ttk.Label(location_info, textvariable=self.folder_label, style='Card.TLabel').pack(anchor='w', pady=(3, 0))
        self.folder_btn = ttk.Button(location, text='Choose folder', command=self.choose_folder)
        self.folder_btn.pack(side='right')
        buttons = ttk.Frame(main)
        buttons.pack(fill='x', pady=(0, 22))
        self.scan_btn = ttk.Button(buttons, text='1  Scan', command=self.refresh, style='Primary.TButton')
        self.scan_btn.pack(side='left', padx=(0, 8))
        self.ai_btn = ttk.Button(buttons, text='2  Analyze with Ollama', command=self.analyze)
        self.ai_btn.pack(side='left', padx=(0, 8))
        ttk.Label(buttons, text='Action').pack(side='left', padx=(12, 6))
        self.mode_box = ttk.Combobox(buttons, textvariable=self.mode, values=MODES,
                                     state='readonly', width=21)
        self.mode_box.bind('<<ComboboxSelected>>', lambda event: self.prepare())
        self.preview_btn = ttk.Button(buttons, text='3  Preview', command=self.show_preview)
        self.preview_btn.pack(side='left')

        table_header = ttk.Frame(main)
        table_header.pack(fill='x')
        ttk.Label(table_header, text='Your files', style='Section.TLabel').pack(side='left')
        ttk.Label(table_header, text='Select ready files to organize', style='Subtitle.TLabel').pack(side='right')

        # Parent the Treeview to the same container in which it is packed.
        # Packing a widget into a different parent can leave an empty area on Windows.
        frame = ttk.Frame(main)
        self.tree = ttk.Treeview(frame, columns=('source', 'category', 'destination', 'method', 'copies', 'status'),
                                 show='headings', selectmode='extended', height=15)
        specs = [('source', 'Name', 210), ('category', 'Category', 110),
                 ('destination', 'Proposed destination', 300), ('method', 'Classification source', 145),
                 ('copies', 'Copies', 60), ('status', 'Status', 260)]
        for key, label, width in specs:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=65)
        self.tree.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(frame, orient='vertical', command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(frame, orient='horizontal', command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal.set)
        self.tree.tag_configure('blocked', foreground='#86623b')

        actions = ttk.Frame(main)
        self.apply_btn = ttk.Button(actions, text='4  Apply selected', command=self.confirm_apply,
                                    style='Primary.TButton')
        self.apply_btn.pack(side='left', padx=(0, 8))
        self.undo_btn = ttk.Button(actions, text='Undo last batch', command=self.confirm_undo)
        self.undo_btn.pack(side='left', padx=(0, 8))
        self.edit_btn = ttk.Button(actions, text='Edit suggested name', command=self.edit_name)
        self.status = tk.StringVar(value='Ready. Scan files to begin.')
        ttk.Label(main, textvariable=self.status, padding=(0, 12, 0, 0),
                  style='Subtitle.TLabel').pack(fill='x', side='bottom')
        actions.pack(fill='x', side='bottom', pady=(0, 4))
        frame.pack(fill='both', expand=True, pady=(8, 14))
        window.after(150, self.poll)

    def set_busy(self, busy):
        self.busy = busy
        for button in (self.folder_btn, self.scan_btn, self.ai_btn, self.preview_btn, self.apply_btn, self.undo_btn, self.edit_btn):
            button.state(['disabled'] if busy else ['!disabled'])
        if self.read_only:
            for button in (self.ai_btn, self.apply_btn, self.undo_btn, self.edit_btn):
                button.state(['disabled'])
        self.mode_box.configure(state='disabled' if busy else 'readonly')

    def choose_folder(self):
        if self.busy:
            return
        folder = filedialog.askdirectory(parent=self.root, initialdir=str(self.selected_root),
                                         title='Choose a folder to preview')
        if not folder:
            return
        try:
            selected = validate_test_folder(Path(folder))
            read_only = False
        except (OSError, ValueError):
            try:
                selected = validate_preview_folder(Path(folder))
                read_only = True
            except (OSError, ValueError) as exc:
                messagebox.showerror('Folder unavailable', str(exc))
                return
        if selected == self.selected_root:
            return
        answer = simpledialog.askstring(
            'Confirm folder change',
            f'Change the selected folder?\n\nCurrent: {self.selected_root}\n'
            f'New: {selected}\n'
            + ('\nREAD-ONLY: files can be scanned and previewed, but not analyzed, moved or renamed.\n' if read_only else '')
            + '\nThe current scan and preview will be cleared. '
            'Type YES to continue:',
            parent=self.root)
        if answer != 'YES':
            return
        self.selected_root = selected
        self.read_only = read_only
        self.set_busy(False)
        self.folder_label.set(f'{"READ-ONLY" if read_only else "Test folder"}  ·  {selected}')
        self.files = []
        self.proposals = []
        self.edited_names = {}
        self.preview_root = None
        self.tree.delete(*self.tree.get_children())
        self.status.set('Folder selected. Scan files to begin.')

    def refresh(self):
        if self.busy:
            return
        try:
            if self.read_only:
                self.files, self.scan_warnings = scan_readonly(self.selected_root)
            else:
                self.files = scan(self.selected_root)
                self.scan_warnings = []
            self.edited_names = {}
            self.prepare()
            if self.scan_warnings:
                messagebox.showwarning('Some files could not be scanned', '\n'.join(self.scan_warnings[:10]))
        except Exception as exc:
            self.files = []
            self.proposals = []
            self.preview_root = None
            self.tree.delete(*self.tree.get_children())
            messagebox.showerror('Scan failed', str(exc))

    def prepare(self):
        if self.busy:
            return
        try:
            self.preview_root = None
            self.proposals = (build_readonly_proposals(self.files, self.mode.get(), self.selected_root)
                              if self.read_only else build_proposals(self.files, self.mode.get(), self.selected_root, self.edited_names))
        except Exception as exc:
            messagebox.showerror('Preview failed', str(exc))
            return False
        self.tree.delete(*self.tree.get_children())
        ready = 0
        for i, p in enumerate(self.proposals):
            state = p['issue'] or 'Ready'
            ready += (state == 'Ready')
            self.tree.insert('', 'end', iid=f'file:{i}', values=(
                p['original'], p['category'] or 'Needs AI',
                str(p['dst'].relative_to(self.selected_root)), p['method'],
                p['duplicate_count'] if p['duplicate_count'] > 1 else '—', state),
                tags=('blocked',) if p['issue'] else ())
        if self.read_only:
            self.status.set(f'READ-ONLY · {len(self.files)} files scanned · filename rules only · no files can be changed')
        else:
            self.status.set(f'{len(self.files)} files scanned · {ready} ready · '
                            f'{len(self.files)-ready} skipped or needing AI · select rows to approve')
        return True

    def show_preview(self):
        """Refresh the plan and show an explicit read-only summary."""
        if self.busy:
            return
        if not self.files:
            messagebox.showinfo('Preview', 'Scan files first, then click Preview.')
            return
        if not self.prepare():
            return
        ready = [p for p in self.proposals if not p['issue'] or
                 (self.read_only and p['issue'] == 'Read-only preview')]
        blocked = [p for p in self.proposals if p not in ready]
        examples = [
            f"{p['original']}  →  {p['dst'].relative_to(self.selected_root)}"
            for p in ready[:10]
        ]
        message = (
            f"Folder: {self.selected_root}\n"
            f"Mode: {self.mode.get()}\n"
            f"Files scanned: {len(self.files)}\n"
            f"{'Rule-based possibilities' if self.read_only else 'Ready for approval'}: {len(ready)}\n"
            f"Skipped or needing review: {len(blocked)}\n\n"
            "Proposed changes (first 10):\n"
            + ('\n'.join(examples) if examples else 'No changes ready.')
            + (f"\n...and {len(ready) - 10} more" if len(ready) > 10 else '')
            + ("\n\nREAD-ONLY preview: no files can be changed here. Analysis uses filenames only."
               if self.read_only else "\n\nNothing has been moved. Select Ready rows in the table, "
               "then click Apply selected moves to approve them.")
        )
        messagebox.showinfo('Preview — no files changed', message, parent=self.root)
        self.preview_root = self.selected_root

    def analyze(self):
        if self.busy or self.read_only:
            return
        unresolved = [f for f in self.files if not f['rule_category'] and cached_result(f)[0] is None]
        if not unresolved:
            self.status.set('No unresolved files need AI. Scan again after adding files.')
            return
        self.set_busy(True)
        self.status.set(f'Analyzing {len(unresolved)} files...')

        def worker():
            errors = []
            completed = 0
            unique = {}
            for f in unresolved:
                unique.setdefault((f['sha256'], f['extension']), f)
            reps = list(unique.values())
            for start in range(0, len(reps), 10):
                batch = reps[start:start + 10]
                try:
                    results = analyze_files(batch, warnings=errors)
                    for f in batch:
                        result = results.get(f['filename'])
                        if not result:
                            errors.append(f"{f['filename']}: Ollama returned no valid result. Try analyzing it again.")
                        else:
                            try:
                                saved = content_cache_write(f, result)
                            except Exception as exc:
                                errors.append(f"{f['filename']}: could not save the result to the cache ({exc}). "
                                              'Check database access and try again.')
                            else:
                                if saved:
                                    completed += 1
                                else:
                                    errors.append(f"{f['filename']}: the file changed during analysis; scan and try again.")
                except Exception as exc:
                    errors.append(analysis_error_message(exc))
            self.queue.put(('ai', completed, len(unresolved) - len(reps), errors))
        threading.Thread(target=worker, daemon=True).start()

    def edit_name(self):
        if self.busy or self.read_only:
            return
        selection = self.tree.selection()
        if len(selection) != 1:
            messagebox.showinfo('Select a file', 'Select one file to edit its suggested name.')
            return
        if self.mode.get() == 'Organize only':
            messagebox.showinfo('Rename mode required', 'Choose Rename only or Rename + Organize first.')
            return
        index = int(selection[0].removeprefix('file:'))
        proposal = self.proposals[index]
        name = simpledialog.askstring('Edit suggested name', 'Enter a filename with the original extension:',
                                      initialvalue=proposal['suggested'], parent=self.root)
        if name is None:
            return
        if not valid_filename(name, proposal['original']):
            messagebox.showwarning('Invalid filename', 'Use a valid Windows filename and keep the original extension.')
            return
        self.edited_names[proposal['original']] = name
        if self.prepare():
            self.tree.selection_set(f'file:{index}')
            self.status.set(self.status.get() + ' · preview again before applying')


    def confirm_apply(self):
        if self.busy or self.read_only:
            return
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo('Selection required', 'Select one or more rows first.')
            return
        if self.preview_root != self.selected_root:
            messagebox.showinfo('Preview required', 'Click Preview and review the proposed changes first.')
            return
        choices = [self.proposals[int(i.removeprefix('file:'))] for i in selected]
        invalid = [p for p in choices if p['issue']]
        if invalid:
            messagebox.showwarning('Unsafe selection', 'Some selected rows are not ready. Select only Ready rows.')
            return
        if not messagebox.askyesno('Review approved moves',
              f'Folder: {self.selected_root}\n\nMove these files?\n\n' + '\n'.join(
                  f"{p['original']}  →  {p['dst'].relative_to(self.selected_root)}" for p in choices[:15]) +
                  (f'\n... and {len(choices)-15} more' if len(choices) > 15 else '')):
            return
        word = simpledialog.askstring('Confirm operations', 'Type YES to perform these test-file moves:', parent=self.root)
        if word != 'YES':
            self.status.set('Cancelled. No actions taken.')
            return
        try:
            outcomes = apply_proposals(choices, self.selected_root)
            self.refresh()
            self.show_operation_results('Move results', outcomes)
        except Exception as exc:
            messagebox.showerror('Move blocked', self.operation_error(exc))

    def confirm_undo(self):
        if self.busy or self.read_only:
            return
        try:
            batch, entries = undo_preview(self.selected_root)
        except Exception as exc:
            messagebox.showerror('Undo blocked', self.operation_error(exc))
            return
        if not batch:
            messagebox.showinfo('Undo last batch', 'No completed batch to undo for this folder.')
            return
        paths = '\n'.join(f'{destination}  →  {source}' for _, source, destination, _ in entries[:15])
        if len(entries) > 15:
            paths += f'\n... and {len(entries) - 15} more'
        if not messagebox.askyesno('Undo last batch', f'Folder: {self.selected_root}\n\nRestore these files?\n\n{paths}'):
            return
        try:
            outcomes = undo_last_batch(self.selected_root, expected_batch=batch)
            self.refresh()
            self.show_operation_results('Undo results', outcomes)
        except Exception as exc:
            messagebox.showerror('Undo blocked', self.operation_error(exc))

    def operation_error(self, exc):
        """Include recorded paths so an interrupted operation can be inspected."""
        try:
            pending = history_pending()
        except Exception:
            pending = []
        if not pending:
            return str(exc)
        details = '\n\n'.join(f'Source: {source}\nDestination: {destination}\n{note}'
                              for _, source, destination, note in pending[:5])
        return (f'{exc}\n\nAn operation was interrupted. Inspect both paths and the history before '
                f'continuing; do not delete either file until you understand what happened.\n\n{details}')

    def show_operation_results(self, title, outcomes):
        summary = '\n'.join(f'{name}: {status}' for name, status in outcomes)[:3500]
        if any(status.startswith('CHECK MANUALLY') for _, status in outcomes):
            messagebox.showwarning(title, self.operation_error(summary))
        else:
            messagebox.showinfo(title, summary)

    def poll(self):
        try:
            kind, completed, reused, errors = self.queue.get_nowait()
        except Empty:
            pass
        else:
            self.set_busy(False)
            self.refresh()
            self.status.set(self.status.get() + f' · {completed} new analyses · {reused} duplicates grouped')
            if errors:
                messagebox.showwarning('Analysis needs attention', '\n\n'.join(errors[:10]) +
                                       (f'\n\n...and {len(errors) - 10} more.' if len(errors) > 10 else ''))
        self.root.after(150, self.poll)


def main():
    window = tk.Tk()
    try:
        migrate_legacy_databases()
    except Exception as exc:
        messagebox.showerror('Database setup failed',
                             f'Existing databases were preserved. Could not prepare the new database names: {exc}')
        window.destroy()
        return
    OrganizerApp(window)
    window.mainloop()

