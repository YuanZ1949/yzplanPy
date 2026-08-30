# YZplan

A Windows desktop application built with PySide6 / PyQt-Fluent-Widgets. The home page uses a "vertical card list" component panel: cards never overlap, can be moved up/down, resized freely, and the layout is persisted automatically. A Fluent-style shell provides home, modules, settings, and about pages together with a global tray icon.

> 中文说明见 [README.md](README.md)

## Features

- **Home component panel**: vertical card list
  - Cards **never overlap**; title bar provides `Move Up` / `Move Down` / `Remove`
  - Component width/height resized steplessly via drag handles; order and size are persisted across restarts
  - Add component, restore default order, clear layout
- **System Info module**: CPU / memory / disk, etc.
- **Path Forward module**: quickly open common paths
- **RSS Aggregator module**
  - Feed fetching, reading, **notifications** and auto refresh
  - **Multi-tag** categorization with a tag filter dropdown
  - **Aggregations (groups)**: source badge expand/collapse, one-click select-all, batch actions (mark read/unread/delete)
  - Lightweight item list (no images); preview area shows a **summary** (title/tags/updated/description)
- **Fluent-style theming**: light / dark / follow system theme switching, wallpaper background and acrylic (blur) effect
- Main window **screen-adaptive** initial size/position; minimize to tray on close, auto-start, global hotkeys

## Requirements

- Windows
- Python 3.11+ (64-bit)

## Setup

```bat
:: Create a virtual environment in the project root
python -m venv .venv

:: Activate it
.venv\Scripts\activate

:: Install dependencies
pip install -r requirements.txt
```

## Run

```bat
run.bat
```

or:

```bat
.venv\Scripts\python main.py
```

On first run, the `data/` directory is created automatically (containing `settings.json`, `app.db`, `logs/`, etc.).

## Tests

```bat
.venv\Scripts\python -m pytest
```

Or run the smoke test:

```bat
.venv\Scripts\python smoke_test.py
```

## Build Executable

Uses PyInstaller (onedir mode):

```bat
build.bat
```

> **Recommended**: create the virtual environment with the standard python.org CPython (64-bit),
> i.e. `python -m venv .venv` then `pip install -r requirements.txt`. `requirements.txt` only
> contains standard pip packages and has no anaconda dependency, so it installs and builds cleanly
> on any standard CPython environment.

`yzplan.spec` auto-adapts to both environments — no environment variables are required:

- **Standard CPython venv**: PyInstaller collects every compiled extension and native DLL itself;
  just build.
- **conda / anaconda venv**: the spec auto-detects the conda base and bundles the stdlib extension
  modules (`_ctypes.pyd`, etc.) together with `sqlite3.dll`, `libssl`/`libcrypto`, etc. from
  `Library\bin`, avoiding `DLL load failed while importing _ctypes` in the frozen app.

If auto-detection ever misfires, point the conda root manually:

```bat
set YZPLAN_CONDA_ROOT=C:\path\to\your\anaconda3
build.bat
```

## Directory Layout

```
.
├─ main.py            # Entry point
├─ core/              # Core: config, theme, tray, single-instance, logging, etc.
├─ ui/                # UI: main window, tabs
├─ modules/           # Feature modules
├─ tests/             # Unit tests
├─ data/              # Runtime data (not committed)
├─ requirements.txt   # Dependencies
├─ yzplan.spec        # PyInstaller build config
└─ build.bat / run.bat
```

## Notes

- `data/`, `.venv/`, `build/`, `dist/`, etc. are locally generated and excluded via `.gitignore`; they are not committed.
- Personal config (e.g. wallpaper path) and RSS data live under `data/` and are not synced with the repository.

## License

GPL-3.0, see [LICENSE](LICENSE).
