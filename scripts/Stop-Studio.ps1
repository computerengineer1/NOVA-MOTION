<#
.SYNOPSIS
  NOVA MOTION - graceful stop. Frees engine memory first (if backend is up),
  then stops ONLY the processes listening on our two loopback ports, and only
  if they were started from this project folder (never touches anything else).
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot

function Get-PortPids([int]$port) {
  try {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop |
      Select-Object -ExpandProperty OwningProcess -Unique
  } catch { @() }
}

function Test-Ours([int]$procId) {
  try {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction Stop
    return ($p.CommandLine -match [regex]::Escape('NOVA-MOTION')) -or
           ($p.CommandLine -match 'uvicorn') -or
           ($p.CommandLine -match [regex]::Escape((Join-Path $Root 'engine')))
  } catch { return $false }
}

# 1) ask the engine to release VRAM while the backend can still relay it
try {
  Invoke-WebRequest -Uri 'http://127.0.0.1:8317/api/engine/free' -Method POST -UseBasicParsing -TimeoutSec 5 | Out-Null
  Write-Host 'Engine memory release requested.' -ForegroundColor Green
} catch {
  Write-Host 'Backend not responding - skipping memory release.' -ForegroundColor DarkYellow
}

$stopped = 0
foreach ($port in 8317, 8188) {
  foreach ($procId in (Get-PortPids $port)) {
    if (Test-Ours $procId) {
      try {
        Stop-Process -Id $procId -Force -ErrorAction Stop
        Write-Host "Stopped PID $procId (port $port)." -ForegroundColor Green
        $stopped++
      } catch {
        Write-Host "Could not stop PID ${procId}: $($_.Exception.Message)" -ForegroundColor Red
      }
    } else {
      Write-Host "PID $procId on port $port was NOT started by NOVA MOTION - leaving it alone." -ForegroundColor Yellow
    }
  }
}

if ($stopped -eq 0) { Write-Host 'Nothing was running.' -ForegroundColor DarkGray }
else { Write-Host 'NOVA MOTION stopped. Your videos and models are untouched.' -ForegroundColor Green }
