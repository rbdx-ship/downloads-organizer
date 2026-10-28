from __future__ import annotations
import hashlib
from pathlib import Path

def file_sha256(path: Path) -> str:
    'Hash file bytes in chunks, without loading the whole file into memory.'
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

