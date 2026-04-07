@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Dhofar Insurance AI Assistant
color 0A

:: Ensure we run from the script's own directory
cd /d "%~dp0"

echo ============================================
echo   Dhofar Insurance AI Assistant - Launcher
echo ============================================
echo.

:: ── Step 1: Check Python ──────────────────────────────────────
echo [1/9] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo ERROR: Python is not installed.
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    echo and make sure "Add Python to PATH" is checked during installation.
    echo.
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do (
    echo        Found Python %%v
)
echo.

:: ── Step 2: Virtual environment ───────────────────────────────
echo [2/9] Setting up virtual environment...
if not exist ".venv\Scripts\python.exe" (
    echo        Creating .venv...
    python -m venv .venv
    if %errorlevel% neq 0 (
        color 0C
        echo.
        echo ERROR: Failed to create virtual environment.
        echo.
        pause
        exit /b 1
    )
    echo        Virtual environment created.
) else (
    echo        Virtual environment already exists.
)
echo.

:: Use the venv Python/pip directly (more reliable than activate.bat)
set "VENV_PYTHON=.venv\Scripts\python.exe"
set "VENV_PIP=.venv\Scripts\pip.exe"

:: ── Step 3: Verify venv ──────────────────────────────────────
echo [3/9] Verifying virtual environment...
"%VENV_PYTHON%" --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo ERROR: Virtual environment Python not found.
    echo        Try deleting .venv folder and running this script again.
    echo.
    pause
    exit /b 1
)
echo        Virtual environment OK.
echo.

:: ── Step 4: Install Python dependencies ──────────────────────
echo [4/9] Installing Python dependencies...
"%VENV_PYTHON%" -m pip install --upgrade pip --quiet >nul 2>&1

"%VENV_PIP%" install -r requirements.txt --quiet --no-warn-script-location
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo ERROR: Failed to install Python dependencies.
    echo        Check requirements.txt and your internet connection.
    echo.
    pause
    exit /b 1
)
echo        All Python dependencies installed.
echo.

:: ── Step 5: Install Tesseract OCR ──────────────────────────
echo [5/9] Checking Tesseract OCR...
set "TESSERACT_EXE="
where tesseract >nul 2>&1
if %errorlevel% equ 0 (
    for /f "delims=" %%p in ('where tesseract 2^>nul') do (
        if not defined TESSERACT_EXE set "TESSERACT_EXE=%%p"
    )
)
if not defined TESSERACT_EXE (
    if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (
        set "TESSERACT_EXE=C:\Program Files\Tesseract-OCR\tesseract.exe"
    )
)
if not defined TESSERACT_EXE (
    if exist "C:\Program Files (x86)\Tesseract-OCR\tesseract.exe" (
        set "TESSERACT_EXE=C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"
    )
)

:: If already installed — use it as-is, no admin rights or changes needed.
if defined TESSERACT_EXE (
    echo        Tesseract already installed - no changes needed.
    goto :tess_done
)

:: Not installed — download and install with Arabic support (one UAC prompt).
echo        Tesseract not found. Downloading installer (~40 MB)...
set "TESS_INSTALLER=%TEMP%\tesseract-ocr-setup.exe"
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri 'https://digi.bib.uni-mannheim.de/tesseract/tesseract-ocr-w64-setup-5.5.0.20241111.exe' -OutFile '%TESS_INSTALLER%' -UseBasicParsing" >nul 2>&1
if not exist "%TESS_INSTALLER%" (
    echo        WARNING: Could not download Tesseract. OCR for scanned pages will be skipped.
    goto :tess_done
)
echo        Installing Tesseract and Arabic language data...
echo        (A User Account Control prompt will appear — click Yes to allow the install)
echo $ProgressPreference = 'SilentlyContinue' > "%TEMP%\tess_setup.ps1"
echo Start-Process -Wait -FilePath '%TESS_INSTALLER%' -ArgumentList '/VERYSILENT', '/NORESTART', '/SUPPRESSMSGBOXES' >> "%TEMP%\tess_setup.ps1"
echo if (Test-Path 'C:\Program Files\Tesseract-OCR\tesseract.exe') { >> "%TEMP%\tess_setup.ps1"
echo     $ara = 'C:\Program Files\Tesseract-OCR\tessdata\ara.traineddata' >> "%TEMP%\tess_setup.ps1"
echo     if (-not (Test-Path $ara)) { >> "%TEMP%\tess_setup.ps1"
echo         Invoke-WebRequest -Uri 'https://github.com/tesseract-ocr/tessdata/raw/main/ara.traineddata' -OutFile $ara -UseBasicParsing >> "%TEMP%\tess_setup.ps1"
echo     } >> "%TEMP%\tess_setup.ps1"
echo } >> "%TEMP%\tess_setup.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File ""%TEMP%\tess_setup.ps1""'"
del "%TEMP%\tess_setup.ps1" >nul 2>&1
del "%TESS_INSTALLER%" >nul 2>&1
if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (
    set "TESSERACT_EXE=C:\Program Files\Tesseract-OCR\tesseract.exe"
    echo        Tesseract installed successfully.
) else (
    echo        WARNING: Installation cancelled or failed. OCR will be skipped.
)

:tess_done
if defined TESSERACT_EXE (
    set "PYTESSERACT_TESSERACT_CMD=%TESSERACT_EXE%"
    set "PATH=C:\Program Files\Tesseract-OCR;%PATH%"
    echo        Tesseract OCR ready.
) else (
    echo        Tesseract not available - scanned PDF pages will be skipped.
)
echo.

:: ── Step 6: Check Node.js ────────────────────────────────────
echo [6/9] Checking Node.js installation...
node --version >nul 2>&1
if %errorlevel% neq 0 (
    :: If Node.js is not installed, check if build already exists
    if exist "static\dist\index.html" (
        echo        Node.js not found, but frontend is already built. Skipping.
        echo.
        goto :start_app
    )
    color 0C
    echo.
    echo ERROR: Node.js is not installed and no pre-built frontend found.
    echo Please install Node.js 18+ from https://nodejs.org/
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('node --version 2^>^&1') do (
    echo        Found Node.js %%v
)
echo.

:: ── Step 7: Build frontend ───────────────────────────────────
echo [7/9] Building frontend...
pushd frontend

:: Skip rebuild if the production bundle already exists (saves ~30 seconds on repeat runs).
:: Delete the static\dist folder manually to force a rebuild.
if exist "..\static\dist\index.html" (
    echo        Frontend already built. Skipping rebuild.
    popd
    echo.
    goto :start_app
)

echo        Installing npm packages...
call npm install --legacy-peer-deps --silent >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo ERROR: Failed to install npm packages.
    echo.
    popd
    pause
    exit /b 1
)
echo        Building React app...
call npx vite build >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo ERROR: Frontend build failed.
    echo        To see details, open a terminal, go to the frontend\ folder
    echo        and run:  npx vite build
    echo.
    popd
    pause
    exit /b 1
)
popd
echo        Frontend built successfully.
echo.

:: ── Step 8: Check .env and API key ─────────────────────────
:start_app
echo [8/9] Checking configuration (.env)...
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        color 0E
        echo.
        echo  NOTICE: A .env file has been created from .env.example
        echo  You must set your GEMINI_API_KEY before the app will work.
        echo.
        echo  Opening .env for editing now...
        echo  After saving the file, re-run this script.
        echo.
        pause
        notepad .env
        exit /b 0
    ) else (
        color 0C
        echo.
        echo ERROR: No .env file found. Please create one containing:
        echo        GEMINI_API_KEY=your_key_here
        echo.
        pause
        exit /b 1
    )
)
:: Warn (but don't block) if the key still has the placeholder value.
findstr /C:"your_gemini_api_key_here" .env >nul 2>&1
if %errorlevel% equ 0 (
    color 0E
    echo.
    echo  WARNING: GEMINI_API_KEY in .env still has the placeholder value.
    echo  Open .env and replace "your_gemini_api_key_here" with your real key.
    echo.
    pause
)
color 0A
echo        Configuration OK.
echo.

:: ── Step 9: Launch application ────────────────────────────────
echo [9/9] Starting Dhofar Insurance AI Assistant...
echo.
echo ============================================
echo   Application running at:
echo   http://127.0.0.1:5000
echo.
echo   Press Ctrl+C to stop the server.
echo ============================================
echo.

:: Open browser after a short delay (gives Flask time to start)
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:5000"

"%VENV_PYTHON%" app.py
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo ERROR: Application exited with an error.
    echo.
    pause
    exit /b 1
)

pause
