# YZplan

A Windows desktop application built with PySide6 / PyQt-Fluent-Widgets. The home page uses a "canvas-style" component panel: components can be freely dragged, resized steplessly by dragging, and reordered by dragging. The flow layout adapts automatically to the window width, and rows with a high fill ratio stretch to fill the full width (no blank space on the right side).

> 中文说明见 [README.md](README.md)

## Features

- **Home component panel**: adaptive flow layout
  - Drag components to move; drag to swap order (**only when dragging** — clicking buttons never triggers reordering)
  - Component width/height resized steplessly via drag handles; sizes are persisted across restarts
  - When the window is widened, rows with a high fill ratio stretch to fill the row — no blank space on the right
  - Add/remove components, reset/clear layout
- **System Info module**: CPU / memory / disk, etc.
- **Path Forward module**: quickly open common paths
- **RSS Aggregator module**: feed fetching, reading, notifications
- Fluent-style theming (light / dark / follow system), wallpaper background and acrylic (blur) effect
- Minimize to tray on close, auto-start, global hotkeys

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

> **Note**: `yzplan.spec` needs to copy `sqlite3.dll`, `libcrypto`, etc. from your conda/anaconda environment.
> Before building, point the environment variable to your conda `Library\bin` directory:

```bat
set YZPLAN_CONDA_BIN=C:\path\to\your\anaconda3\Library\bin
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
