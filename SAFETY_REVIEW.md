# Folder selection safety review

## Real Downloads review, 2026-10-28

The user requested access to their Windows Downloads folder. The first selection
now opens a read-only filename-rule preview. A successful preview records that
folder's device and file identity in memory; only then can a second selection of
the same folder offer writable access, followed by typed YES. The regular list
of proposed moves and separate YES confirmation remain mandatory. Permission and
preview are session-only. The backend refuses to authorize real Downloads if the
preview is missing or the folder identity changed. The Windows Downloads registry
location must be readable, and all external-folder restrictions, including local
fixed NTFS, name rule, links, protected trees and cloud-sync exclusions still
apply. Existing collision, content identity, pending history and Undo checks
remain in force. Simulated Downloads paths and disposable fixtures are used for
tests; no personal Downloads files were read or changed during this review.

Popup backgrounds and text use explicit light/dark colors. A Qt message box was
rendered and visually checked. AI setup and text-entry dialogs use the same
contrast rules.

The historical description below records the earlier review; references to the
real Downloads folder being blocked are superseded by the review above.

Review updated 2026-10-28 for explicitly selected external data folders.

The app starts in `test-downloads`. In the PySide6 interface, eligible external
folders can now be approved for classification, renaming/moving and Undo. The
folder picker offers Yes (writable), No (read-only, the default), or Cancel.
Switching requires a warning and exact typed `YES`; applying operations still
requires the full change list followed by a separate typed `YES`. Approval is
held in memory for one session and bound to the folder's volume/file identity.
Deleting/replacing the approved folder invalidates permission. Approval is not
recursive and is not persisted on disk. Existing categories/history remain
available when the same folder is explicitly approved on a later launch.

An additional folder-name guard now requires external writable targets to have
the final directory name `Downloads` by default, ignoring case. This is the
selected working folder, not a requirement on category subfolders. The rule is
enforced in the backend external-folder validator, including authorization,
classification, proposal revalidation, moves, categories and Undo. Folder names
elsewhere in the parent path do not qualify. The internal test sandbox is exempt.
`Safety settings` changes the name after a warning and exact typed YES. The saved
name is validated as one Windows folder component and written atomically to
ignored `safety_settings.json`; corrupt or unreadable settings block external
writes. Successful saves revoke all session approvals and clear the current
window's suggestions; an external selection becomes read-only until approved
again. Other windows' proposals cannot bypass backend permission checks. Changing
the setting neither renames folders nor alters databases/cache keys. Undo in a
folder with the old name requires restoring that setting and reapproving it.
This extra condition does not authorize the real Downloads folder or remove
any path, drive, link, confirmation or file-identity protections.

Writable external folders require a fixed local NTFS drive. Drive roots, the
home directory and its ancestors, the app checkout and its ancestors/descendants,
system/application data trees, hidden directories, known OneDrive locations,
network/removable drives, symlinks and junctions are excluded. Other Windows
reparse points are rejected by the locked move engine. This intentionally limits
the first release of external-folder support. Legacy Tkinter remains a test-folder
development fallback and does not offer writable external-folder selection.

Read-only mode lists immediate files and uses filename rules without hashing,
content extraction, AI calls, cache writes, changes or Undo. The real Windows
Downloads folder and its subfolders remain blocked. If the Windows Downloads
location cannot be verified, external selection fails closed.

Before applying an operation, the app requires a preview and explicit
confirmation, then verifies the folder, source identity, name, destination and
collisions. It rechecks after creating the destination folder. Operation history
records intent before changes; interrupted operations block later operations and
show the recorded paths. Undo checks the recorded hash and is scoped to the
selected folder. Existing history and cache schemas are unchanged.

External operations use `organizer/windows_moves.py`: directory handles are
opened from the drive root downward without delete sharing, preventing ordinary
concurrent directory replacement while paths are in use. Category directories
are created only inside this protection. The source is opened with read/delete
access and read sharing only, rejecting existing conflicting writers and blocking
new writes/deletion during verification and rename. The opened path, file
identity, size, modification time and SHA-256 are verified; source hard links and
reparse points are rejected. Undo verifies recorded content on its locked handle.
`SetFileInformationByHandle` renames that same source handle without the replace
flag. A destination created after collision checking causes an error rather than
an overwrite. There is no copy/delete or cross-volume fallback. Open files,
permission failures and unsupported operations stop conservatively with an
actionable error and a pending history entry for inspection.

The prior test-folder hard-link engine is retained for compatibility and does
not provide the same concurrency protection. It must remain restricted to test
fixtures. Classification policy/cache fingerprints are unchanged by this work.

Tests use disposable test files and databases. Read-only mode, folder-specific
Undo, collisions, changed files, link checks and failed operations have
regression coverage. New tests exercise real handle-based moves and Undo,
concurrent source writes and directory renames, racing destination creation,
open-writer conflicts, replaced source identity, modified Undo content, Unicode
filename preservation and all three organization modes. Permission failures and
UI confirmations also have mocked coverage. The opt-in external smoke test
actually created two disposable folders outside the checkout, used one isolated
history database and separate categories, and successfully classified via Python,
reviewed, moved, reopened the window and undid each folder's batch independently.
Its dialog answers were automated. Cache reuse and category-policy isolation
were tested using synthetic stored results. No personal files, real Downloads,
existing databases, live AI requests or installation tasks were used.

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

Remaining limits: Windows handle protections address ordinary competing file
operations, not kernel-level interference or every filesystem/filter-driver
behavior. Content may be read during scanning/classification before move-time
locks are acquired; changed files are rechecked before moving. Known cloud-sync
locations are blocked, but third-party sync services cannot all be detected;
choose a dedicated unsynced folder. A successful rename followed by a database
failure or crash leaves pending history requiring manual inspection. No automatic
recovery/deletion is attempted. Large scans still run on the UI thread. Folder
permission checks cannot guarantee later success; actual Windows access checks
are authoritative. Review suggestions and keep backups of important files.

Win32 implementation references:
[CreateFile sharing modes](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew),
[FILE_RENAME_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_rename_info),
[SetFileInformationByHandle](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-setfileinformationbyhandle).
