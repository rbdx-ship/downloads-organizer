"""Validated, non-secret AI settings. API keys live in Windows Credential Manager."""
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import tempfile

from .config import PROJECT, MODEL

SETTINGS_PATH = PROJECT / 'ai_settings.json'
SERVICE = 'DownloadsOrganizer.OpenAI'


@dataclass(frozen=True)
class AIConfig:
    provider: str = 'ollama'
    model: str = MODEL
    cloud_consent: bool = False

    def __post_init__(self):
        if self.provider not in ('ollama', 'openai', 'rules'):
            raise ValueError('Choose Local Ollama, OpenAI, or Python rules only.')
        if self.provider != 'rules' and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}', self.model):
            raise ValueError('Enter a valid model name.')
        if self.provider == 'ollama' and self.model.lower().endswith('cloud'):
            raise ValueError('Choose a downloaded local model. Ollama cloud models are not supported by the local option.')
        if type(self.cloud_consent) is not bool:
            raise ValueError('Invalid cloud consent setting.')
        if self.provider == 'openai' and not self.cloud_consent:
            raise ValueError('Consent is required before using cloud AI.')

    @property
    def cache_model(self):
        # Versioned adapter identity prevents provider/model/settings collisions.
        return f'{self.provider}:{self.model}:adapter-v1'

    @property
    def label(self):
        return {'rules': 'Python rules only', 'ollama': f'Local Ollama · {self.model}',
                'openai': f'OpenAI · {self.model}'}[self.provider]


def load(path=None):
    path = SETTINGS_PATH if path is None else Path(path)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('version') != 1 or data.get('setup_completed') is not True:
        raise ValueError('AI settings are incomplete or from an unsupported version. Run setup again.')
    return AIConfig(provider=data['provider'], model=data['model'], cloud_consent=data['cloud_consent'])


def save(config, path=None):
    path = SETTINGS_PATH if path is None else Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='ai-settings-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({'version': 1, 'setup_completed': True, **asdict(config)}, stream, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def credential_store():
    if os.name != 'nt':
        raise RuntimeError('This version requires Windows Credential Manager for API keys.')
    # Explicit backend: never fall back to plaintext credential storage.
    from keyring.backends.Windows import WinVaultKeyring
    return WinVaultKeyring()


def get_api_key():
    key = credential_store().get_password(SERVICE, 'api-key')
    if not key:
        raise RuntimeError('No OpenAI API key is saved. Open AI settings and enter your key.')
    return key


def save_api_key(key):
    key = key.strip()
    if not key or any(ch.isspace() for ch in key):
        raise ValueError('Enter an API key without spaces.')
    credential_store().set_password(SERVICE, 'api-key', key)


def commit(config, key=None, path=None):
    """Save settings without leaving a changed credential behind on file failure."""
    if config.provider != 'openai' or not key:
        save(config, path)
        return
    store = credential_store()
    old = store.get_password(SERVICE, 'api-key')
    key = key.strip()
    if not key or any(ch.isspace() for ch in key):
        raise ValueError('Enter an API key without spaces.')
    store.set_password(SERVICE, 'api-key', key)
    try:
        save(config, path)
    except Exception:
        if old is None:
            store.delete_password(SERVICE, 'api-key')
        else:
            store.set_password(SERVICE, 'api-key', old)
        raise
