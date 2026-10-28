"""Persistent folder-name guard; independent of AI credentials and caches."""
import json
import os
from pathlib import Path
import tempfile
from .config import PROJECT, INVALID_CHARS, WINDOWS_RESERVED

SETTINGS_PATH = PROJECT / 'safety_settings.json'
DEFAULT_FOLDER_NAME = 'Downloads'


def validate_name(name):
    if (not isinstance(name, str) or not name or name != name.strip() or len(name) > 100
            or name.startswith('.') or name.endswith('.') or name in {'.', '..'}
            or name.split('.')[0].upper() in WINDOWS_RESERVED
            or any(ord(c) < 32 or c in INVALID_CHARS for c in name)):
        raise ValueError('Enter one valid folder name, without a path, surrounding spaces, or a trailing dot.')
    return name


def required_name():
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding='utf-8'))
        if data.get('version') != 1:
            raise ValueError('Unsupported settings version')
        return validate_name(data['required_folder_name'])
    except FileNotFoundError:
        return DEFAULT_FOLDER_NAME
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError('Safety settings cannot be read. Open Safety settings and save a valid folder name.') from exc


def validate_folder_name(folder):
    name = required_name()
    if Path(folder).name.casefold() != name.casefold():
        raise ValueError(f'Writable target folders must be named "{name}". '
                         'Choose a matching folder or change the name in Safety settings.')


def save_name(name):
    name = validate_name(name)
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=SETTINGS_PATH.parent, prefix='safety-settings-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({'version': 1, 'required_folder_name': name}, stream, indent=2)
        os.replace(temporary, SETTINGS_PATH)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    # Existing folder approvals cannot survive a policy change.
    from .folder_access import _approved
    _approved.clear()
