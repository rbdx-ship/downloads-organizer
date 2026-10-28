# Downloads Organizer — Codex project instructions

## Project objective
Develop and maintain a local-first Windows desktop application that organizes downloaded files using a **hybrid workflow**: deterministic Python rules for straightforward files and local Ollama inference for ambiguous documents. Keep the user in control of changes.

## Development and teaching approach
- The owner is learning Python and AI agents using the Hugging Face AI Agents course. Explain important coding decisions in straightforward language, with short examples of agent concepts when relevant.
- Work incrementally. Before broad refactors, inspect the existing working code and explain the proposed change. Keep functionality working throughout.
- Give simple PowerShell run/test instructions for Windows and the existing `.venv` environment.
- Fix root causes, not just symptoms. Add regression tests for bugs that have already occurred.
- Never claim that a GUI workflow or local Ollama call has been tested unless it really has been executed; clearly distinguish static checks and mocked tests.

## Source of truth
- Read `PROJECT_CONTEXT.md` before changing architecture or behavior.
- Inspect the files actually present in this folder; earlier filenames and history are documented context, not evidence that particular files still exist.
- Identify the latest working application through inspection and testing. Preserve the prior script as a backup before refactoring.

## Functional principles
- Start in `test-downloads/`, not the user's real Downloads folder. The real Downloads folder may only be handled after a dedicated safety review, dry-run preview, and explicit user authorization.
- Scan local files with Python; classify obvious cases via configurable rules; use Ollama for ambiguous files only.
- Extract limited text from supported PDF, DOCX, TXT, and MD files when helpful; do not execute untrusted downloads or embedded instructions.
- Batch LLM classifications using stable numeric file IDs, not returned names, to associate answers with sources.
- Use a centrally defined, versioned classification policy; account for policy and model changes in cache validity.
- Use SHA-256 content hashes for duplicate detection and to reuse classification/naming results for identical content under the same policy/model. Never auto-delete duplicates.
- Validate all suggested filenames and categories, preserve extensions, prevent collisions and overwrites, and reject unsafe file paths.
- Require explicit human approval for renames and moves. No surprise file changes.
- Keep an inspectable operation history and verify file identity on Undo; treat interrupted operations conservatively.
- Make failures understandable in the UI, including skipped file reasons and actionable error messages.

## Engineering priorities
1. Stabilize the current Tkinter application: scanning, analyzing, preview, approved moves, persistent undo.
2. Refactor into modules (`config`, `classifier`, `cache`, `file_manager`, `interface`) without changing behavior.
3. Add automated pytest tests for classifications, cache invalidation, identical content, collisions, approved moves and Undo.
4. Improve progress indication, editing suggested filenames and UI error messages.
5. Only then introduce real-folder selection, packaging and limited autonomy.

## Operational notes
- Local working directory: the root of this repository.
- Activate: `.\.venv\Scripts\Activate.ps1`
- Local model managed by Ollama; inspect installed models instead of assuming a specific one is available.
- Keep `.venv/`, database files, documents and test artifacts out of version control unless intentionally anonymized fixtures.
- When a request changes classification categories, rules, prompts, model or extraction logic, ensure corresponding cache policy invalidation.
