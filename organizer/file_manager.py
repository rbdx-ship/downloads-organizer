from __future__ import annotations
import os
import sqlite3
from contextlib import closing
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from .config import *
from .cache import cached_result
from .file_identity import file_sha256
from .folder_access import validate_operation_folder, is_test_folder

def utc_now():
    return datetime.now(timezone.utc).isoformat()


def history_connect():
    return sqlite3.connect(HISTORY_DB)


def history_init():
    PROJECT.mkdir(parents=True, exist_ok=True)
    with closing(history_connect()) as conn, conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS operations (
            id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, created_at TEXT NOT NULL,
            source TEXT NOT NULL, destination TEXT NOT NULL, sha256 TEXT NOT NULL,
            status TEXT NOT NULL, updated_at TEXT NOT NULL, note TEXT NOT NULL DEFAULT ''
        )''')


def history_insert(op_id, batch_id, src, dst, digest):
    with closing(history_connect()) as conn, conn:
        conn.execute('INSERT INTO operations VALUES (?,?,?,?,?,?,?,?,?)',
                     (op_id, batch_id, utc_now(), str(src), str(dst), digest, 'pending', utc_now(), ''))


def history_set(op_id, status, note=''):
    with closing(history_connect()) as conn, conn:
        conn.execute('UPDATE operations SET status=?, updated_at=?, note=? WHERE id=?',
                     (status, utc_now(), note, op_id))


def history_pending():
    with closing(history_connect()) as conn, conn:
        return conn.execute("SELECT id,source,destination,note FROM operations WHERE status='pending'").fetchall()


def valid_filename(name, original):
    if not isinstance(name, str) or not name or name != Path(name).name:
        return False
    if name in {'.', '..'} or len(name) > 200 or name.endswith(('.', ' ')):
        return False
    if any(ord(ch) < 32 or ch in INVALID_CHARS for ch in name):
        return False
    if name.split('.')[0].upper() in WINDOWS_RESERVED:
        return False
    return Path(name).suffix.lower() == Path(original).suffix.lower()


def valid_category(name, categories=None):
    allowed = CATEGORIES if categories is None else categories
    return (isinstance(name, str) and name in allowed and bool(name) and len(name) <= 100
            and name not in {'.', '..'} and not name.endswith(('.', ' '))
            and name.split('.')[0].upper() not in WINDOWS_RESERVED
            and not any(ord(ch) < 32 or ch in INVALID_CHARS for ch in name))


def existing_path_casefold(parent, name):
    if not parent.exists():
        return None
    for p in parent.iterdir():
        if p.name.casefold() == name.casefold():
            return p
    return None


def safe_source(path, root=None):
    root = validate_operation_folder(ROOT if root is None else root)
    return (path.parent == root and not path.is_symlink() and path.is_file()
            and path.resolve().parent == root)


def safe_destination(path, root=None, categories=None):
    root = validate_operation_folder(ROOT if root is None else root)
    parent = path.parent
    if parent == root:
        return True
    allowed = CATEGORIES if categories is None else categories
    if parent.parent != root or not valid_category(parent.name, allowed):
        return False
    # Reject links and Windows junctions, even if they point back into the root.
    if parent.is_symlink() or parent.is_junction():
        return False
    return parent.resolve() == parent


def build_proposals(files, mode, root=None, name_overrides=None, categories=None, ai_config=None):
    if mode not in MODES:
        raise ValueError('Invalid operating mode')
    root = validate_operation_folder(ROOT if root is None else root)
    allowed = CATEGORIES if categories is None else tuple(categories)
    proposals = []
    hash_counts = Counter(f['sha256'] for f in files)
    for f in files:
        original = f['filename']
        src = root / original
        cached, cache_origin = cached_result(f, categories, ai_config)
        # Content cache takes precedence to maintain consistent names for identical files.
        if cached and cache_origin == 'Content cache':
            category, suggested, method = cached['category'], cached['suggested_name'], cache_origin
        elif f['rule_category'] in allowed:
            category, suggested, method = f['rule_category'], original, 'Python rules'
        elif cached:
            category, suggested, method = cached['category'], cached['suggested_name'], cache_origin
        else:
            category, suggested, method = None, original, 'Needs AI'
        if name_overrides and original in name_overrides:
            suggested = name_overrides[original]
        new_name = original if mode == 'Organize only' else suggested
        dst = (root / new_name if mode == 'Rename only' else
               root / category / new_name if category else root / new_name)
        problem = None
        if method == 'Needs AI':
            problem = ('Needs AI — configure it in AI settings' if ai_config is not None and ai_config.provider == 'rules'
                       else 'Classify this file with AI first')
        elif not valid_category(category, allowed):
            problem = 'Invalid category'
        elif not valid_filename(new_name, original):
            problem = 'Unsafe filename or changed extension'
        elif not safe_source(src, root):
            problem = 'Source missing or outside selected folder'
        elif src.stat().st_size == 0:
            problem = 'Empty file — review manually'
        elif not safe_destination(dst, root, allowed):
            problem = 'Destination outside selected folder'
        elif src == dst:
            problem = 'No change needed'
        elif existing_path_casefold(dst.parent, dst.name) is not None:
            other = existing_path_casefold(dst.parent, dst.name)
            problem = 'Identical file already at destination' if (
                other.is_file() and not other.is_symlink() and file_sha256(src) == file_sha256(other)
            ) else 'Destination already exists'
        # Warning does not implicitly delete the user's duplicate file.
        proposals.append({'original': original, 'src': src, 'dst': dst,
                          'category': category, 'suggested': suggested, 'method': method,
                          'sha256': f['sha256'], 'size': f['size'], 'mtime_ns': f['mtime_ns'],
                          'root': root,
                          'identity': f.get('identity'),
                          'categories': allowed,
                          'duplicate_count': hash_counts[f['sha256']], 'issue': problem})
    collisions = Counter(str(p['dst']).casefold() for p in proposals if p['issue'] is None)
    for p in proposals:
        if p['issue'] is None and collisions[str(p['dst']).casefold()] > 1:
            p['issue'] = 'Several proposals target the same filename'
    return proposals


def build_readonly_proposals(files, mode, root):
    """Describe rule-based possibilities without reading content or changing files."""
    root = validate_preview_folder(root)
    if mode not in MODES:
        raise ValueError('Invalid operating mode')
    proposals = []
    for f in files:
        original = f['filename']
        category = f['rule_category']
        src = root / original
        dst = root / original if mode == 'Rename only' or not category else root / category / original
        issue = 'Read-only preview' if category else 'Needs AI — unavailable in read-only mode'
        if category and mode == 'Rename only':
            issue = 'No rename suggested by rules'
        elif category and (dst.parent.is_symlink() or dst.parent.is_junction()):
            issue = 'Destination folder is a link or junction'
        elif category and existing_path_casefold(dst.parent, dst.name) is not None:
            issue = 'Destination already exists'
        proposals.append({'original': original, 'src': src, 'dst': dst, 'category': category,
                          'suggested': original, 'method': 'Python rules' if category else 'Needs AI',
                          'duplicate_count': 1, 'issue': issue})
    return proposals


def revalidate(proposal, root=None):
    src, dst = proposal['src'], proposal['dst']
    root = validate_operation_folder(ROOT if root is None else root)
    allowed = proposal.get('categories', CATEGORIES)
    if proposal.get('root') != root or not safe_source(src, root) or not safe_destination(dst, root, allowed):
        return False, 'Path or source changed'
    if not valid_filename(dst.name, src.name):
        return False, 'Invalid proposed filename'
    if existing_path_casefold(dst.parent, dst.name) is not None:
        return False, 'Destination already exists'
    stat = src.stat()
    if (stat.st_size != proposal['size'] or stat.st_mtime_ns != proposal['mtime_ns'] or
            file_sha256(src) != proposal['sha256']):
        return False, 'Source changed after preview'
    return True, 'OK'


def apply_proposals(proposals, root=None):
    # Test fixtures use exclusive hard link + unlink. External folders use a
    # locked Windows handle rename. Neither engine overwrites a destination.
    # A pending log row is written before filesystem operations. Pending needs human inspection.
    root = validate_operation_folder(ROOT if root is None else root)
    if history_pending():
        raise RuntimeError('An interrupted operation is pending. Inspect history before proceeding.')
    batch_id = str(uuid.uuid4())
    outcomes = []
    for p in proposals:
        if p['issue'] is not None:
            outcomes.append((p['original'], 'SKIPPED: ' + p['issue']))
            continue
        try:
            ok, reason = revalidate(p, root)
        except (OSError, ValueError) as exc:
            outcomes.append((p['original'], 'SKIPPED: Cannot verify file or folder: ' + str(exc)))
            continue
        if not ok:
            outcomes.append((p['original'], 'SKIPPED: ' + reason))
            continue
        opid = str(uuid.uuid4())
        history_insert(opid, batch_id, p['src'], p['dst'], p['sha256'])
        try:
            # External directory creation happens only inside the handle-locked
            # move engine, so a replaced root cannot redirect this write.
            if is_test_folder(root):
                p['dst'].parent.mkdir(parents=True, exist_ok=True)
            ok, reason = revalidate(p, root)
            if not ok:
                raise OSError(f'Safety check failed after preparing destination: {reason}')
            if is_test_folder(root):
                os.link(p['src'], p['dst'], follow_symlinks=False)
                p['src'].unlink()
            else:
                from .windows_moves import move_verified
                move_verified(p['src'], p['dst'], root, p['sha256'], p.get('identity'))
            history_set(opid, 'moved')
            outcomes.append((p['original'], 'MOVED → ' + str(p['dst'].relative_to(root))))
        except OSError as exc:
            history_set(opid, 'pending', 'Inspect both paths: ' + str(exc))
            outcomes.append((p['original'], 'CHECK MANUALLY: ' + str(exc)))
            break
    return outcomes


def undo_preview(root=None):
    root = validate_operation_folder(ROOT if root is None else root)
    if history_pending():
        raise RuntimeError('Pending operations need manual inspection before Undo.')
    with closing(history_connect()) as conn, conn:
        rows = conn.execute("SELECT batch_id, source FROM operations WHERE status='moved' "
                            "ORDER BY created_at DESC, rowid DESC").fetchall()
        batch = next((batch_id for batch_id, source in rows if Path(source).parent == root), None)
        if not batch:
            return None, []
        entries = conn.execute("SELECT id,source,destination,sha256 FROM operations "
                               "WHERE batch_id=? AND status='moved' ORDER BY rowid DESC",
                               (batch,)).fetchall()
    return batch, entries


def undo_last_batch(root=None, expected_batch=None):
    root = validate_operation_folder(ROOT if root is None else root)
    batch, entries = undo_preview(root)
    if expected_batch is not None and batch != expected_batch:
        raise RuntimeError('History changed after the Undo preview. Review it again.')
    if not batch:
        return [('History', 'No completed batch to undo')]
    outcomes = []
    for opid, source, destination, digest in entries:
        src, dst = Path(source), Path(destination)
        # History retains the original destination even if the user later edits categories.
        recorded_categories = (dst.parent.name,) if dst.parent != root else ()
        if (src.parent != root or not safe_destination(dst, root, recorded_categories) or
                src.exists() or src.is_symlink() or dst.is_symlink() or not dst.is_file()):
            outcomes.append((dst.name, 'SKIPPED: unsafe paths or existing original'))
            continue
        if file_sha256(dst) != digest:
            outcomes.append((dst.name, 'SKIPPED: content was modified'))
            continue
        try:
            # Record intent before changing either path, so a crash blocks later
            # operations until the two paths have been inspected.
            history_set(opid, 'pending', 'Undo in progress; inspect both paths if interrupted')
            if is_test_folder(root):
                os.link(dst, src, follow_symlinks=False)
                dst.unlink()
            else:
                from .windows_moves import move_verified
                move_verified(dst, src, root, digest)
            history_set(opid, 'undone')
            outcomes.append((dst.name, 'RESTORED → ' + src.name))
        except OSError as exc:
            history_set(opid, 'pending', 'Undo interrupted: ' + str(exc))
            outcomes.append((dst.name, 'CHECK MANUALLY: ' + str(exc)))
            break
    return outcomes

