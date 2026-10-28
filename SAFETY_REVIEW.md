# Folder selection safety review

The application permits file changes only in `test-downloads` and its unlinked
subfolders. Other eligible folders are read-only: the app lists immediate files
and uses filename rules to show possible destinations. It does not hash or
extract file contents, call Ollama, save classification results, rename, move,
or undo in read-only mode. The Windows Downloads folder and its subfolders are
blocked until a separate review and explicit authorization. If its configured
location cannot be verified, external folder selection fails closed.

Before applying a test-folder operation, the app requires a preview and explicit
confirmation, then verifies the folder, source identity, name, destination and
collisions. It rechecks after creating the destination folder. Operation history
records intent before changes; interrupted operations block later operations and
show the recorded paths. Undo checks the recorded hash and is scoped to the
selected test folder. Existing history and cache schemas are unchanged.

Tests use disposable test files and databases. Read-only mode, folder-specific
Undo, collisions, changed files, link checks and failed operations have
regression coverage. No real Downloads folder has been scanned as part of this
review.

AI setup is explicit and separate from folder selection. OpenAI receives only
limited extracted text, filenames when text is unavailable, extensions, numeric
IDs and the category list after per-run consent. It uses a fixed official API
endpoint and response storage is disabled; this does not eliminate provider
abuse-monitoring retention. Keys use Windows Credential Manager rather than
settings/SQLite. Local Ollama inference checks model metadata before sending
document text and rejects cloud/remote models. No provider fallback is automatic.
Setup tests use synthetic text. Installer execution is gated by an explicit
user action, an official HTTPS download allowlist and a valid Ollama publisher
signature. Model downloads and installer downloads can be cancelled before
execution; a launched interactive Windows installer must finish or be cancelled
in its own window.

Remaining limitation: checks and filesystem changes are separate system calls,
so another process could change paths or files between them. The present design
does not provide atomic protection against a malicious concurrent process.
This must be addressed before enabling writes outside the test folder. Also,
large scans currently run on the UI thread, and a file that changes while being
listed may need another scan. Review all suggestions: filename rules can be
wrong, and read-only preview intentionally does not analyze document content.
