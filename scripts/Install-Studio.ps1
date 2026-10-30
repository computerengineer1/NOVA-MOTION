<#
.SYNOPSIS
  NOVA MOTION - one-time local installation (Windows 10/11, no admin rights).

.DESCRIPTION
  Installs, entirely inside this project folder:
    1. backend\.venv     - FastAPI backend dependencies (pinned)
    2. engine\ComfyUI    - ComfyUI v0.43.0 (pinned tag) + its requirements
    3. engine\.venv      - Python 3.13 venv with torch 2.14.1 + torchvision 0.29.1
                           (CUDA 13.0 wheels - works with recent NVIDIA drivers,
                           does NOT install the CUDA toolkit or touch system settings)
    4. custom_nodes\ComfyUI-AnimateDiff-Evolved - motion module support (Apache-2.0)
    5. tools\ffmpeg      - FFmpeg (gyan.dev release-essentials build) if not on PATH
    6. frontend\dist     - production UI build (requires Node.js >= 20.19; optional,
                           can be built later)

  Model weights (~4 GB) are NOT downloaded here - install them from the Models
  page in the UI, where the license is shown and explicitly accepted first.

  Nothing is written outside this folder. No admin rights, no registry edits,
  no PATH/env changes, no Docker, no WSL.
#>

[CmdletBinding()]
param(
  [switch]$SkipFrontend,      # skip npm install/build even if Node.js exists
  [switch]$WithRife,          # also install the OPTIONAL RIFE frame-interpolation node pack
  [switch]$Force              # re-run steps even if they appear complete
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$Root       = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $Root 'backend'
$EngineDir  = Join-Path $Root 'engine'
$ComfyDir   = Join-Path $EngineDir 'ComfyUI'
$ToolsDir   = Join-Path $Root 'tools'
$FrontDir   = Join-Path $Root 'frontend'

# ---- pinned versions (verified 2026-10-29; do not bump casually) ----------
$ComfyTag      = 'v0.43.0'
$ComfyZipUrl   = 'https://github.com/comfyanonymous/ComfyUI/archive/refs/tags/v0.43.0.zip'
$TorchVersion  = '2.14.1'
$TorchVision   = '0.29.1'
$TorchIndex    = 'https://download.pytorch.org/whl/cu130'
$AniDiffRepo   = 'https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved'
$AniDiffZip    = 'https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved/archive/refs/heads/main.zip'
$RifeRepo      = 'https://github.com/Fannovel16/ComfyUI-Frame-Interpolation'
$RifeZip       = 'https://github.com/Fannovel16/ComfyUI-Frame-Interpolation/archive/refs/heads/main.zip'
$FfmpegZipUrl  = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'

function Write-Step($msg)  { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "    [ok] $msg" -ForegroundColor Green }
function Write-Warn2($msg) { Write-Host "    [!!] $msg" -ForegroundColor Yellow }
function Write-Err2($msg)  { Write-Host "    [xx] $msg" -ForegroundColor Red }

function Test-Command($name) {
  $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

function Get-Py313 {
  # Prefer the py launcher with an explicit 3.13; fall back to a python that IS 3.13.
  if (Test-Command 'py') {
    try {
      $v = & py -3.13 -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
      if ($LASTEXITCODE -eq 0 -and $v -eq '3.13') { return @('py', @('-3.13')) }
    } catch { }
  }
  foreach ($cand in @('python3.13', 'python3', 'python')) {
    if (Test-Command $cand) {
      try {
        $v = & $cand -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v -eq '3.13') { return @($cand, @()) }
      } catch { }
    }
  }
  return $null
}

function Invoke-Download($url, $dest) {
  Write-Host "    downloading $url"
  $tmp = "$dest.part"
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing
  Move-Item -Force $tmp $dest
}

function Expand-ZipTo($zip, $destDir) {
  Expand-Archive -Path $zip -DestinationPath $destDir -Force
}

# ============================================================ preflight ====
Write-Host 'NOVA MOTION - local installer' -ForegroundColor Magenta
Write-Host "Project root: $Root"

if (-not (Test-Path (Join-Path $BackendDir 'requirements.txt'))) {
  Write-Err2 "backend\requirements.txt not found - run this script from the project's scripts folder."
  exit 1
}

$py = Get-Py313
if ($null -eq $py) {
  Write-Err2 'Python 3.13 was not found.'
  Write-Host '    Install it WITHOUT admin rights from https://www.python.org/downloads/'
  Write-Host '    (check "Add python.exe to PATH" or use the py launcher), then re-run.'
  exit 1
}
Write-Ok ("Python 3.13 found via '{0} {1}'" -f $py[0], ($py[1] -join ' '))

# free disk on the project drive (weights ~4 GB come later via the Models page)
$drive = (Get-Item $Root).PSDrive.Name
$freeGb = [math]::Round((Get-PSDrive $drive).Free / 1GB, 1)
Write-Ok "Free disk on ${drive}: $freeGb GB"
if ($freeGb -lt 8) {
  Write-Err2 "Less than 8 GB free - installation needs ~8 GB now (torch+ComfyUI) and ~4 GB later (models)."
  exit 1
} elseif ($freeGb -lt 15) {
  Write-Warn2 'Less than 15 GB free - enough to install, but model downloads (~4 GB) will be tight.'
}

# GPU sanity note (informational only - the backend does real detection at runtime)
try {
  $gpu = Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match 'NVIDIA|GeForce|RTX|GTX' } | Select-Object -First 1
  if ($gpu) { Write-Ok ("GPU seen by Windows: {0} (driver {1})" -f $gpu.Name, $gpu.DriverVersion) }
  else { Write-Warn2 'No NVIDIA GPU detected - generation requires CUDA. CPU-only runs are not supported.' }
} catch { Write-Warn2 'Could not query GPU info (non-fatal).' }

foreach ($d in @($EngineDir, $ToolsDir)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }

# ========================================================== backend venv ====
Write-Step 'Backend virtual environment (backend\.venv)'
$backendPy = Join-Path $BackendDir '.venv\Scripts\python.exe'
if ($Force -or -not (Test-Path $backendPy)) {
  & $py[0] @($py[1]) -m venv (Join-Path $BackendDir '.venv')
  if ($LASTEXITCODE -ne 0) { Write-Err2 'venv creation failed'; exit 1 }
}
& $backendPy -m pip install --quiet --upgrade pip wheel
& $backendPy -m pip install -r (Join-Path $BackendDir 'requirements.txt')
if ($LASTEXITCODE -ne 0) { Write-Err2 'backend dependency install failed'; exit 1 }
Write-Ok 'backend dependencies installed (pinned)'

# ============================================================== ComfyUI ====
Write-Step "ComfyUI $ComfyTag (engine\ComfyUI)"
if ($Force -or -not (Test-Path (Join-Path $ComfyDir 'main.py'))) {
  if (Test-Command 'git') {
    if (Test-Path $ComfyDir) { Remove-Item -Recurse -Force $ComfyDir }
    & git clone --depth 1 --branch $ComfyTag 'https://github.com/comfyanonymous/ComfyUI' $ComfyDir
    if ($LASTEXITCODE -ne 0) { Write-Err2 'git clone of ComfyUI failed'; exit 1 }
  } else {
    $zip = Join-Path $env:TEMP "comfyui-$ComfyTag.zip"
    Invoke-Download $ComfyZipUrl $zip
    $tmpx = Join-Path $env:TEMP "comfyui-x-$([guid]::NewGuid().ToString('N').Substring(0,8))"
    Expand-ZipTo $zip $tmpx
    $inner = Get-ChildItem $tmpx | Select-Object -First 1
    if (Test-Path $ComfyDir) { Remove-Item -Recurse -Force $ComfyDir }
    Move-Item $inner.FullName $ComfyDir
    Remove-Item -Recurse -Force $tmpx
    Remove-Item -Force $zip
  }
}
Write-Ok "ComfyUI present ($ComfyTag)"

# ============================================================ engine venv ==
Write-Step 'Engine virtual environment (engine\.venv) + PyTorch CUDA 13.0 wheels'
$enginePy = Join-Path $EngineDir '.venv\Scripts\python.exe'
if ($Force -or -not (Test-Path $enginePy)) {
  & $py[0] @($py[1]) -m venv (Join-Path $EngineDir '.venv')
  if ($LASTEXITCODE -ne 0) { Write-Err2 'engine venv creation failed'; exit 1 }
}
& $enginePy -m pip install --quiet --upgrade pip wheel
Write-Host '    installing torch (this is the biggest download, ~3 GB - be patient)'
& $enginePy -m pip install "torch==$TorchVersion" "torchvision==$TorchVision" --index-url $TorchIndex
if ($LASTEXITCODE -ne 0) { Write-Err2 'torch install failed'; exit 1 }
& $enginePy -m pip install -r (Join-Path $ComfyDir 'requirements.txt')
if ($LASTEXITCODE -ne 0) { Write-Err2 'ComfyUI requirements install failed'; exit 1 }
Write-Ok 'engine dependencies installed (torch pinned, CUDA 13.0 wheels)'

# ========================================================= custom nodes ====
Write-Step 'Custom node: ComfyUI-AnimateDiff-Evolved (required)'
$nodesDir = Join-Path $ComfyDir 'custom_nodes'
New-Item -ItemType Directory -Force -Path $nodesDir | Out-Null
$adeDir = Join-Path $nodesDir 'ComfyUI-AnimateDiff-Evolved'
if ($Force -or -not (Test-Path $adeDir)) {
  if (Test-Command 'git') {
    & git clone --depth 1 $AniDiffRepo $adeDir
    if ($LASTEXITCODE -ne 0) { Write-Err2 'git clone of AnimateDiff-Evolved failed'; exit 1 }
  } else {
    $zip = Join-Path $env:TEMP 'ade-main.zip'
    Invoke-Download $AniDiffZip $zip
    $tmpx = Join-Path $env:TEMP "ade-x-$([guid]::NewGuid().ToString('N').Substring(0,8))"
    Expand-ZipTo $zip $tmpx
    $inner = Get-ChildItem $tmpx | Select-Object -First 1
    Move-Item $inner.FullName $adeDir
    Remove-Item -Recurse -Force $tmpx; Remove-Item -Force $zip
  }
}
$adeReq = Join-Path $adeDir 'requirements.txt'
if (Test-Path $adeReq) { & $enginePy -m pip install -r $adeReq; if ($LASTEXITCODE -ne 0) { Write-Warn2 'AnimateDiff requirements had failures (often already satisfied).' } }
Write-Ok 'AnimateDiff-Evolved installed'

if ($WithRife) {
  Write-Step 'Optional custom node: ComfyUI-Frame-Interpolation (RIFE) - EXPERIMENTAL on 4 GB VRAM'
  $rifeDir = Join-Path $nodesDir 'ComfyUI-Frame-Interpolation'
  if ($Force -or -not (Test-Path $rifeDir)) {
    if (Test-Command 'git') {
      & git clone --depth 1 $RifeRepo $rifeDir
    } else {
      $zip = Join-Path $env:TEMP 'cfi-main.zip'
      Invoke-Download $RifeZip $zip
      $tmpx = Join-Path $env:TEMP "cfi-x-$([guid]::NewGuid().ToString('N').Substring(0,8))"
      Expand-ZipTo $zip $tmpx
      $inner = Get-ChildItem $tmpx | Select-Object -First 1
      Move-Item $inner.FullName $rifeDir
      Remove-Item -Recurse -Force $tmpx; Remove-Item -Force $zip
    }
  }
  $rifeReq = Join-Path $rifeDir 'requirements.txt'
  if (Test-Path $rifeReq) { & $enginePy -m pip install -r $rifeReq }
  Write-Ok 'RIFE node pack installed (FFmpeg minterpolate remains the recommended interpolator)'
} else {
  Write-Host '    (skipping optional RIFE pack - pass -WithRife to add it; minterpolate needs nothing)'
}

# ================================================================ FFmpeg ===
Write-Step 'FFmpeg'
$ffmpegLocal = Join-Path $ToolsDir 'ffmpeg\bin\ffmpeg.exe'
$onPath = Test-Command 'ffmpeg'
if ($Force -or (-not (Test-Path $ffmpegLocal) -and -not $onPath)) {
  $zip = Join-Path $env:TEMP 'ffmpeg-release-essentials.zip'
  Invoke-Download $FfmpegZipUrl $zip
  $tmpx = Join-Path $env:TEMP "ffmpeg-x-$([guid]::NewGuid().ToString('N').Substring(0,8))"
  Expand-ZipTo $zip $tmpx
  $binSrc = Get-ChildItem -Recurse -Directory $tmpx | Where-Object { $_.Name -eq 'bin' } | Select-Object -First 1
  if ($null -eq $binSrc) { Write-Err2 'ffmpeg zip layout unexpected'; exit 1 }
  $binDst = Join-Path $ToolsDir 'ffmpeg\bin'
  New-Item -ItemType Directory -Force -Path $binDst | Out-Null
  Copy-Item (Join-Path $binSrc.FullName '*') $binDst -Force
  Remove-Item -Recurse -Force $tmpx; Remove-Item -Force $zip
  Write-Ok "FFmpeg extracted to tools\ffmpeg\bin (the backend finds it there automatically)"
} elseif (Test-Path $ffmpegLocal) {
  Write-Ok 'FFmpeg already present in tools\ffmpeg\bin'
} else {
  Write-Ok 'FFmpeg found on PATH (backend will use it)'
}

# ============================================================== frontend ===
Write-Step 'Frontend build (frontend\dist)'
$distIndex = Join-Path $FrontDir 'dist\index.html'
if (-not $SkipFrontend -and (Test-Command 'npm') -and ($Force -or -not (Test-Path $distIndex))) {
  Push-Location $FrontDir
  try {
    & npm install --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'npm install failed' }
    & npm run build
    if ($LASTEXITCODE -ne 0) { throw 'npm run build failed' }
    Write-Ok 'frontend built'
  } catch {
    Write-Warn2 "Frontend build failed: $($_.Exception.Message)"
    Write-Warn2 'The backend still serves the API; build the UI later with: cd frontend && npm install && npm run build'
  } finally { Pop-Location }
} elseif (Test-Path $distIndex) {
  Write-Ok 'frontend\dist already built'
} else {
  Write-Warn2 'Node.js/npm not found (or -SkipFrontend). The UI needs a one-time build:'
  Write-Warn2 '  1) install Node.js LTS (>= 20.19) from https://nodejs.org  2) cd frontend  3) npm install  4) npm run build'
}

# ============================================================== summary ====
Write-Host "`n============================================================" -ForegroundColor Magenta
Write-Host ' Installation complete.' -ForegroundColor Green
Write-Host '   Next steps:'
Write-Host '     1. Run  Start-Studio.bat   (starts backend; it auto-starts ComfyUI'
Write-Host '        on 127.0.0.1:8188 with low-VRAM flags and opens the UI)'
Write-Host '     2. Open the Models page, accept the licenses and install the'
Write-Host '        recommended AnimateDiff + SD1.5 pack (~4 GB, resumable).'
Write-Host '     3. Generate your first 8-second video in the Studio.'
Write-Host '   Everything binds to 127.0.0.1 only. No telemetry, no accounts.'
Write-Host "============================================================`n" -ForegroundColor Magenta
