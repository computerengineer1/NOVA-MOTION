<#
.SYNOPSIS
  NOVA MOTION - start the studio (backend on 127.0.0.1:8317; the backend
  auto-starts the managed ComfyUI engine on 127.0.0.1:8188).
#>
[CmdletBinding()]
param(
  [switch]$NoBrowser   # do not open a browser tab
)

$ErrorActionPreference = 'Stop'
$Root       = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $Root 'backend'
$backendPy  = Join-Path $BackendDir '.venv\Scripts\python.exe'
$BaseUrl    = 'http://127.0.0.1:8317'

if (-not (Test-Path $backendPy)) {
  Write-Host 'Backend venv not found. Run Install-Studio.bat first.' -ForegroundColor Red
  Read-Host 'Press Enter to exit'
  exit 1
}

# already running?
$healthy = $false
try {
  $r = Invoke-WebRequest -Uri "$BaseUrl/api/health" -UseBasicParsing -TimeoutSec 3
  $healthy = ($r.StatusCode -eq 200)
} catch { $healthy = $false }

if ($healthy) {
  Write-Host 'NOVA MOTION backend is already running.' -ForegroundColor Yellow
} else {
  if (-not (Test-Path (Join-Path $Root 'frontend\dist\index.html'))) {
    Write-Host 'WARNING: frontend\dist is missing - the API will run but the UI cannot be served.' -ForegroundColor Yellow
    Write-Host '         Build it once:  cd frontend && npm install && npm run build' -ForegroundColor Yellow
  }
  Write-Host 'Starting NOVA MOTION backend (a new console window will open)...' -ForegroundColor Cyan
  Start-Process -FilePath $backendPy `
    -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8317' `
    -WorkingDirectory $BackendDir
  # wait for health (engine autostart can take a while on first launch)
  $deadline = (Get-Date).AddSeconds(90)
  do {
    Start-Sleep -Seconds 2
    try {
      $r = Invoke-WebRequest -Uri "$BaseUrl/api/health" -UseBasicParsing -TimeoutSec 3
      $healthy = ($r.StatusCode -eq 200)
    } catch { $healthy = $false }
    Write-Host '.' -NoNewline
  } while (-not $healthy -and (Get-Date) -lt $deadline)
  Write-Host ''
  if (-not $healthy) {
    Write-Host 'Backend did not become healthy within 90 s. Check the new console window and logs\app.log.' -ForegroundColor Red
    Write-Host 'Then run Diagnose-Studio.bat for a full report.' -ForegroundColor Yellow
    Read-Host 'Press Enter to exit'
    exit 1
  }
  Write-Host 'Backend is healthy.' -ForegroundColor Green
}

if (-not $NoBrowser) {
  Start-Process $BaseUrl
  Write-Host "Opened $BaseUrl in your browser." -ForegroundColor Green
}
Write-Host 'To stop everything later: run Stop-Studio.bat' -ForegroundColor DarkGray
