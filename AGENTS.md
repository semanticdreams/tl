# Repository Guidelines

## Project Structure & Module Organization
- Entry point stays `tl/main.py` (exports `main`), while UI/logic is split across modules: `tl/window.py` (MainWindow + UI), `tl/backends.py`, `tl/persistence.py`, `tl/history.py`, `tl/worker.py`, `tl/widgets.py`, `tl/languages.py`, `tl/models.py`, `tl/constants.py`, and `tl/resources.py`; GUI assets live in `tl/assets/` (e.g., `icon.png`). The package exposes an entrypoint `tl.main:main` and installs a `tl` console script.
- Persistent user data is written at runtime to the Qt `applicationDirPath` (same directory as the binary when packaged), using `settings.json` and `history.jsonl`. No repo-stored state should be committed.
- `pyproject.toml` declares dependencies (PySide6, OpenAI SDK) and the script entry. `uv.lock` pins versions for repeatable installs.

## Build, Test, and Development Commands
- Install the tool locally with editable support:
  ```bash
  uv tool install . -e
  ```
- Run the app directly (requires GUI environment and `OPENAI_API_KEY`):
  ```bash
  uv run tl
  ```
- Package/entrypoint check:
  ```bash
  uv run python -m tl.main
  ```
- No formal test suite exists yet; rely on manual checks (launch UI, translate, verify history persistence).

## Coding Style & Naming Conventions
- Python 3.12+, PEP 8 defaults; prefer 4-space indentation and descriptive names for UI elements (`src_lang`, `history_model`, etc.).
- Keep module-level constants uppercase (e.g., `DEBOUNCE_MS`, `OPENAI_TRANSLATION_MODEL`). Dataclasses are used for records (`TranslationRecord`, `TranslateJob`).
- UI structure favors small helpers (`SearchableComboBox`, `Persistence`); add comments for non-obvious behaviors (coalesced jobs, debouncing).
- Avoid introducing new global state; route user data through `Persistence`.

## Testing Guidelines
- Manual QA focus:
  - Launch: `uv run tl`; confirm tray icon, show/hide works.
  - Translation: edit source text; ensure debounce triggers, target updates, and history item appears newest-first.
  - Error handling: unset `OPENAI_API_KEY` to confirm graceful status message, not a crash.
- When adding tests later, follow `tests/test_*.py` naming and prefer pytest; mock network-bound OpenAI calls.

## Commit & Pull Request Guidelines
- Commit messages: present tense, concise summary of the change (e.g., `Improve debounced translation scheduling`). Avoid bundling unrelated changes.
- PRs should include: purpose, key behavior changes, testing done (manual steps or commands), and any UI screenshots if relevant to the tray or main window.
- Link issues when applicable; call out risk areas (translation threading, persistence formats) and rollback steps.

## Security & Configuration Tips
- Secrets: set `OPENAI_API_KEY` in your environment; do not commit it or write it to history files.
- Network calls are limited to the OpenAI client; validate new backends for key management and error handling before enabling.
