@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
echo ============================================================
echo   YZplan push-all  :  GitHub + Gitea 一键双推
echo ============================================================
cd /d "%~dp0"

set "ACTION=main"
if /I "%~1"=="--all"    set "ACTION=all"
if /I "%~1"=="--tags"   set "ACTION=tags"
if /I "%~1"=="--alltags" set "ACTION=alltags"
if /I "%~1"=="--main"   set "ACTION=main"

call :push_remote origin GitHub
if errorlevel 1 goto fail
call :push_remote gitea Gitea
if errorlevel 1 goto fail

echo.
echo [OK] 已按动作 "%ACTION%" 推送到 GitHub 与 Gitea。
goto end

:push_remote
if "%ACTION%"=="main"    git push "%~1" main
if "%ACTION%"=="all"     git push "%~1" --all
if "%ACTION%"=="tags"    git push "%~1" --tags
if "%ACTION%"=="alltags" git push "%~1" --all --tags
exit /b %errorlevel%

:fail
echo.
echo [ERROR] 至少一个远端推送失败。当前状态：
git status -sb
pause
exit /b 1

:end
pause
endlocal
