"""PySide6 interface for the existing organizer services."""
from __future__ import annotations

from pathlib import Path
import sys
import threading

from PySide6.QtCore import QObject, Qt, Signal, QTimer, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFrame,
    QHeaderView, QHBoxLayout, QInputDialog, QLabel, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .config import ROOT, MODES, validate_test_folder, validate_preview_folder
from .classifier import scan, scan_readonly, analyze_files
from .cache import cached_result, content_cache_write
from .database_migration import migrate_legacy_databases
from . import categories as category_store
from . import providers
from .ai_settings import AIConfig
from .ai_setup_dialog import AISetupDialog, startup_config
from .file_manager import (history_init, history_pending, build_proposals,
                           build_readonly_proposals, valid_filename,
                           apply_proposals, undo_preview, undo_last_batch)

STYLE = """
QMainWindow { background: #103b37; }
QWidget#shell { background: #103b37; }
QWidget { font-family: 'Segoe UI'; font-size: 10pt; color: #183d37; }
QFrame#surface { background: #ffffff; border-radius: 18px; }
QFrame#folderCard { background: #f0f6f3; border-radius: 14px; }
QLabel#eyebrow { color: #486a60; font-size: 9pt; font-weight: 700; letter-spacing: 1px; }
QLabel#title { color: #143a35; font-size: 22pt; font-weight: 700; }
QLabel#subtitle, QLabel#status { color: #506e64; }
QLabel#section { font-size: 13pt; font-weight: 700; }
QLabel#cardLabel { color: #527168; font-size: 9pt; font-weight: 700; }
QLabel#path { color: #244d44; }
QPushButton { background: #eef4f1; border: none; border-radius: 9px; padding: 10px 16px; font-weight: 600; }
QPushButton:hover { background: #dfebe5; }
QPushButton:disabled { background: #f3f6f4; color: #a5b5ad; }
QPushButton#primary { background: #113e37; color: white; }
QPushButton#primary:hover { background: #286155; }
QPushButton#primary:disabled { background: #b8cbc2; color: #eff5f1; }
QComboBox { background: #f3f7f5; border: 1px solid #dbe7e0; border-radius: 8px; padding: 9px 12px; min-width: 170px; }
QTableWidget { background: #ffffff; color: #173b37; border: 1px solid #d8e6de; border-radius: 12px; gridline-color: #e9f0ec; selection-background-color: #c9e4d5; selection-color: #102f29; }
QHeaderView::section { background: #edf4f0; color: #365c50; border: none; padding: 11px 8px; font-weight: 600; }
QTableWidget::item { padding: 6px; border-bottom: 1px solid #edf2ef; color: #173b37; }
QTableWidget::item:selected { background: #c9e4d5; color: #102f29; }
QProgressBar { background: #e6f0ea; border: none; border-radius: 4px; height: 8px; }
QProgressBar::chunk { background: #23745e; border-radius: 4px; }
QLabel#step { background: #f1f5f3; color: #60766c; border-radius: 8px; padding: 9px 14px; }
QLabel#step[active="true"] { background: #dceee3; color: #173b37; font-weight: 700; }
QLabel#modeBadge { background: #e5eee9; color: #305d4d; border-radius: 7px; padding: 5px 10px; font-size: 9pt; font-weight: 600; }
QLabel#empty { color: #506e64; background: #f4f8f5; border-radius: 9px; padding: 18px; }
QPushButton#quiet { background: transparent; color: #365c50; padding: 8px 10px; }
QPushButton#quiet:hover { background: #e8f0eb; }
QPushButton#quiet:disabled { color: #9caaa3; }
QFrame#footer { border-top: 1px solid #dfebe4; }
"""


class Spinner(QWidget):
    """A rotating dot indicates work without implying a known duration."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(22, 22)
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)

    def tick(self):
        self.angle = (self.angle + 30) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor('#d1e7dc'), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(3, 3, 16, 16))
        painter.translate(11, 11)
        painter.rotate(self.angle)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#1e765d'))
        painter.drawEllipse(QRectF(5, -3, 6, 6))


def classification_counts(proposals):
    counts = {'Python rules': 0, 'AI / cached AI': 0, 'Unresolved': 0}
    for p in proposals:
        method = p.get('method')
        if method == 'Python rules':
            counts['Python rules'] += 1
        elif method in ('Content cache', 'Path cache'):
            counts['AI / cached AI'] += 1
        else:
            counts['Unresolved'] += 1
    return counts


class ClassificationChart(QWidget):
    COLORS = ('#24745d', '#83b5a0', '#dfb967')

    def __init__(self, counts, parent=None):
        super().__init__(parent)
        self.counts = counts
        self.setFixedSize(200, 200)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        total = sum(self.counts.values())
        rect = QRectF(18, 18, 164, 164)
        painter.setPen(QPen(QColor('#eaf2ee'), 22))
        painter.drawEllipse(rect)
        if total:
            start = 90 * 16
            for count, color in zip(self.counts.values(), self.COLORS):
                span = round(360 * 16 * count / total)
                if span:
                    painter.setPen(QPen(QColor(color), 22))
                    painter.drawArc(rect, start, -span)
                    start -= span
        painter.setPen(QColor('#173b37'))
        font = painter.font()
        font.setPointSize(21)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), str(total))


class ClassificationSummary(QDialog):
    def __init__(self, counts, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Classification complete')
        self.setMinimumWidth(490)
        self.setStyleSheet('QDialog { background: white; } QLabel { color: #183d37; font-family: Segoe UI; font-size: 10pt; }')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        title = QLabel('Classification complete')
        title.setStyleSheet('font-size: 17pt; font-weight: 700;')
        layout.addWidget(title)
        layout.addWidget(QLabel('How the files were classified'))
        content = QHBoxLayout()
        content.addWidget(ClassificationChart(counts))
        legend = QVBoxLayout()
        legend.addStretch()
        for (label, count), color in zip(counts.items(), ClassificationChart.COLORS):
            row = QLabel(f'●  {label}:  {count}')
            row.setStyleSheet('color: #183d37; font-weight: 600;')
            legend.addWidget(row)
        legend.addStretch()
        content.addLayout(legend)
        layout.addLayout(content)
        note = QLabel('AI includes previously cached AI classifications. Unresolved files still need attention.')
        note.setWordWrap(True)
        note.setStyleSheet('color: #728980; font-size: 9pt;')
        layout.addWidget(note)
        button = QPushButton('Done')
        button.setStyleSheet('QPushButton { background: #113e37; color: white; border: 0; '
                             'border-radius: 8px; padding: 9px 20px; font-weight: 600; } '
                             'QPushButton:hover { background: #286155; }')
        button.clicked.connect(self.accept)
        layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignRight)


class AnalysisSignals(QObject):
    finished = Signal(int, int, list)


class ApprovalDialog(QDialog):
    """Scrollable dry run of every checked file before explicit approval."""
    def __init__(self, root, proposals, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Review selected changes')
        self.resize(850, 500)
        layout = QVBoxLayout(self)
        title = QLabel(f'Review {len(proposals)} proposed changes')
        title.setStyleSheet('font-size: 14pt; font-weight: 700;')
        layout.addWidget(title)
        path = QLabel(f'Folder: {root}\nNo files have been moved. Review the list, then continue to confirmation.')
        path.setWordWrap(True)
        layout.addWidget(path)
        table = QTableWidget(len(proposals), 2)
        table.setHorizontalHeaderLabels(['Current file', 'Proposed destination'])
        table.verticalHeader().hide()
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row, proposal in enumerate(proposals):
            table.setItem(row, 0, QTableWidgetItem(proposal['original']))
            table.setItem(row, 1, QTableWidgetItem(str(proposal['dst'].relative_to(root))))
        layout.addWidget(table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Continue')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class OrganizerWindow(QMainWindow):
    def __init__(self, root=None, ai_config=None):
        super().__init__()
        self.selected_root = validate_test_folder(ROOT if root is None else root)
        self.files, self.proposals, self.edited_names = [], [], {}
        self.read_only = False
        self.classified = False
        self.categories = None
        self.ai_config = AIConfig() if ai_config is None else ai_config
        self.busy = False
        self.has_undo = False
        self._compact = None
        self._loading_table = False
        self.signals = AnalysisSignals(self)
        self.signals.finished.connect(self.analysis_finished)
        history_init()
        self.setWindowTitle('Downloads Organizer')
        self.resize(1280, 800)
        self.setMinimumSize(980, 620)
        self.setStyleSheet(STYLE)
        self._build_ui()
        self.categories = category_store.load(self.selected_root)
        self.refresh()

    def _label(self, text, name=None):
        label = QLabel(text)
        if name:
            label.setObjectName(name)
        return label

    def _button(self, text, callback, primary=False):
        button = QPushButton(text)
        if primary:
            button.setObjectName('primary')
        button.clicked.connect(callback)
        return button

    def _build_ui(self):
        shell = QWidget()
        shell.setObjectName('shell')
        self.setCentralWidget(shell)
        outer = QVBoxLayout(shell)
        outer.setContentsMargins(12, 12, 12, 12)
        surface = QFrame()
        surface.setObjectName('surface')
        outer.addWidget(surface)
        main = QVBoxLayout(surface)
        self.main_layout = main
        main.setContentsMargins(30, 24, 30, 22)
        main.setSpacing(12)
        header = QHBoxLayout()
        header.addWidget(self._label('Downloads Organizer', 'title'))
        header.addStretch()
        self.provider_label = self._label(self.ai_config.label, 'subtitle')
        self.provider_label.setWordWrap(True)
        self.provider_label.setMaximumWidth(300)
        header.addWidget(self.provider_label)
        self.ai_settings_btn = self._button('AI settings', self.edit_ai_settings)
        self.ai_settings_btn.setObjectName('quiet')
        header.addWidget(self.ai_settings_btn)
        main.addLayout(header)
        self.intro_label = self._label('Choose a folder. Classify its files. Review and organize.', 'subtitle')
        main.addWidget(self.intro_label)

        steps = QHBoxLayout()
        steps.setSpacing(8)
        self.step_labels = []
        for text in ('1  Your folder', '2  Classify files', '3  Review & organize'):
            label = self._label(text, 'step')
            self.step_labels.append(label)
            steps.addWidget(label, 1)
        main.addLayout(steps)

        card = QFrame()
        card.setObjectName('folderCard')
        card_layout = QVBoxLayout(card)
        self.folder_card_layout = card_layout
        card_layout.setContentsMargins(20, 15, 20, 15)
        folder_row = QHBoxLayout()
        details = QVBoxLayout()
        details.setSpacing(5)
        folder_heading = QHBoxLayout()
        folder_heading.addWidget(self._label('CURRENT FOLDER', 'cardLabel'))
        self.mode_badge = self._label('Test folder', 'modeBadge')
        folder_heading.addWidget(self.mode_badge)
        folder_heading.addStretch()
        details.addLayout(folder_heading)
        self.folder_label = self._label('', 'path')
        self.folder_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.folder_label.setWordWrap(True)
        details.addWidget(self.folder_label)
        folder_row.addLayout(details, 1)
        self.folder_btn = self._button('Change folder', self.choose_folder)
        folder_row.addWidget(self.folder_btn)
        self.scan_btn = self._button('Refresh', self.refresh)
        self.scan_btn.setObjectName('quiet')
        self.scan_btn.setToolTip('Read the folder again and clear the current suggestions.')
        folder_row.addWidget(self.scan_btn)
        card_layout.addLayout(folder_row)

        category_row = QHBoxLayout()
        self.category_summary = self._label('', 'subtitle')
        self.category_summary.setWordWrap(True)
        category_row.addWidget(self.category_summary, 1)
        self.category_btn = self._button('Edit categories', self.edit_categories)
        self.category_btn.setObjectName('quiet')
        self.category_btn.setToolTip('Categories are saved for this folder. Changing them requires classification again.')
        category_row.addWidget(self.category_btn)
        card_layout.addLayout(category_row)
        main.addWidget(card)
        self._update_folder_label()

        self.progress_row = QWidget()
        progress_layout = QHBoxLayout(self.progress_row)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        self.spinner = Spinner()
        progress_layout.addWidget(self.spinner)
        self.progress_label = self._label('Classification in progress…', 'subtitle')
        progress_layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        progress_layout.addWidget(self.progress_bar, 1)
        main.addWidget(self.progress_row)
        self.progress_row.hide()

        heading = QHBoxLayout()
        self.table_title = self._label('Files in this folder', 'section')
        heading.addWidget(self.table_title)
        self.table_summary = self._label('', 'subtitle')
        heading.addWidget(self.table_summary)
        heading.addStretch()
        self.reclassify_btn = self._button('Classify again', self.analyze)
        self.reclassify_btn.setObjectName('quiet')
        heading.addWidget(self.reclassify_btn)
        self.edit_btn = self._button('Edit suggested name', self.edit_name)
        self.edit_btn.setObjectName('quiet')
        self.edit_btn.setToolTip('Click one file row to edit its suggested name. Checkboxes control which files will be organized.')
        heading.addWidget(self.edit_btn)
        main.addLayout(heading)

        self.selection_bar = QWidget()
        selection_layout = QHBoxLayout(self.selection_bar)
        selection_layout.setContentsMargins(0, 0, 0, 0)
        self.select_all = QCheckBox('Select all ready files')
        self.select_all.setTristate(True)
        self.select_all.stateChanged.connect(self.toggle_all)
        selection_layout.addWidget(self.select_all)
        self.selection_hint = self._label('Ready files are checked automatically. Uncheck any you want to keep.', 'subtitle')
        selection_layout.addWidget(self.selection_hint)
        selection_layout.addStretch()
        self.details_toggle = QCheckBox('Show details')
        self.details_toggle.setToolTip('Show full destinations, classification source and duplicate counts.')
        self.details_toggle.toggled.connect(lambda _: self.update_workflow())
        selection_layout.addWidget(self.details_toggle)
        main.addWidget(self.selection_bar)
        self.empty_label = self._label('This folder is empty. Add files here, then click Refresh.', 'empty')
        self.empty_label.setWordWrap(True)
        main.addWidget(self.empty_label)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(['Include', 'Current name', 'Proposed name', 'Category', 'Proposed destination', 'Classified by', 'Copies', 'Status'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(42)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        for index, width in enumerate((70, 170, 180, 110, 240, 110, 60, 190)):
            self.table.setColumnWidth(index, width)
        self.table.itemChanged.connect(self.selection_changed)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self.update_workflow())
        main.addWidget(self.table, 1)

        footer = QFrame()
        footer.setObjectName('footer')
        actions = QHBoxLayout(footer)
        actions.setContentsMargins(0, 14, 0, 0)
        self.undo_btn = self._button('Undo last batch', self.confirm_undo)
        self.undo_btn.setObjectName('quiet')
        self.undo_btn.setToolTip('Restore the last recorded batch in this folder.')
        actions.addWidget(self.undo_btn)
        actions.addStretch()
        self.mode_label = self._label('When organizing', 'subtitle')
        actions.addWidget(self.mode_label)
        self.mode_box = QComboBox()
        self.mode_box.addItems(MODES)
        self.mode_box.currentIndexChanged.connect(lambda _: self.prepare(preserve_checks=True))
        actions.addWidget(self.mode_box)
        self.ai_btn = self._button('Classify files', self.analyze, True)
        actions.addWidget(self.ai_btn)
        self.apply_btn = self._button('Review & organize', self.confirm_apply, True)
        actions.addWidget(self.apply_btn)
        main.addWidget(footer)
        self.next_hint = self._label('', 'subtitle')
        self.next_hint.setWordWrap(True)
        main.addWidget(self.next_hint)
        self.status = self._label('Ready. Scan files to begin.', 'status')
        self.status.setWordWrap(True)
        main.addWidget(self.status)

    def _update_folder_label(self):
        self.folder_label.setText(str(self.selected_root))
        self.mode_badge.setText('Read-only preview' if self.read_only else 'Test folder')

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, 'next_hint'):
            return
        compact = self.height() < 720
        if compact == self._compact:
            return
        self._compact = compact
        self.intro_label.setVisible(not compact)
        self.next_hint.setVisible(not compact)
        for label in self.step_labels:
            label.setVisible(not compact)
        self.main_layout.setSpacing(8 if compact else 12)
        if compact:
            self.main_layout.setContentsMargins(24, 18, 24, 18)
            self.folder_card_layout.setContentsMargins(16, 10, 16, 10)
        else:
            self.main_layout.setContentsMargins(30, 24, 30, 22)
            self.folder_card_layout.setContentsMargins(20, 15, 20, 15)

    def update_workflow(self):
        """Keep the available actions aligned with the current user step."""
        if self._loading_table or not hasattr(self, 'apply_btn'):
            return
        writable = not self.read_only
        idle = not self.busy
        checked = len(self.selected_rows())
        ready = sum(not p['issue'] for p in self.proposals)
        reviewing = self.classified and idle

        for control in (self.folder_btn, self.scan_btn, self.ai_settings_btn, self.table):
            control.setEnabled(idle)
        self.category_btn.setEnabled(idle and writable)
        self.undo_btn.setEnabled(idle and writable and self.has_undo)
        self.reclassify_btn.setVisible(reviewing and writable and bool(self.files))
        self.reclassify_btn.setEnabled(idle and writable)
        self.ai_btn.setVisible(writable and (not self.classified or self.busy))
        self.ai_btn.setEnabled(idle and writable and bool(self.files))
        file_count = len(self.files)
        self.ai_btn.setText('Classifying…' if self.busy else f'Classify {file_count} {"file" if file_count == 1 else "files"}')
        self.apply_btn.setVisible(reviewing and writable)
        self.apply_btn.setEnabled(idle and writable and checked > 0)
        self.apply_btn.setText(f'Review & organize {checked} {"file" if checked == 1 else "files"}')
        self.mode_label.setVisible(reviewing and writable)
        self.mode_box.setVisible(reviewing and writable)
        self.mode_box.setEnabled(reviewing and writable)
        self.selection_bar.setVisible(reviewing and bool(self.proposals))
        self.select_all.setVisible(writable)
        self.selection_hint.setVisible(writable)
        self.select_all.setEnabled(idle and writable and ready > 0)
        self.details_toggle.setEnabled(idle)
        self.edit_btn.setVisible(reviewing and writable and bool(self.files))
        focused = self.table.selectionModel().selectedRows()
        self.edit_btn.setEnabled(reviewing and writable and len(focused) == 1
                                 and self.mode_box.currentText() != 'Organize only')

        self.table_title.setText('Review suggestions' if self.classified else 'Files in this folder')
        if self.busy:
            self.table_summary.setText('Classification in progress')
        elif self.classified and writable:
            self.table_summary.setText(f'{checked} checked  ·  {ready} ready  ·  {len(self.proposals)-ready} need attention')
        else:
            self.table_summary.setText(f'{len(self.files)} files')
        self.empty_label.setVisible(not self.files and idle)
        for column in (0, 2, 3, 4, 5, 6):
            hidden = (not self.classified or (column == 0 and self.read_only)
                      or (column in (4, 5, 6) and not self.details_toggle.isChecked()))
            self.table.setColumnHidden(column, hidden)
        if self.read_only:
            self.category_summary.setText('Filename rules only. Classification settings and file changes are unavailable here.')
            hint = 'Read-only preview. Choose a test folder to classify and organize files.'
        elif self.busy:
            hint = 'Please wait. Suggestions will appear here when classification finishes.'
        elif not self.files:
            hint = 'Add files to this folder or choose another folder to begin.'
        elif not self.classified:
            hint = ('Start with Classify. You can review and edit the suggested categories first.' if self.categories is None
                    else 'Classify files to get suggested names and categories. Files are changed only after your approval.')
        elif not ready:
            hint = 'No files are ready to organize. Check their status, change the action, or classify again.'
        elif not checked:
            hint = 'Check the files you want to organize, or use Select all ready files.'
        else:
            hint = 'Ready files are checked. The next screen reviews every change before you approve it.'
        if writable:
            if self.categories:
                full_list = ', '.join(self.categories)
                summary = full_list if len(full_list) <= 95 else full_list[:92] + '…'
                self.category_summary.setText('Categories: ' + summary)
                self.category_summary.setToolTip(full_list)
            else:
                self.category_summary.setText('Choose your categories when you first classify.')
                self.category_summary.setToolTip('')
        self.next_hint.setText(hint)
        self.provider_label.setText(self.ai_config.label)
        self.provider_label.setToolTip(self.ai_config.label)
        active_step = 0 if self.read_only else 2 if reviewing else 1
        for index, label in enumerate(self.step_labels):
            label.setProperty('active', index == active_step)
            label.style().unpolish(label)
            label.style().polish(label)

    def refresh_history_state(self):
        if self.read_only:
            self.has_undo = False
        else:
            try:
                batch, _ = undo_preview(self.selected_root)
                self.has_undo = batch is not None
            except Exception:
                # Keep the action available so it can explain pending history/errors.
                self.has_undo = True

    def set_busy(self, busy):
        self.busy = busy
        self.progress_row.setVisible(busy)
        if busy:
            self.spinner.timer.start(80)
        else:
            self.spinner.timer.stop()
        self.update_select_all()

    def closeEvent(self, event):
        if self.busy:
            QMessageBox.information(self, 'Analysis in progress', 'Wait for the current analysis to finish before closing.')
            event.ignore()
        else:
            event.accept()

    def choose_folder(self):
        if self.busy:
            return
        folder = QFileDialog.getExistingDirectory(self, 'Choose a folder to preview', str(self.selected_root))
        if not folder:
            return
        try:
            try:
                selected, read_only = validate_test_folder(Path(folder)), False
            except (OSError, ValueError):
                selected, read_only = validate_preview_folder(Path(folder)), True
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, 'Folder unavailable', str(exc))
            return
        if selected == self.selected_root:
            return
        warning = '\n\nREAD-ONLY: files can be previewed but not changed or analyzed.' if read_only else ''
        answer, ok = QInputDialog.getText(self, 'Confirm folder change',
            f'Current: {self.selected_root}\nNew: {selected}{warning}\n\nThe current scan and preview will be cleared. Type YES to continue:')
        if not ok or answer != 'YES':
            return
        self.selected_root, self.read_only = selected, read_only
        self.has_undo = False
        self.categories = None if read_only else category_store.load(selected)
        self.classified = read_only
        self.files, self.proposals, self.edited_names = [], [], {}
        self.table.setRowCount(0)
        self._update_folder_label()
        self.set_busy(False)
        self.refresh()

    def refresh(self, preserve_classified=False):
        if self.busy:
            return
        try:
            if self.read_only:
                self.files, warnings = scan_readonly(self.selected_root)
            else:
                self.files, warnings = scan(self.selected_root), []
            self.edited_names = {}
            if not preserve_classified:
                self.classified = self.read_only
            self.refresh_history_state()
            self.prepare()
            if warnings:
                QMessageBox.warning(self, 'Some files could not be scanned', '\n'.join(warnings[:10]))
        except Exception as exc:
            self.files, self.proposals = [], []
            self.classified = False
            self.table.setRowCount(0)
            self.update_select_all()
            QMessageBox.critical(self, 'Scan failed', str(exc))

    def prepare(self, *_, preserve_checks=False):
        if self.busy:
            return False
        checked_names = ({self.proposals[i]['original'] for i in self.selected_rows()}
                         if preserve_checks else None)
        if not self.classified:
            self.proposals = []
            self._loading_table = True
            self.table.setRowCount(len(self.files))
            for row, file in enumerate(self.files):
                for col, value in enumerate(('—', file['filename'], '—', '—', '—', '—', '—', 'Not classified')):
                    item = QTableWidgetItem(value)
                    if col == 0:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                    self.table.setItem(row, col, item)
            self._loading_table = False
            self.update_select_all()
            self.status.setText(f'{len(self.files)} files loaded from this folder.')
            return True
        try:
            self.proposals = (build_readonly_proposals(self.files, self.mode_box.currentText(), self.selected_root)
                              if self.read_only else build_proposals(self.files, self.mode_box.currentText(), self.selected_root, self.edited_names, self.categories, self.ai_config))
        except Exception as exc:
            self.proposals = []
            self.table.setRowCount(0)
            self.update_select_all()
            QMessageBox.critical(self, 'Preview failed', str(exc))
            return False
        self._loading_table = True
        self.table.setRowCount(len(self.proposals))
        for row, p in enumerate(self.proposals):
            include = QTableWidgetItem()
            ready = not self.read_only and not p['issue']
            if ready:
                include.setFlags(include.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                checked = checked_names is None or p['original'] in checked_names
                include.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            else:
                include.setText('—')
                include.setFlags(include.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            self.table.setItem(row, 0, include)
            values = (p['original'], p['dst'].name, p['category'] or 'Needs AI', str(p['dst'].relative_to(self.selected_root)),
                      p['method'], str(p['duplicate_count']) if p['duplicate_count'] > 1 else '—', p['issue'] or 'Ready')
            for column, value in enumerate(values, 1):
                item = QTableWidgetItem(str(value))
                item.setToolTip(f"Destination: {p['dst']}\nClassified by: {p['method']}\nIdentical copies in this scan: {p['duplicate_count']}")
                self.table.setItem(row, column, item)
        self._loading_table = False
        self.update_select_all()
        ready = sum(not p['issue'] for p in self.proposals)
        self.status.setText(f'READ-ONLY · {len(self.files)} files · filename rules only · no files can be changed' if self.read_only else
                            f'{len(self.files)} files scanned  ·  {ready} ready  ·  {len(self.files)-ready} need attention')
        return True

    def toggle_all(self, state):
        if self._loading_table:
            return
        checked = state != Qt.CheckState.Unchecked.value
        self._loading_table = True
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self._loading_table = False
        self.update_select_all()

    def selection_changed(self, item):
        if not self._loading_table and item.column() == 0:
            self.update_select_all()

    def update_select_all(self):
        items = [self.table.item(row, 0) for row in range(self.table.rowCount())]
        eligible = [item for item in items if item and item.flags() & Qt.ItemFlag.ItemIsUserCheckable]
        count = sum(item.checkState() == Qt.CheckState.Checked for item in eligible)
        state = (Qt.CheckState.Unchecked if not count else Qt.CheckState.Checked if count == len(eligible)
                 else Qt.CheckState.PartiallyChecked)
        self.select_all.blockSignals(True)
        self.select_all.setCheckState(state)
        self.select_all.blockSignals(False)
        self.select_all.setEnabled(bool(eligible) and not self.busy and not self.read_only)
        self.update_workflow()

    def analyze(self):
        if self.busy or self.read_only:
            return
        if not self.files:
            QMessageBox.information(self, 'No files', 'There are no files to classify in this folder.')
            return
        if self.categories is None and not self.edit_categories():
            return
        self.classified = True
        self.prepare()
        active_config = self.ai_config
        unresolved = [f for f in self.files if f['rule_category'] not in self.categories
                      and cached_result(f, self.categories, active_config)[0] is None]
        if active_config.provider == 'rules':
            self.status.setText(f'Python rules classified {len(self.files)-len(unresolved)} files. '
                                f'{len(unresolved)} remain unresolved; enable AI in AI settings if needed.')
            self.show_classification_summary()
            return
        if not unresolved:
            self.status.setText(f'{len(self.files)} files classified using rules or cache. Review the table before organizing.')
            self.show_classification_summary()
            return
        active_categories = self.categories
        if active_config.provider == 'openai':
            answer = QMessageBox.question(self, 'Allow cloud classification?',
                f'OpenAI model: {active_config.model}\n\n'
                f'Classify up to {len(unresolved)} ambiguous files using the OpenAI API? '
                'Up to 1,200 characters of extracted text per document, the extension, numeric file ID and chosen categories '
                'will be sent. Filenames are sent when text is unavailable. Full files are not uploaded. '
                'Duplicate content may be grouped. API usage charges apply.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                self.status.setText('Cloud classification cancelled. No document text was sent.')
                return
        self.set_busy(True)
        self.progress_label.setText(f'Classifying with {active_config.label}…')
        self.status.setText(f'Analyzing {len(unresolved)} files with {active_config.label}…')

        def worker():
            errors, completed, unique = [], 0, {}
            try:
                for f in unresolved:
                    unique.setdefault((f['sha256'], f['extension']), f)
                reps = list(unique.values())
                for start in range(0, len(reps), 10):
                    batch = reps[start:start + 10]
                    try:
                        results = analyze_files(batch, warnings=errors, categories=active_categories, ai_config=active_config)
                        for f in batch:
                            result = results.get(f['filename'])
                            if not result:
                                errors.append(f"{f['filename']}: AI returned no valid result. Try again.")
                                continue
                            try:
                                if content_cache_write(f, result, active_categories, active_config):
                                    completed += 1
                                else:
                                    errors.append(f"{f['filename']}: the file changed; scan and try again.")
                            except Exception as exc:
                                errors.append(f"{f['filename']}: could not save the result to the cache ({exc}).")
                    except Exception as exc:
                        errors.append(providers.error_message(exc, active_config))
            except Exception as exc:
                errors.append(f'Analysis could not be completed: {exc}')
            finally:
                self.signals.finished.emit(completed, len(unresolved) - len(unique), errors)
        threading.Thread(target=worker, daemon=True).start()

    def analysis_finished(self, completed, grouped, errors):
        self.set_busy(False)
        self.refresh(preserve_classified=True)
        self.status.setText(self.status.text() + f'  ·  {completed} new analyses  ·  {grouped} duplicates grouped')
        if errors:
            QMessageBox.warning(self, 'Analysis needs attention', '\n\n'.join(errors[:10]))
        self.show_classification_summary()

    def show_classification_summary(self):
        ClassificationSummary(classification_counts(self.proposals), self).exec()

    def selected_rows(self):
        return [row for row in range(self.table.rowCount())
                if (item := self.table.item(row, 0)) is not None
                and item.flags() & Qt.ItemFlag.ItemIsUserCheckable
                and item.checkState() == Qt.CheckState.Checked]

    def edit_ai_settings(self):
        if self.busy:
            return
        dialog = AISetupDialog(self.ai_config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.ai_config = dialog.saved_config
            self.refresh()

    def edit_categories(self):
        if self.busy or self.read_only:
            return False
        initial = self.categories or category_store.SUGGESTED
        text, ok = QInputDialog.getMultiLineText(
            self, 'Categories for this folder',
            'Edit these suggested categories, one per line. Include Other for uncertain files:',
            '\n'.join(initial))
        if not ok:
            return False
        try:
            self.categories = category_store.save(self.selected_root, text.splitlines())
        except Exception as exc:
            QMessageBox.warning(self, 'Invalid categories', str(exc))
            return False
        self.classified = False
        self.edited_names = {}
        self.prepare()
        return True

    def edit_name(self):
        if self.busy or self.read_only:
            return
        rows = sorted(index.row() for index in self.table.selectionModel().selectedRows())
        if not self.classified:
            QMessageBox.information(self, 'Classification required', 'Click Classify first.')
            return
        if len(rows) != 1:
            QMessageBox.information(self, 'Select a file', 'Select one file to edit its suggested name.')
            return
        if self.mode_box.currentText() == 'Organize only':
            QMessageBox.information(self, 'Rename mode required', 'Choose Rename only or Rename + Organize first.')
            return
        p = self.proposals[rows[0]]
        name, ok = QInputDialog.getText(self, 'Edit suggested name', 'Enter a filename with the original extension:', text=p['suggested'])
        if not ok:
            return
        if not valid_filename(name, p['original']):
            QMessageBox.warning(self, 'Invalid filename', 'Use a valid Windows filename and keep the original extension.')
            return
        self.edited_names[p['original']] = name
        if self.prepare(preserve_checks=True):
            self.table.selectRow(rows[0])
            self.status.setText(self.status.text() + '  ·  review changes when organizing')

    def confirm_apply(self):
        if self.busy or self.read_only:
            return
        rows = self.selected_rows()
        if not self.classified:
            QMessageBox.information(self, 'Classification required', 'Click Classify first.')
            return
        if not rows:
            QMessageBox.information(self, 'No files checked', 'Check the files you want to organize, or use Select all ready files.')
            return
        choices = [self.proposals[row] for row in rows]
        if any(p['issue'] for p in choices):
            QMessageBox.warning(self, 'Unsafe selection', 'Only ready files can be organized. Review their status first.')
            return
        if ApprovalDialog(self.selected_root, choices, self).exec() != QDialog.DialogCode.Accepted:
            return
        answer, ok = QInputDialog.getText(self, 'Confirm operations', 'Type YES to perform these test-file moves:')
        if not ok or answer != 'YES':
            self.status.setText('Cancelled. No actions taken.')
            return
        try:
            outcomes = apply_proposals(choices, self.selected_root)
            self.refresh()
            self.show_operation_results('Move results', outcomes)
        except Exception as exc:
            QMessageBox.critical(self, 'Move blocked', self.operation_error(exc))

    def confirm_undo(self):
        if self.busy or self.read_only:
            return
        try:
            batch, entries = undo_preview(self.selected_root)
            if not batch:
                QMessageBox.information(self, 'Undo last batch', 'No completed batch to undo for this folder.')
                return
            paths = '\n'.join(f'{destination}  →  {source}' for _, source, destination, _ in entries[:15])
            if len(entries) > 15:
                paths += f'\n...and {len(entries)-15} more'
            if QMessageBox.question(self, 'Undo last batch', f'Folder: {self.selected_root}\n\nRestore these files?\n\n{paths}') != QMessageBox.StandardButton.Yes:
                return
            outcomes = undo_last_batch(self.selected_root, expected_batch=batch)
            self.refresh()
            self.show_operation_results('Undo results', outcomes)
        except Exception as exc:
            QMessageBox.critical(self, 'Undo blocked', self.operation_error(exc))

    def operation_error(self, exc):
        try:
            pending = history_pending()
        except Exception:
            pending = []
        if not pending:
            return str(exc)
        details = '\n\n'.join(f'Source: {src}\nDestination: {dst}\n{note}' for _, src, dst, note in pending[:5])
        return f'{exc}\n\nInspect both paths and the history before continuing. Do not delete either file until you understand what happened.\n\n{details}'

    def show_operation_results(self, title, outcomes):
        summary = '\n'.join(f'{name}: {status}' for name, status in outcomes)[:3500]
        if any(status.startswith('CHECK MANUALLY') for _, status in outcomes):
            QMessageBox.warning(self, title, self.operation_error(summary))
        else:
            QMessageBox.information(self, title, summary)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    try:
        from .config import PROJECT
        PROJECT.mkdir(parents=True, exist_ok=True)
        ROOT.mkdir(parents=True, exist_ok=True)
        config = startup_config()
        migrate_legacy_databases()
        window = OrganizerWindow(ai_config=config)
    except Exception as exc:
        QMessageBox.critical(None, 'Startup failed', f'Could not start the organizer: {exc}')
        return 1
    window.show()
    return app.exec()
