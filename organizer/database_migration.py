"""Copy old databases to their new names without changing the originals."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile

from .config import DB_PATH, HISTORY_DB, LEGACY_DB_PATH, LEGACY_HISTORY_DB


def copy_legacy_database(source, destination):
    source, destination = Path(source), Path(destination)
    if destination.exists() or not source.exists():
        return False
    # SQLite's backup API includes committed data still in a WAL file.
    fd, temporary = tempfile.mkstemp(prefix=destination.name + '.', suffix='.tmp', dir=destination.parent)
    os.close(fd)
    try:
        with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as old, \
             closing(sqlite3.connect(temporary)) as new:
            old.backup(new)
            if new.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError(f'Integrity check failed while copying {source.name}.')
        # Windows rename fails if a destination appears concurrently.
        os.rename(temporary, destination)
        return True
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def migrate_legacy_databases():
    for source, destination in ((LEGACY_DB_PATH, DB_PATH), (LEGACY_HISTORY_DB, HISTORY_DB)):
        copy_legacy_database(source, destination)
