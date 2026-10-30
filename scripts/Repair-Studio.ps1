<#
.SYNOPSIS
  NOVA MOTION - repair. Re-verifies and re-installs broken pieces:
    * both venvs (re-runs pinned dependency installs, pip check)
    * model files: size + SHA-256 against models\registry.json; corrupted or
      truncated files can be deleted (with confirmation) so the Models page
      installer resumes/re-downloads them. Your videos in outputs\ are NEVER
      touched by this script.
    * FFmpeg presence (re-downloads if missing)
    * frontend dist presence
#>
[CmdletBinding()]
param(
  [switch]$SkipDeps      # only verify models/ffmpeg/frontend, no pip work
)

$ErrorActionPreference = 'Stop'
$Root      = Split-Path -Parent $PSScriptRoot
$ComfyDir  = Join-Path $Root 'engine\ComfyUI'
$backendPy = Join-Path $Root 'backend\.venv\Scripts\python.exe'
$enginePy  = Join-Path $Root 'engine\.venv\Scripts\python.exe'

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    [ok] $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "    [!!] $msg" -ForegroundColor Yellow }
function Write-Err2($msg) { Write-Host "    [xx] $msg" -ForegroundColor Red }

# ------------------------------------------------------------ dependencies
if (-not $SkipDeps) {
  Write-Step 'Backend venv'
  if (Test-Path $backendPy) {
    & $backendPy -m pip install -r (Join-Path $Root 'backend\requirements.txt')
    & $backendPy -m pip check
    if ($LASTEXITCODE -eq 0) { Write-Ok 'backend deps consistent' } else { Write-Warn2 'pip check reported conflicts above' }
  } else { Write-Err2 'backend venv missing - run Install-Studio.bat' }

  Write-Step 'Engine venv (torch must stay pinned: 2.14.1+cu130)'
  if (Test-Path $enginePy) {
    & $enginePy -c "import torch, torchvision; print('torch', torch.__version__, '| torchvision', torchvision.__version__, '| cuda build', torch.version.cuda)"
    & $enginePy -m pip install -r (Join-Path $ComfyDir 'requirements.txt')
    & $enginePy -m pip check
    if ($LASTEXITCODE -eq 0) { Write-Ok 'engine deps consistent' } else { Write-Warn2 'pip check reported conflicts above' }
    $adeReq = Join-Path $ComfyDir 'custom_nodes\ComfyUI-AnimateDiff-Evolved\requirements.txt'
    if (Test-Path $adeReq) { & $enginePy -m pip install -r $adeReq }
  } else { Write-Err2 'engine venv missing - run Install-Studio.bat' }
}

# ------------------------------------------------------------ model files
Write-Step 'Model files vs registry (SHA-256)'
$regPath = Join-Path $Root 'models\registry.json'
$bad = @()
if (Test-Path $regPath) {
  $reg = Get-Content $regPath -Raw | ConvertFrom-Json
  foreach ($m in $reg.models) {
    foreach ($f in $m.files) {
      $full = Join-Path $ComfyDir ($f.dest -replace '/', '\')
      if (-not (Test-Path $full)) { continue }   # not installed yet - fine
      $size = (Get-Item $full).Length
      if ($size -ne $f.size_bytes) {
        Write-Warn2 ("{0}: size {1:N0} != expected {2:N0} (truncated/corrupt)" -f $f.dest, $size, $f.size_bytes)
        $bad += $full
        continue
      }
      if ($f.sha256) {
        Write-Host "    hashing $($f.dest) ..."
        $h = (Get-FileHash $full -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($h -ne $f.sha256.ToLowerInvariant()) {
          Write-Warn2 ("{0}: SHA-256 mismatch" -f $f.dest)
          $bad += $full
        } else { Write-Ok ("{0} verified" -f $f.dest) }
      }
    }
  }
  if ($bad.Count -gt 0) {
    Write-Host ''
    Write-Err2 ("{0} corrupt model file(s) found. The installer can resume/re-download only if these are removed." -f $bad.Count)
    $answer = Read-Host 'Delete the corrupt files now? Your videos are never touched. (y/N)'
    if ($answer -match '^[yY]') {
      foreach ($p in $bad) { Remove-Item -Force $p; Write-Ok "deleted $p" }
      Write-Host '    Now open the Models page (or POST /api/models/install) to re-download.' -ForegroundColor Green
    } else {
      Write-Warn2 'Kept as-is. Nothing will be deleted without your confirmation.'
    }
  } else {
    Write-Ok 'all installed model files match the registry'
  }
} else { Write-Err2 'models\registry.json missing!' }

# ----------------------------------------------------------------- ffmpeg
Write-Step 'FFmpeg'
$ffLocal = Join-Path $Root 'tools\ffmpeg\bin\ffmpeg.exe'
$fpLocal = Join-Path $Root 'tools\ffmpeg\bin\ffprobe.exe'
if ((Test-Path $ffLocal) -and (Test-Path $fpLocal)) {
  Write-Ok 'tools\ffmpeg\bin complete'
} elseif (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
  Write-Ok 'ffmpeg found on PATH'
} else {
  Write-Warn2 'FFmpeg missing - downloading release-essentials build...'
  $zip = Join-Path $env:TEMP 'ffmpeg-release-essentials.zip'
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $zip -UseBasicParsing
  $tmpx = Join-Path $env:TEMP ("ffmpeg-x-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
  Expand-Archive -Path $zip -DestinationPath $tmpx -Force
  $binSrc = Get-ChildItem -Recurse -Directory $tmpx | Where-Object { $_.Name -eq 'bin' } | Select-Object -First 1
  $binDst = Join-Path $Root 'tools\ffmpeg\bin'
  New-Item -ItemType Directory -Force -Path $binDst | Out-Null
  Copy-Item (Join-Path $binSrc.FullName '*') $binDst -Force
  Remove-Item -Recurse -Force $tmpx; Remove-Item -Force $zip
  Write-Ok 'FFmpeg restored'
}

# --------------------------------------------------------------- frontend
Write-Step 'Frontend build'
if (Test-Path (Join-Path $Root 'frontend\dist\index.html')) {
  Write-Ok 'frontend\dist present'
} else {
  Write-Warn2 'frontend\dist missing - run: cd frontend && npm install && npm run build'
}

Write-Host "`nRepair finished. Run Diagnose-Studio.bat for a fresh report." -ForegroundColor Green
