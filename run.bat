@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found!
    pause
    exit /b 1
)

set "PYTHONHOME="
set "PYTHONPATH="
set "PATH=%SystemRoot%\System32;%SystemRoot%;%~dp0.venv\Scripts;%~dp0.venv;%PATH%"

echo Using: ".venv\Scripts\python.exe"
".venv\Scripts\python.exe" -c "import PySide6.QtCore as c; print('Qt6Core:', c.__file__)"
".venv\Scripts\python.exe" main.py
