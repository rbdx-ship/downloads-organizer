"""Folder-specific category settings, stored with operation history."""
from contextlib import closing
import json
import sqlite3
from pathlib import Path
from . import file_manager
from .config import INVALID_CHARS, WINDOWS_RESERVED
from .folder_access import validate_operation_folder

SUGGESTED = ('Career', 'Finance', 'Learning', 'Images', 'Other')


def validate_categories(names):
    cleaned = tuple(name.strip() for name in names)
    if not cleaned or len(cleaned) > 30:
        raise ValueError('Choose between 1 and 30 categories.')
    if len({name.casefold() for name in cleaned}) != len(cleaned):
        raise ValueError('Category names must be unique, ignoring capitalization.')
    for name in cleaned:
        if (not name or len(name) > 100 or name in {'.', '..'} or name.endswith(('.', ' '))
                or any(ord(ch) < 32 or ch in INVALID_CHARS for ch in name)
                or name.split('.')[0].upper() in WINDOWS_RESERVED):
            raise ValueError(f'Invalid Windows folder name: {name!r}')
    if 'Other' not in cleaned:
        raise ValueError('Include a category named Other for uncertain files.')
    return cleaned


def load(root):
    root = validate_operation_folder(Path(root))
    with closing(file_manager.history_connect()) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='folder_categories'").fetchone():
            return None
        row = conn.execute('SELECT categories FROM folder_categories WHERE folder=?', (str(root),)).fetchone()
    return validate_categories(json.loads(row[0])) if row else None


def save(root, names):
    root = validate_operation_folder(Path(root))
    cleaned = validate_categories(names)
    with closing(file_manager.history_connect()) as conn, conn:
        conn.execute('CREATE TABLE IF NOT EXISTS folder_categories (folder TEXT PRIMARY KEY, categories TEXT NOT NULL)')
        conn.execute('INSERT OR REPLACE INTO folder_categories (folder, categories) VALUES (?, ?)',
                     (str(root), json.dumps(cleaned, ensure_ascii=False)))
    return cleaned
