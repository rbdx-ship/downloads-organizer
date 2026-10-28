# Hybrid Downloads Organizer — Project handoff

## Purpose
This project began as a practical AI-agents learning exercise alongside the Hugging Face AI Agents course. The goal is now to build a useful, local-first Windows file organizer that classifies and optionally renames and organizes downloads. The user wants to understand both the code and the tradeoffs between deterministic workflows and agent autonomy.

## Development environment
- Windows / PowerShell.
- Project directory: the root of this repository.
- Dedicated Python environment at `.venv/`.
- Jupyter used for initial experiments; the application now uses Python Tkinter.
- Ollama runs a local model. Earlier experiments used `qwen2:7b`, later `qwen2.5:7b` for improved tool calling; confirm the installed model in the current environment.
- SQLite stores classification results and later operation history.

## Current application (updated 2026-10-28)
- Launch `downloads_organizer.py` for the PySide6 interface; `downloads_organizer_tk.py` retains the prior Tkinter interface.
- Application services live in `organizer/`. Earlier notebooks and scripts are under `archive/`; the repaired Step 10 script is preserved in `tests/reference/` as a historical backup for the classification-policy comparison test.
- Shared databases are `classification_cache.db` and `operation_history.db`. The app copies legacy databases to the new names only when needed and preserves the originals.
- The PySide6 window lists the selected folder's files automatically, offers folder-specific categories, and classifies using Python rules plus Ollama. Classification cache validity includes the chosen category set.
- The primary action changes from Classify to Review & organize. Ready files are checked by default; a select-all control supports bulk operations. A scrollable review and explicit YES confirmation precede moves.
- Classification now requires confirmation with an approximate time range and rules/cache/unique-AI/duplicate counts. OpenAI excerpt/cost consent is included when needed. During AI batches, a QTimer updates elapsed and estimated remaining time, and actual batch completions advance the progress bar. Estimates adapt from successful provider/model-specific batch timings in memory for the session; initial ranges are rough heuristics, not measured guarantees. Overruns are explicit. Cancelling preserves the current preview and starts no worker. No classification/cache policy changes or new persistent timing data.
- Folder/category controls are grouped together, name editing is above the table, and Undo is separate in the footer. Details can be expanded; smaller windows use a compact layout.
- The app starts in `test-downloads`. The PySide6 folder picker now offers explicitly approved writable external folders on fixed local NTFS drives, or read-only preview. Typed YES is required to change folders, and each operation still requires review and YES. Writable approval is scoped to a folder identity for the app session. System/application/hidden folders, known cloud-sync locations, network/removable drives and links are excluded. Real Downloads remains blocked pending explicit authorization.
- External moves and Undo use Windows handles that deny concurrent source writes/deletion and directory replacement, verify file identity/content, and rename without overwriting. Test-folder operations retain the prior hard-link workflow. Shared database schemas and existing records are preserved. `tests/manual_external_workflow.py` exercises actual moves and folder-scoped Undo in a disposable sibling folder outside the project, with isolated test databases and automated dialog answers; no AI or personal files.
- Writable external target folders must have the configured final name, default `Downloads`, ignoring case and regardless of parent path. `Safety settings` changes that name only after a warning and typed YES; saving revokes existing approvals and clears suggestions. The developer test sandbox is exempt. Settings persist in ignored `safety_settings.json`; invalid settings fail closed for external writes. The rule does not unlock the real Windows Downloads location or other protected folders, and changing it does not alter databases or classification cache policy.
- Automated regression tests use disposable files and databases under `test-downloads`. `tests/manual_qt_workflow.py` exercises real Ollama, a real move, and Undo after recreating the window; its confirmations are automated.
- First-run setup now offers local Ollama, OpenAI, or rules-only mode. Provider settings are stored in ignored `ai_settings.json`; API keys use Windows Credential Manager. AI settings can be changed from the window header. Direct construction of the test window defaults to local Ollama for test compatibility; the public launcher loads settings or prompts first.
- Local setup detects installed models, guides official signed Windows installation, downloads models with progress/cancellation, and tests structured output using synthetic text. Local inference verifies model metadata and rejects remote/cloud Ollama models.
- OpenAI uses the official endpoint and structured Responses output with response storage disabled. Users consent to each document-classification run; setup uses sample text only. Provider/model/adapter identities partition caches without deleting existing results. No cloud fallback is automatic.
- Source checkouts keep existing data in the project; packaged builds use LocalAppData. The default test folder is created on normal startup when missing.

## What we built, in order
1. Filesystem scanner via `pathlib`: list filenames, extensions and sizes.
2. Local Ollama connection and structured classification into categories.
3. Approval-based file-moving prototype restricted to `test-downloads/`.
4. Jupyter `ipywidgets` interface for selecting files, executing approved changes and Undo.
5. An LLM tool-calling learning experiment with `list_test_files`, `classify_test_file` and `propose_move`. This was educational; the production direction is a hybrid deterministic pipeline rather than an agent call for every file.
6. Hybrid scanning: extension/keyword rules handle obvious cases; limited content extraction (PDF via PyMuPDF, Word via python-docx, text files) and batched Ollama classify the rest.
7. SQLite result caching to avoid repeated LLM inference. An important bug was found: the model returned proposed names in the `filename` field, breaking exact-name matching. We switched to stable numeric `file_id` references in batch responses.
8. Policy-aware caching so taxonomy and prompt changes invalidate stale results; proposed automatic SHA-256 policy fingerprints. A new category (Arts & Crafts) was a motivating example. Confirm that running code uses the same policy construction and model configuration consistently.
9. Jupyter safe Rename + Organize, with filename validation, conflict checks, SHA-256 integrity verification, approval, logs and Undo.
10. Persistent Undo and duplicate detection in the notebook, then a Tkinter desktop application.
11. Content-hash cache improvement: exact duplicate document bytes can reuse one AI classification/naming suggestion despite different source paths.
12. Desktop GUI iteration to expose scanning, Ollama analysis, preview, approved moves and persistent Undo.

## Known bugs encountered and lessons
- Jupyter widgets showed `VBox(...)` text rather than controls until widget support/environment was corrected.
- Earlier category folder validation incorrectly reused a filename validation function, causing every file to be marked 'unsafe category'. Validate folder names separately.
- An earlier app version rendered no results table because Tkinter `Treeview` was positioned in the wrong parent container.
- Preview initially only refreshed the table and did not visibly signal success; a summary popup was added.
- The first preview-popup patch accidentally nested the `analyze()` method incorrectly and produced `AttributeError: 'OrganizerApp' object has no attribute 'analyze'`. A repaired version was supplied. Pay extra attention to GUI class method scope/indentation, and test component construction.
- Buttons in Jupyter needed callbacks attached to the current widget instances.
- Cache keying by path caused identical copied files to be reanalyzed and sometimes receive different names; moving toward SHA-256 content-based cache fixed the conceptual issue.
- Changes to categories/prompts must invalidate stale AI cache entries, but not necessarily rerun deterministic classification for all unchanged content.

## Status when leaving ChatGPT tutorial
- The most recently supplied application was named `downloads_organizer_app_step10_part2_repaired.py`. Treat it as a candidate starting point, **not** automatically as verified working software; inspect and run tests locally.
- Intended features: Tkinter file table, Scan, Analyze with Ollama, Preview, Rename + Organize / Organize only / Rename only, approved actions, persistent Undo, SHA-256 duplicate detection, SQLite caching and history.
- Safe default is test-folder-only. Do not access or modify real Downloads without review and explicit user approval.
- The user had not yet confirmed the final repaired version's full end-to-end functionality.

## Existing data and expected file types
- Test PDFs named `document_001.pdf` through `document_005.pdf` represent a scientist job application, electricity invoice, CRISPR scientific review, lab automation notes and Python course material. Their names are ambiguous so content extraction should trigger LLM classification.
- Additional dummy examples include CVs, invoices, tutorials, images and installer files. Some test files use placeholder bytes and are not valid PDFs or executables.
- Current example categories: Career, Finance, Learning, Images, Software, Other, and later Arts & Crafts and possibly Household. Read current code as authoritative.
- Historical databases include `organizer_cache.db`, `step10_operations.db` and sometimes `step9` operation history. Do not overwrite or migrate them without backup.

## Architecture decisions
- The performance experiment with 13 test files showed 8 classified by Python and 5 sent to Ollama; the AI batch took 64.8 seconds. This motivated selective inference and caching.
- A cache lookup should use source integrity and policy/model identification. Recognizing identical bytes by SHA-256 allows reuse, while filename collisions and duplicate files still require human judgment.
- AI-generated filenames are *suggestions*. They should be checked for unsupported claims, Windows-invalid characters, unchanged extensions and collisions.
- Prefer strong separation between scanner, classifier, extraction, cache, file operations, and UI. Keep file-changing actions independent from AI output until explicit approval.

## Near-term roadmap
**Step 11:** Stabilize then refactor the monolithic Windows app into small, testable modules. Preserve behavior and databases.
**Step 12:** Add pytest regression tests for rules, cache keying, policy updates, duplication, safe movement and Undo.
**Step 13:** Improve interface with responsive progress, clear preview, per-file corrections and error explanations.
**Step 14:** Add optional real Downloads location with read-only scan/dry-run and explicit approvals.
**Step 15:** Package for Windows (e.g. PyInstaller) after testing.
**Step 16:** Add limited agent-driven investigation for files that deterministic tools cannot interpret, without giving it uncontrolled move/delete authority.

## Working instructions for a new Codex session
Read `AGENTS.md`, this context document, the latest application file and any current tests. Describe the current architecture and identify discrepancies between intended and implemented functionality. Run non-destructive checks first. Then propose a safe incremental Step 11 refactor that preserves the test-folder restriction, SQLite data and UI functionality. Explain changes in clear teaching language.

## Optional previous-chat archival
A copy of the full ChatGPT conversation may be stored separately for archival reference. It is not a substitute for accurate source-code inspection, tests, or these maintained project documents.
