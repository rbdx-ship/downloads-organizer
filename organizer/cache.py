from __future__ import annotations
import sqlite3
from contextlib import closing
from pathlib import Path
from .config import *
from .file_identity import file_sha256

def ensure_content_cache(conn):
    'New table: an AI result can be shared by identical file contents.'
    conn.execute('''CREATE TABLE IF NOT EXISTS content_classifications (
        sha256 TEXT NOT NULL, extension TEXT NOT NULL, model TEXT NOT NULL,
        policy_hash TEXT NOT NULL, category TEXT NOT NULL,
        suggested_name TEXT NOT NULL, reason TEXT NOT NULL,
        PRIMARY KEY (sha256, extension, model, policy_hash))''')


def content_cache_read(file, categories=None, ai_config=None):
    if ai_config is not None and ai_config.provider == 'rules':
        return None
    model = MODEL if ai_config is None else ai_config.cache_model
    allowed = CATEGORIES if categories is None else categories
    fingerprint = POLICY_HASH if categories is None else policy_hash(allowed)
    if not DB_PATH.exists() or not file.get('sha256'):
        return None
    try:
        with closing(sqlite3.connect(DB_PATH)) as conn, conn:
            row = conn.execute('''SELECT category, suggested_name, reason
                FROM content_classifications
                WHERE sha256=? AND extension=? AND model=? AND policy_hash=?''',
                (file['sha256'], file['extension'], model, fingerprint)).fetchone()
    except sqlite3.Error:
        return None
    if row and row[0] in allowed:
        return {'category': row[0], 'suggested_name': row[1], 'reason': row[2]}
    return None


def cached_result(file, categories=None, ai_config=None):
    'Favor shared content identity; still honor the old path cache.'
    result = content_cache_read(file, categories, ai_config)
    if result is not None:
        return result, 'Content cache'
    result = cache_read(file, categories, ai_config)
    if result is not None:
        return result, 'Path cache'
    return None, None


def content_cache_write(file, result, categories=None, ai_config=None):
    'Store only if file has not changed since scanning; never overwrite hash results.'
    p = Path(file['path'])
    if ai_config is not None and ai_config.provider == 'rules':
        return False
    model = MODEL if ai_config is None else ai_config.cache_model
    if p.is_symlink() or not p.is_file():
        return False
    before = p.stat()
    if before.st_size != file['size'] or before.st_mtime_ns != file['mtime_ns']:
        return False
    if file_sha256(p) != file['sha256']:
        return False
    after = p.stat()
    if after.st_size != before.st_size or after.st_mtime_ns != before.st_mtime_ns:
        return False
    allowed = CATEGORIES if categories is None else categories
    fingerprint = POLICY_HASH if categories is None else policy_hash(allowed)
    if result['category'] not in allowed:
        return False
    PROJECT.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        ensure_content_cache(conn)
        conn.execute('''INSERT OR IGNORE INTO content_classifications
            (sha256, extension, model, policy_hash, category, suggested_name, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (file['sha256'], file['extension'], model, fingerprint,
             result['category'], result['suggested_name'], result['reason']))
    return True


def cache_read(file, categories=None, ai_config=None):
    if ai_config is not None and ai_config.provider == 'rules':
        return None
    model = MODEL if ai_config is None else ai_config.cache_model
    allowed = CATEGORIES if categories is None else categories
    fingerprint = POLICY_HASH if categories is None else policy_hash(allowed)
    if not DB_PATH.exists():
        return None
    try:
        with closing(sqlite3.connect(DB_PATH)) as conn, conn:
            row = conn.execute('''SELECT category, suggested_name, reason FROM classifications_v2
                                  WHERE path=? AND file_size=? AND modified_ns=?
                                  AND model=? AND policy_hash=?''',
                               (str(Path(file['path']).resolve()), file['size'], file['mtime_ns'],
                                model, fingerprint)).fetchone()
    except sqlite3.Error:
        return None
    if row and row[0] in allowed:
        return {'category': row[0], 'suggested_name': row[1], 'reason': row[2]}
    return None


def cache_write(file, result):
    PROJECT.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS classifications_v2 (
            path TEXT NOT NULL, file_size INTEGER NOT NULL, modified_ns INTEGER NOT NULL,
            model TEXT NOT NULL, policy_hash TEXT NOT NULL, category TEXT NOT NULL,
            suggested_name TEXT NOT NULL, reason TEXT NOT NULL,
            PRIMARY KEY(path, model, policy_hash))''')
        # Only cache when the file has not changed while the model was analyzing it.
        p = Path(file['path'])
        if not p.is_file() or p.is_symlink():
            return False
        stat = p.stat()
        if stat.st_size != file['size'] or stat.st_mtime_ns != file['mtime_ns']:
            return False
        conn.execute('''INSERT OR REPLACE INTO classifications_v2
            (path,file_size,modified_ns,model,policy_hash,category,suggested_name,reason)
            VALUES(?,?,?,?,?,?,?,?)''',
            (str(p.resolve()), stat.st_size, stat.st_mtime_ns, MODEL, POLICY_HASH,
             result['category'], result['suggested_name'], result['reason']))
    return True

