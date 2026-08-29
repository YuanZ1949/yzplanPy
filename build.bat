@echo off
chcp 65001 >nul
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

copy /y ".venv\pyvenv.cfg" ".venv\pyvenv.cfg.bak" >nul
if exist "_fix_venv.py" (
    .venv\Scripts\python.exe _fix_venv.py --fix
)

.venv\Scripts\python.exe -m PyInstaller --noconfirm yzplan.spec
set "BUILD_RESULT=%errorlevel%"

copy /y ".venv\pyvenv.cfg.bak" ".venv\pyvenv.cfg" >nul
del ".venv\pyvenv.cfg.bak" >nul 2>&1

if "%BUILD_RESULT%" equ "0" (
    echo.
    echo Build succeeded: dist\YZplan\
    ie4uinit.exe -show >nul 2>&1
) else (
    echo.
    echo Build failed!
)

pause
