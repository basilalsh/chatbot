@echo off
chcp 65001 >nul
setlocal
title Dhofar AI Assistant - Update
color 0B

cd /d "%~dp0"

echo ============================================
echo   Dhofar Insurance AI Assistant - Updater
echo ============================================
echo.

:: ── Check git ────────────────────────────────────────────────
git --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo ERROR: Git is not installed.
    echo Please install Git from https://git-scm.com/downloads
    echo.
    pause
    exit /b 1
)

:: ── Fetch latest info ────────────────────────────────────────
echo Checking for updates...
echo.
git fetch origin main 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo ERROR: Could not reach GitHub. Check your internet connection.
    echo.
    pause
    exit /b 1
)

:: ── Check if behind ─────────────────────────────────────────
for /f %%c in ('git rev-list HEAD..origin/main --count 2^>nul') do set "BEHIND=%%c"

if "%BEHIND%"=="0" (
    echo You already have the latest version. No update needed.
    echo.
    pause
    exit /b 0
)

echo Found %BEHIND% new update(s). Pulling...
echo.
git pull origin main 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo ERROR: Update failed. You may have local changes conflicting.
    echo Please contact your administrator.
    echo.
    pause
    exit /b 1
)

:: ── Pull LFS objects (large files like embedding cache) ──────
git lfs pull 2>&1

echo.
echo ============================================
echo   Update successful!
echo ============================================
echo.
echo Run run.bat to launch the updated application.
echo.
pause
