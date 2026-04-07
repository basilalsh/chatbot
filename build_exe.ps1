param(
    [switch]$OneFile = $true
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Python virtual environment not found at .venv."
}

& $python -m pip install --upgrade pip | Out-Null
& $python -m pip install pyinstaller pywebview bottle proxy_tools

$modeArgs = @("--onefile")
if (-not $OneFile) {
    $modeArgs = @("--onedir")
}

$commonArgs = @(
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", "DhofarAIAssistant",
    "--add-data", "templates;templates",
    "--add-data", "static;static",
    "--add-data", "data;data",
    "--add-data", "uploads;uploads",
    "--add-data", "utils;utils",
    "--add-data", "MERGED_PUBLIC_PDF_FILES.pdf;.",
    "--add-data", "dhofar-insurance-social.jpg;.",
    "--add-data", ".env;."
)

& $python -m PyInstaller @modeArgs @commonArgs "desktop_launcher.py"

Write-Host "`nBuild complete. EXE output:" -ForegroundColor Green
if ($OneFile) {
    Write-Host "  dist\DhofarAIAssistant.exe"
} else {
    Write-Host "  dist\DhofarAIAssistant\DhofarAIAssistant.exe"
}
