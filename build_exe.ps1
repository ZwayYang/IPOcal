$ErrorActionPreference = "Stop"

Set-Location -Path $PSScriptRoot

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
  Write-Host "Creating venv (.venv)..." -ForegroundColor Cyan
  py -m venv .venv
}

Write-Host "Installing build deps..." -ForegroundColor Cyan
.\.venv\Scripts\python.exe -m pip install --upgrade pip | Out-Host
.\.venv\Scripts\python.exe -m pip install pyinstaller | Out-Host

Write-Host "Building IPOcal.exe..." -ForegroundColor Cyan
.\.venv\Scripts\python.exe -m PyInstaller --onefile --name IPOcal launcher.py

Write-Host ""
Write-Host "Done. EXE is at: .\dist\IPOcal.exe" -ForegroundColor Green
Write-Host "Double-click it to start the server and open the browser." -ForegroundColor Green
Write-Host ""
