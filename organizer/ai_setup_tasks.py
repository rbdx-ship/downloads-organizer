"""Background setup tasks; installation occurs only after an explicit UI action."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

import httpx
from pydantic import BaseModel

from .config import PROJECT
from . import providers

INSTALLER_URL = 'https://ollama.com/download/OllamaSetup.exe'


class Cancelled(RuntimeError):
    pass


class ProbeResult(BaseModel):
    file_id: int
    category: str
    suggested_name: str
    reason: str


class ProbeResults(BaseModel):
    results: list[ProbeResult]


def hardware_summary():
    import psutil
    location = Path(os.environ.get('OLLAMA_MODELS', str(Path.home() / '.ollama' / 'models')))
    while not location.exists() and location != location.parent:
        location = location.parent
    free = shutil.disk_usage(location).free / 1024**3
    memory = psutil.virtual_memory().total / 1024**3
    return f'{memory:.1f} GB system RAM · {free:.1f} GB free on the model storage drive. Model downloads may need several GB; size appears during download.'


def detect_ollama():
    with httpx.Client(base_url=providers.OLLAMA_HOST, timeout=5, trust_env=False) as client:
        response = client.get('/api/tags')
        response.raise_for_status()
        entries = response.json()['models']
    return [entry.get('model') or entry['name'] for entry in entries
            if not entry.get('remote_host') and not entry.get('remote_model')
            and not (entry.get('model') or entry.get('name', '')).lower().endswith('cloud')]


def pull_model(model, progress, cancel):
    stream = providers.ollama_client(timeout=30).pull(model=model, stream=True)
    layers, success = {}, False
    try:
        for event in stream:
            if cancel.is_set():
                raise Cancelled('Model download cancelled. Download again to resume stored layers.')
            digest, total = getattr(event, 'digest', None), getattr(event, 'total', None)
            if digest and total:
                layers[digest] = (total, getattr(event, 'completed', 0) or 0)
            total_bytes = sum(value[0] for value in layers.values())
            completed = sum(value[1] for value in layers.values())
            percent = min(99, int(100 * completed / total_bytes)) if total_bytes else -1
            description = event.status
            if total_bytes:
                description += f' · {completed / 1024**3:.2f} / {total_bytes / 1024**3:.2f} GB (announced layers)'
            progress(description, percent)
            if event.status == 'success':
                success = True
        if not success:
            raise RuntimeError('Download ended before Ollama confirmed success. Try downloading again.')
        progress('Model download complete. Test the connection next.', 100)
        return 'Model downloaded. Click Test model to verify structured classification.'
    finally:
        close = getattr(stream, 'close', None)
        if close:
            close()


def test_config(config, api_key=None):
    # Never use personal files for setup, including cloud connection tests.
    sample = [{'file_id': 0, 'original_filename': '', 'extension': '.txt',
               'content_excerpt': 'A beginner tutorial for learning Python functions.'}]
    result = providers.classify(sample, ProbeResults, ('Learning', 'Other'), config, api_key)
    from .file_manager import valid_filename
    if (len(result.results) != 1 or result.results[0].file_id != 0
            or result.results[0].category not in ('Learning', 'Other')
            or not valid_filename(result.results[0].suggested_name, 'sample.txt')):
        raise RuntimeError('The model did not return the expected structured classification.')
    return 'Connection and structured classification test passed using sample text.'


def verify_ollama_signature(path):
    # The executable path is passed through an environment variable, never shell text.
    environment = dict(os.environ, ORGANIZER_INSTALLER_PATH=str(path))
    command = ("$s = Get-AuthenticodeSignature -LiteralPath $env:ORGANIZER_INSTALLER_PATH; "
               "if ($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'Ollama') { exit 1 }; exit 0")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                            env=environment, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
                            timeout=60)
    if result.returncode != 0:
        raise RuntimeError('Ollama publisher signature could not be verified. Use the official download page to install manually.')


def start_ollama():
    try:
        detect_ollama()
        return 'Ollama is already running. Check installation to list models.'
    except Exception:
        pass
    install = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Programs' / 'Ollama'
    candidates = [install / 'ollama app.exe', install / 'ollama.exe']
    for candidate in candidates:
        if candidate.is_file():
            verify_ollama_signature(candidate)
            arguments = [str(candidate)] + (['serve'] if candidate.name == 'ollama.exe' else [])
            subprocess.Popen(arguments, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=subprocess.CREATE_NO_WINDOW)
            return 'Ollama was started. Wait a moment, then click Check installation.'
    raise RuntimeError('Ollama was not found in its standard installation folder. Install it or start it from the Windows Start menu.')


def install_ollama(progress, cancel):
    target = PROJECT / 'setup-downloads'
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target, prefix='ollama-', ignore_cleanup_errors=True) as temporary:
        path = Path(temporary) / 'OllamaSetup.exe'
        with httpx.stream('GET', INSTALLER_URL, follow_redirects=True, trust_env=False, timeout=30) as response:
            response.raise_for_status()
            allowed_hosts = {'ollama.com', 'github.com', 'objects.githubusercontent.com',
                             'release-assets.githubusercontent.com'}
            for item in (*response.history, response):
                if item.url.scheme != 'https' or item.url.host not in allowed_hosts:
                    raise RuntimeError('Unexpected installer download location. Use the official download page.')
            total = int(response.headers.get('Content-Length', 0))
            if total and shutil.disk_usage(target).free < total + 256 * 1024**2:
                raise RuntimeError('Not enough free space to download the Ollama installer. Free disk space or install it manually on another drive.')
            completed = 0
            with path.open('xb') as output:
                for chunk in response.iter_bytes():
                    if cancel.is_set():
                        raise Cancelled('Installer download cancelled.')
                    output.write(chunk)
                    completed += len(chunk)
                    progress(f'Downloading official Ollama installer · {completed / 1024**2:.1f} MB',
                             int(100 * completed / total) if total else -1)
        if cancel.is_set():
            raise Cancelled('Installation cancelled before launch.')
        progress('Verifying the official Ollama publisher signature…', -1)
        verify_ollama_signature(path)
        if cancel.is_set():
            raise Cancelled('Installation cancelled before launch.')
        progress('Complete the Ollama Windows installer in its window. This app will wait.', -1)
        # Interactive installer intentionally opens its own window.
        result = subprocess.run([str(path)], check=False)
        if result.returncode != 0:
            raise RuntimeError('The Ollama installer was cancelled or did not complete. You can try again.')
    return 'Installer finished. Start Ollama, then click Check installation.'
