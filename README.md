# tl

A minimal desktop translator built with PySide6. Type source text on the left, pick source/target languages, and the tool streams translations into the right pane via the OpenAI API (defaults to `gpt-4o-mini`). It keeps a searchable, newest-first history sidebar and lives in the system tray so you can hide/show it quickly while working in other apps. Settings/history are stored in the Qt `applicationDirPath` (same directory as the app executable; when running via `uv run` that’s the uv shim dir).

<img width="751" height="444" alt="image" src="https://github.com/user-attachments/assets/ca6f9c90-0054-4364-91fc-54ae24fc1cd7" />

## Setup

Requirements: Python 3.12+, `uv`, and an `OPENAI_API_KEY` in your environment. The app writes runtime settings/history next to the binary (no repo-stored state).

### Run with uv

```
uv run tl
```

### Install with uv

```
uv tool install . -e
```

Then run with `tl`.
