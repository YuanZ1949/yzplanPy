@echo off
chcp 65001 >nul
rem ========================================
rem   YZplan Build  (PyInstaller onedir)
rem   Recommended: standard python.org CPython (64bit) venv + pip install -r requirements.txt.
rem   conda/anaconda venvs are auto-detected by yzplan.spec (no env vars needed).
rem ========================================
echo ========================================
echo   YZplan Build
echo ========================================

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found!
    pause
    exit /b 1
)

set "PYTHONHOME="
set "PYTHONPATH="
set "PATH=%SystemRoot%\System32;%SystemRoot%;%~dp0.venv\Scripts;%~dp0.venv"

rem --- Backup runtime data files ---
set "DATA_BAK=_data_bak_%RANDOM%"
echo [INFO] Backing up runtime data to %DATA_BAK%\...
mkdir "%DATA_BAK%" 2>nul

if exist "data\app.db" (
    mkdir "%DATA_BAK%\data" 2>nul
    move /y "data\app.db" "%DATA_BAK%\data\app.db" >nul 2>&1
)
if exist "data\settings.json" (
    mkdir "%DATA_BAK%\data" 2>nul
    move /y "data\settings.json" "%DATA_BAK%\data\settings.json" >nul 2>&1
)
if exist "data\logs" (
    mkdir "%DATA_BAK%\data" 2>nul
    move /y "data\logs" "%DATA_BAK%\data\logs" >nul 2>&1
)

rem --- Build ---
copy /y ".venv\pyvenv.cfg" ".venv\pyvenv.cfg.bak" >nul
if exist "_fix_venv.py" (
    .venv\Scripts\python.exe _fix_venv.py --fix
)

.venv\Scripts\python.exe -m PyInstaller --noconfirm yzplan.spec
set "BUILD_RESULT=%errorlevel%"

copy /y ".venv\pyvenv.cfg.bak" ".venv\pyvenv.cfg" >nul
del ".venv\pyvenv.cfg.bak" >nul 2>&1

rem --- Restore runtime data files ---
echo [INFO] Restoring runtime data from %DATA_BAK%\...
if exist "%DATA_BAK%\data\app.db" (
    move /y "%DATA_BAK%\data\app.db" "data\app.db" >nul 2>&1
)
if exist "%DATA_BAK%\data\settings.json" (
    move /y "%DATA_BAK%\data\settings.json" "data\settings.json" >nul 2>&1
)
if exist "%DATA_BAK%\data\logs" (
    if not exist "data\logs" mkdir "data\logs"
    xcopy /s /e /y /q "%DATA_BAK%\data\logs\*" "data\logs\" >nul 2>&1
    rd /s /q "%DATA_BAK%\data\logs" >nul 2>&1
)
rd /s /q "%DATA_BAK%" >nul 2>&1

if "%BUILD_RESULT%" equ "0" (
    echo.
    echo Build succeeded: dist\YZplan\
    ie4uinit.exe -show >nul 2>&1
) else (
    echo.
    echo Build failed!
)

pause
