# tl

A minimal desktop translator built with PySide6. Type source text on the left, pick source/target languages, and the tool streams translations into the right pane via the OpenAI API (defaults to `gpt-4o-mini`). It keeps a newest-first history sidebar and lives in the system tray so you can hide/show it quickly while working in other apps. Settings/history are stored in Qt's `AppDataLocation`.

<img width="751" height="444" alt="image" src="https://github.com/user-attachments/assets/ca6f9c90-0054-4364-91fc-54ae24fc1cd7" />

## Setup

Requirements: Python 3.12+ and `uv`.

### Run with uv

```
uv run tl
```

### Install with uv

```
uv tool install . -e
```

Then run with `tl`.
