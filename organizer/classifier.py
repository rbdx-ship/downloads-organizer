from __future__ import annotations
import re
import json
from pathlib import Path
from .config import *
from .file_identity import file_sha256

def rule_classify(filename: str) -> str | None:
    path = Path(filename)
    if path.suffix.lower() in EXTENSION_RULES:
        return EXTENSION_RULES[path.suffix.lower()]
    words = ' ' + re.sub(r'[_\-.]+', ' ', path.stem.lower()) + ' '
    matches = {category for category, keywords in KEYWORD_RULES.items()
               if any(f' {keyword} ' in words for keyword in keywords)}
    return next(iter(matches)) if len(matches) == 1 else None


def scan(root=None):
    root = validate_test_folder(ROOT if root is None else root)
    if not root.is_dir():
        raise FileNotFoundError(f'Test folder not found: {root}')
    out = []
    for p in sorted(root.iterdir()):
        if not p.is_file() or p.is_symlink():
            continue
        stat = p.stat()
        out.append({'filename': p.name, 'path': str(p), 'extension': p.suffix.lower(),
                    'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns,
                    'rule_category': rule_classify(p.name), 'sha256': file_sha256(p)})
    return out


def scan_readonly(root):
    """Read names and metadata only; no hashing, extraction or cache writes."""
    root = validate_preview_folder(root)
    files, skipped = [], []
    for path in sorted(root.iterdir()):
        try:
            if path.is_symlink() or not path.is_file():
                continue
            stat = path.stat()
            files.append({'filename': path.name, 'path': str(path),
                          'extension': path.suffix.lower(), 'size': stat.st_size,
                          'mtime_ns': stat.st_mtime_ns, 'rule_category': rule_classify(path.name)})
        except OSError as exc:
            skipped.append(f'{path.name}: {exc}')
    return files, skipped


def extract_content(path: Path, limit=1200, warnings=None):
    try:
        if path.suffix.lower() == '.pdf':
            import pymupdf
            with pymupdf.open(path) as doc:
                return ' '.join(doc[i].get_text() for i in range(min(2, len(doc))))[:limit]
        if path.suffix.lower() == '.docx':
            from docx import Document
            return ' '.join(p.text for p in Document(path).paragraphs)[:limit]
        if path.suffix.lower() in {'.txt', '.md'}:
            return path.read_text(encoding='utf-8', errors='replace')[:limit]
    except Exception as exc:
        if warnings is not None:
            warnings.append(f'{path.name}: could not read document text ({exc}). '
                            'AI will use the filename instead; review its suggestion carefully.')
    return ''


def analyze_files(files, warnings=None, categories=None, ai_config=None):
    """One batched AI call for a small group of ambiguous files."""
    if ai_config is not None and ai_config.provider == 'rules':
        return {}
    import ollama
    from pydantic import BaseModel

    class Result(BaseModel):
        file_id: int
        category: str
        suggested_name: str
        reason: str

    class Results(BaseModel):
        results: list[Result]

    allowed = CATEGORIES if categories is None else categories
    payload = []
    for i, f in enumerate(files):
        content = extract_content(Path(f['path']), warnings=warnings)
        payload.append({'file_id': i,
                        'original_filename': '' if content.strip() else f['filename'],
                        'extension': f['extension'], 'content_excerpt': content})
    if ai_config is None:
        response = ollama.chat(model=MODEL, messages=[
            {'role': 'system', 'content': AI_INSTRUCTIONS + '\nAllowed categories: ' + ', '.join(allowed)},
            {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}
        ], format=Results.model_json_schema(), options={'temperature': 0})
        parsed = Results.model_validate_json(response.message.content).results
    else:
        from .providers import classify
        parsed = classify(payload, Results, allowed, ai_config).results
    output = {}
    counts = {}
    for item in parsed:
        counts[item.file_id] = counts.get(item.file_id, 0) + 1
    for item in parsed:
        i = item.file_id
        if (not isinstance(i, int) or not 0 <= i < len(files) or
                counts[i] != 1 or item.category not in allowed):
            continue
        f = files[i]
        if (not item.suggested_name or Path(item.suggested_name).name != item.suggested_name
                or Path(item.suggested_name).suffix.lower() != f['extension']):
            continue
        output[f['filename']] = {'category': item.category,
                                 'suggested_name': item.suggested_name, 'reason': item.reason}
    return output


def analysis_error_message(exc):
    """Turn common local model errors into useful next steps."""
    import httpx
    import ollama
    if isinstance(exc, (httpx.ConnectError, ConnectionError)):
        return 'Cannot connect to Ollama. Start Ollama and try again.'
    if isinstance(exc, ollama.ResponseError) and exc.status_code == 404:
        return f'Ollama could not find model {MODEL}. Check installed models with `ollama list` and install or configure the model.'
    return f'Analysis failed: {exc}. Check Ollama and try again.'

