"""First-run AI setup and later provider settings, with background setup tasks."""
import threading

from PySide6.QtCore import QObject, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QProgressBar, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from . import ai_settings, ai_setup_tasks, providers
from .ai_settings import AIConfig
from .config import MODEL


class SetupSignals(QObject):
    progress = Signal(str, int)
    finished = Signal(str, object, str)


class AISetupDialog(QDialog):
    def __init__(self, current=None, parent=None, settings_path=None):
        super().__init__(parent)
        self.setWindowTitle('Set up AI' if current is None else 'AI settings')
        self.setMinimumWidth(650)
        self.settings_path = settings_path
        self.saved_config = None
        self.verified = None
        self.busy = False
        self.cancel_event = threading.Event()
        self._close_when_done = False
        self.signals = SetupSignals(self)
        self.signals.progress.connect(self.on_progress)
        self.signals.finished.connect(self.on_finished)
        self.setStyleSheet('''
            QDialog { background: white; }
            QMessageBox, QInputDialog { background: #ffffff; color: #183d37; }
            QMessageBox QLabel, QInputDialog QLabel { color: #183d37; background: transparent; }
            QWidget { color: #183d37; font-family: 'Segoe UI'; font-size: 10pt; }
            QLabel#title { font-size: 20pt; font-weight: 700; }
            QLabel#muted { color: #506e64; }
            QPushButton { background: #eaf2ed; border: 0; border-radius: 7px; padding: 9px 13px; }
            QPushButton:disabled { color: #97a79e; background: #f2f5f3; }
            QPushButton#save { background: #173f35; color: white; }
            QPushButton#save:disabled { background: #b7cbc1; }
            QLineEdit, QComboBox { border: 1px solid #cadcd0; border-radius: 6px; padding: 8px; background: white; }
            QProgressBar { border: 0; background: #eaf2ed; height: 9px; }
            QProgressBar::chunk { background: #26775f; }
        ''')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(12)
        layout.addWidget(self.label('How would you like to classify files?', 'title'))
        layout.addWidget(self.label('Python rules always handle straightforward files. Choose how to handle the rest.', 'muted'))
        self.provider_combo = QComboBox()
        self.provider_combo.addItem('Local AI with Ollama — runs on this computer', 'ollama')
        self.provider_combo.addItem('OpenAI API — cloud processing and usage charges', 'openai')
        self.provider_combo.addItem('Python rules only — no AI setup', 'rules')
        layout.addWidget(self.provider_combo)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages)
        self.mutable_controls = [self.provider_combo]
        self._build_local()
        self._build_cloud()
        rules = QWidget()
        rules_layout = QVBoxLayout(rules)
        rules_layout.addWidget(self.label('No downloads or API key needed. Files matched by Python rules can be organized. '
                                         'Ambiguous files will stay unresolved. You can enable AI later in AI settings.'))
        rules_layout.addStretch()
        self.pages.addWidget(rules)
        self.status = self.label('Choose an option, then follow its setup steps.', 'muted')
        self.status.setMinimumHeight(48)
        layout.addWidget(self.status)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        footer = QHBoxLayout()
        self.cancel_task_btn = QPushButton('Cancel task')
        self.cancel_task_btn.clicked.connect(self.cancel_task)
        self.cancel_task_btn.hide()
        footer.addWidget(self.cancel_task_btn)
        footer.addStretch()
        self.cancel_btn = QPushButton('Cancel')
        self.cancel_btn.clicked.connect(self.reject)
        self.save_btn = QPushButton('Save & continue')
        self.save_btn.setObjectName('save')
        self.save_btn.clicked.connect(self.save_selection)
        footer.addWidget(self.cancel_btn)
        footer.addWidget(self.save_btn)
        layout.addLayout(footer)
        self.provider_combo.currentIndexChanged.connect(self.input_changed)
        if current:
            self.local_model.setCurrentText(current.model if current.provider == 'ollama' else MODEL)
            self.cloud_model.setText(current.model if current.provider == 'openai' else 'gpt-4o-mini')
            self.cloud_consent.setChecked(current.cloud_consent)
            self.provider_combo.setCurrentIndex({'ollama': 0, 'openai': 1, 'rules': 2}[current.provider])
        self.input_changed()

    @staticmethod
    def label(text, name=None):
        label = QLabel(text)
        label.setWordWrap(True)
        if name:
            label.setObjectName(name)
        return label

    def task_button(self, text, callback, layout):
        button = QPushButton(text)
        button.clicked.connect(callback)
        layout.addWidget(button)
        self.mutable_controls.append(button)
        return button

    def _build_local(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.addWidget(self.label('1. Check or install Ollama'))
        layout.addWidget(self.label('Ollama is the local engine; the model is a separate download. '
                                    'Installation opens the official Windows installer.', 'muted'))
        row = QHBoxLayout()
        self.detect_btn = self.task_button('Check installation', self.check_local, row)
        self.install_btn = self.task_button('Download & install Ollama', self.install_local, row)
        self.start_btn = self.task_button('Start Ollama', lambda: self.run_task('start', ai_setup_tasks.start_ollama), row)
        layout.addLayout(row)
        official = QPushButton('Open official download page')
        official.clicked.connect(lambda: QDesktopServices.openUrl(QUrl('https://ollama.com/download/windows')))
        layout.addWidget(official)
        layout.addWidget(self.label('2. Choose or download a model'))
        self.local_model = QComboBox()
        self.local_model.setEditable(True)
        self.local_model.addItem(MODEL)
        self.local_model.setToolTip('The project has been tested with qwen2.5:7b. You may enter another Ollama model name.')
        self.local_model.currentTextChanged.connect(self.input_changed)
        self.mutable_controls.append(self.local_model)
        layout.addWidget(self.local_model)
        try:
            hardware = ai_setup_tasks.hardware_summary()
        except Exception:
            hardware = 'Check available memory and disk space. Models may require several GB and performance depends on your hardware.'
        layout.addWidget(self.label(hardware, 'muted'))
        self.pull_btn = self.task_button('Download selected model', self.download_model, layout)
        layout.addWidget(self.label('3. Verify the setup'))
        self.test_local_btn = self.task_button('Test model with sample text', self.test_selection, layout)
        self.pages.addWidget(page)

    def _build_cloud(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.addWidget(self.label('1. Enter your OpenAI model and API key'))
        layout.addWidget(self.label('Use your own OpenAI API account. API usage incurs charges. '
            'The connection test sends sample text only; file classification is a separate action.', 'muted'))
        self.cloud_model = QLineEdit('gpt-4o-mini')
        self.cloud_model.setPlaceholderText('A model ID with structured output support')
        self.cloud_model.setToolTip('Starter option: gpt-4o-mini. Model availability depends on your API account.')
        layout.addWidget(self.cloud_model)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText('API key, or leave blank to use a previously saved key')
        layout.addWidget(self.key_edit)
        layout.addWidget(self.label('Your key is stored in Windows Credential Manager, never in the settings file or database.', 'muted'))
        links = QHBoxLayout()
        for text, url in [('Get an API key', 'https://platform.openai.com/api-keys'),
                          ('API pricing', 'https://developers.openai.com/api/docs/pricing'),
                          ('Data controls', 'https://developers.openai.com/api/docs/guides/your-data')]:
            button = QPushButton(text)
            button.clicked.connect(lambda _=False, link=url: QDesktopServices.openUrl(QUrl(link)))
            links.addWidget(button)
        layout.addLayout(links)
        layout.addWidget(self.label('2. Review what leaves your computer'))
        self.cloud_consent = QCheckBox('I allow OpenAI processing and understand that API charges apply.')
        layout.addWidget(self.cloud_consent)
        layout.addWidget(self.label('For ambiguous files, the app sends up to 1,200 characters of extracted document text, '
            'the extension, numeric file ID and chosen categories, plus the filename when text is unavailable. It does not upload whole files. '
            'You will confirm each cloud classification run. There is no automatic cloud fallback.', 'muted'))
        layout.addWidget(self.label('3. Verify model access'))
        self.test_cloud_btn = self.task_button('Test connection with sample text', self.test_selection, layout)
        self.mutable_controls.extend([self.cloud_model, self.key_edit, self.cloud_consent])
        self.cloud_model.textChanged.connect(self.input_changed)
        self.key_edit.textChanged.connect(self.input_changed)
        self.cloud_consent.toggled.connect(self.input_changed)
        layout.addStretch()
        self.pages.addWidget(page)

    def candidate(self):
        provider = self.provider_combo.currentData()
        model = (self.local_model.currentText().strip() if provider == 'ollama' else
                 self.cloud_model.text().strip() if provider == 'openai' else '')
        return AIConfig(provider, model, provider == 'openai' and self.cloud_consent.isChecked())

    def input_changed(self, *_):
        if not hasattr(self, 'save_btn'):
            return
        self.verified = None
        self.pages.setCurrentIndex(self.provider_combo.currentIndex())
        self.save_btn.setEnabled(self.provider_combo.currentData() == 'rules' and not self.busy)

    def check_local(self):
        self.run_task('detect', ai_setup_tasks.detect_ollama)

    def install_local(self):
        answer = QMessageBox.question(self, 'Install Ollama',
            'Download the official Ollama Windows installer and launch it? It may require several GB of disk space. '
            'You will complete installation in its own window.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.run_task('install', lambda: ai_setup_tasks.install_ollama(self.signals.progress.emit, self.cancel_event))

    def download_model(self):
        try:
            config = self.candidate()
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        answer = QMessageBox.question(self, 'Download model',
            f'Download {config.model} through local Ollama? The model may require several GB. '
            'Existing downloaded layers are reused.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.verified = None
            self.run_task('pull', lambda: ai_setup_tasks.pull_model(config.model, self.signals.progress.emit, self.cancel_event))

    def test_selection(self):
        try:
            config = self.candidate()
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        key = self.key_edit.text().strip() if config.provider == 'openai' else None
        self.verified = None
        self.run_task('test', lambda: (config, ai_setup_tasks.test_config(config, key or None)), config)

    def run_task(self, kind, task, config=None):
        if self.busy:
            return
        self.busy = True
        self.cancel_event.clear()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()
        self.cancel_task_btn.show()
        self.save_btn.setEnabled(False)
        self.status.setText('Working…')
        for control in self.mutable_controls:
            control.setEnabled(False)

        def worker():
            result, error = None, ''
            try:
                result = task()
                if self.cancel_event.is_set():
                    raise ai_setup_tasks.Cancelled('Task cancelled. No AI configuration was saved.')
            except ai_setup_tasks.Cancelled as exc:
                error = str(exc)
            except Exception as exc:
                if self.cancel_event.is_set():
                    error = 'Task cancelled. No AI configuration was saved.'
                elif kind == 'test':
                    error = providers.error_message(exc, config)
                elif kind == 'detect':
                    error = 'Ollama is not reachable. Start it, or download and install it, then check again.'
                elif isinstance(exc, RuntimeError):
                    error = str(exc)
                else:
                    error = 'Setup could not complete. Check connectivity, disk space and Ollama, then retry.'
            self.signals.finished.emit(kind, result, error)
        threading.Thread(target=worker, daemon=True).start()

    def on_progress(self, text, percent):
        self.status.setText(text)
        self.progress_bar.setRange(0, 0 if percent < 0 else 100)
        if percent >= 0:
            self.progress_bar.setValue(percent)

    def on_finished(self, kind, result, error):
        self.busy = False
        self.progress_bar.hide()
        self.cancel_task_btn.hide()
        for control in self.mutable_controls:
            control.setEnabled(True)
        if self._close_when_done:
            self.key_edit.clear()
            super().reject()
            return
        if error:
            self.status.setText(error)
        elif kind == 'detect':
            selected = self.local_model.currentText()
            for model in result:
                if self.local_model.findText(model) < 0:
                    self.local_model.addItem(model)
            self.local_model.setCurrentText(selected)
            self.status.setText('Ollama is running. Installed models: ' + (', '.join(result) if result else 'none. Download a model next.'))
        elif kind == 'test':
            self.verified, message = result
            self.status.setText(message + ' Save to finish setup.')
        else:
            self.status.setText(str(result))
        self.save_btn.setEnabled(self.verified is not None or self.provider_combo.currentData() == 'rules')

    def cancel_task(self):
        self.cancel_event.set()
        self.status.setText('Cancelling… An active connection test or Windows installer must finish before closing.')

    def reject(self):
        if self.busy:
            self._close_when_done = True
            self.cancel_task()
            return
        self.key_edit.clear()
        super().reject()

    def closeEvent(self, event):
        if self.busy:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)

    def save_selection(self):
        if self.busy:
            return
        try:
            config = self.candidate()
            if config.provider != 'rules' and config != self.verified:
                raise ValueError('Test the selected model successfully before saving.')
            key = self.key_edit.text().strip()
            ai_settings.commit(config, key if config.provider == 'openai' else None, self.settings_path)
        except Exception as exc:
            self.status.setText('Could not save AI settings. Check credential storage and file access. ' +
                                (str(exc) if isinstance(exc, ValueError) else ''))
            return
        self.saved_config = config
        self.key_edit.clear()
        super().accept()


def startup_config():
    """Prompt only when setup is absent/invalid; cancellation remains temporary."""
    try:
        config = ai_settings.load()
    except Exception:
        QMessageBox.warning(None, 'AI setup required', 'Saved AI settings could not be read. Choose your AI setup again.')
        config = None
    if config is not None:
        return config
    setup = AISetupDialog()
    if setup.exec() == QDialog.DialogCode.Accepted:
        return setup.saved_config
    return AIConfig('rules', '')
