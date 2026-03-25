$ErrorActionPreference = "Stop"

try {
  # Ensure working directory is this script's folder
  Set-Location -Path $PSScriptRoot

  if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Creating venv (.venv)..." -ForegroundColor Cyan
    py -m venv .venv
  }

  Write-Host "Installing/updating dependencies..." -ForegroundColor Cyan
  .\.venv\Scripts\python.exe -m pip install -r requirements.txt | Out-Host

  $port = 8000
  $url = "http://127.0.0.1:$port/"

  Write-Host "Starting IPOcal at $url" -ForegroundColor Green
  Start-Process $url

  # Run server in this window (close window to stop)
  .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port $port
}
catch {
  Write-Host ""
  Write-Host "Failed to start IPOcal." -ForegroundColor Red
  Write-Host $_.Exception.Message -ForegroundColor Yellow
  Write-Host ""
  Read-Host "Press Enter to close"
  exit 1
}

