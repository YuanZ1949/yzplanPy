@echo off
chcp 65001 >nul
echo ========================================
echo   Push to GitHub + Gitea (main branch)
echo ========================================
cd /d "%~dp0"

echo.
echo [1/2] git push origin main  (GitHub) ...
git push origin main
if errorlevel 1 (
    echo.
    echo [ERROR] GitHub push failed!
    pause
    exit /b 1
)

echo.
echo [2/2] git push gitea main  (Gitea) ...
git push gitea main
if errorlevel 1 (
    echo.
    echo [ERROR] Gitea push failed!
    pause
    exit /b 1
)

echo.
echo Done: pushed to GitHub and Gitea.
pause
