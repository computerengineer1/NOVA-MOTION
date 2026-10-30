<#
.SYNOPSIS
  NOVA MOTION - diagnostics report. Measures the real machine (dedicated VRAM
  via nvidia-smi, real free RAM/disk), checks every installation artifact,
  probes the running services, and writes logs\diagnostic-<timestamp>.txt.
  Read-only: changes nothing.
#>
[CmdletBinding()]
param(
  [switch]$HashModels   # also verify SHA-256 of installed model files (slow)
)

$ErrorActionPreference = 'Continue'
$Root       = Split-Path -Parent $PSScriptRoot
$ComfyDir   = Join-Path $Root 'engine\ComfyUI'
$report     = New-Object System.Collections.Generic.List[string]

function Log($msg) { Write-Host $msg; $report.Add($msg) }
function Section($t) { Log ''; Log ('=' * 62); Log " $t"; Log ('=' * 62) }

Section 'NOVA MOTION DIAGNOSTIC REPORT'
Log ("Time: {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
Log ("Project root: {0}" -f $Root)

Section '1. Operating system / CPU / RAM'
$os = Get-CimInstance Win32_OperatingSystem
Log ("OS: {0} (build {1}), {2}" -f $os.Caption, $os.BuildNumber, $os.OSArchitecture)
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
Log ("CPU: {0} ({1} cores / {2} logical)" -f $cpu.Name.Trim(), $cpu.NumberOfCores, $cpu.NumberOfLogicalProcessors)
$ramTotal = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
$ramFree  = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
Log ("RAM: {0} GB total, {1} GB free" -f $ramTotal, $ramFree)
if ($ramFree -lt 2.2) { Log 'WARNING: less than 2.2 GB free RAM - generation preflight will warn/block. Close other apps.' }

Section '2. GPU (dedicated VRAM only - shared memory is NOT VRAM)'
$nvsmi = Join-Path $env:SystemRoot 'System32\nvidia-smi.exe'
if (Test-Path $nvsmi) {
  $q = & $nvsmi --query-gpu=name,driver_version,memory.total,memory.used --format=csv,noheader 2>$null
  if ($q) { Log ("nvidia-smi: {0}" -f ($q -join '; ')) }
  $cc = & $nvsmi --query-gpu=compute_cap --format=csv,noheader 2>$null
  if ($cc) { Log ("compute capability: {0}" -f ($cc -join ', ')) }
} else {
  Log 'nvidia-smi not found (driver not installed?) - falling back to WMI (note: WMI AdapterRAM caps at 4 GB and is unreliable).'
}
Get-CimInstance Win32_VideoController | ForEach-Object {
  Log ("WMI GPU: {0} | driver {1} | AdapterRAM(raw, unreliable) {2} GB" -f $_.Name, $_.DriverVersion, [math]::Round($_.AdapterRAM / 1GB, 2))
}

Section '3. Disk space'
Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Free -ne $null } | ForEach-Object {
  Log ("{0}: {1} GB free of {2} GB" -f $_.Name, [math]::Round($_.Free / 1GB, 1), [math]::Round(($_.Used + $_.Free) / 1GB, 1))
}

Section '4. Toolchain versions'
foreach ($tool in @('py', 'python', 'node', 'npm', 'git')) {
  $cmd = Get-Command $tool -ErrorAction SilentlyContinue
  if ($cmd) {
    $ver = & $tool --version 2>$null | Select-Object -First 1
    Log ("{0}: {1}" -f $tool, $ver)
  } else { Log ("{0}: NOT FOUND" -f $tool) }
}
$ffLocal = Join-Path $Root 'tools\ffmpeg\bin\ffmpeg.exe'
if (Test-Path $ffLocal) { Log ("ffmpeg (project): {0}" -f (& $ffLocal -version 2>$null | Select-Object -First 1)) }
$ffPath = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ffPath) { Log ("ffmpeg (PATH): {0}" -f $ffPath.Source) }
if (-not (Test-Path $ffLocal) -and -not $ffPath) { Log 'ffmpeg: NOT FOUND - encoding will fail. Run Repair-Studio or Install-Studio.' }

Section '5. Installation artifacts'
$checks = [ordered]@{
  'backend\.venv\Scripts\python.exe'              = (Join-Path $Root 'backend\.venv\Scripts\python.exe')
  'engine\.venv\Scripts\python.exe'               = (Join-Path $Root 'engine\.venv\Scripts\python.exe')
  'engine\ComfyUI\main.py (ComfyUI v0.43.0)'      = (Join-Path $ComfyDir 'main.py')
  'custom_nodes\ComfyUI-AnimateDiff-Evolved'      = (Join-Path $ComfyDir 'custom_nodes\ComfyUI-AnimateDiff-Evolved')
  'custom_nodes\ComfyUI-Frame-Interpolation (opt)'= (Join-Path $ComfyDir 'custom_nodes\ComfyUI-Frame-Interpolation')
  'frontend\dist\index.html (built UI)'           = (Join-Path $Root 'frontend\dist\index.html')
  'models\registry.json'                          = (Join-Path $Root 'models\registry.json')
  'workflows\animatediff_t2v.template.json'       = (Join-Path $Root 'workflows\animatediff_t2v.template.json')
  'data\nova.db (created on first run)'           = (Join-Path $Root 'data\nova.db')
}
foreach ($k in $checks.Keys) {
  $state = if (Test-Path $checks[$k]) { 'present' } else { 'MISSING' }
  Log ("{0,-46} {1}" -f $k, $state)
}

Section '6. Model files (from models\registry.json)'
$regPath = Join-Path $Root 'models\registry.json'
if (Test-Path $regPath) {
  $reg = Get-Content $regPath -Raw | ConvertFrom-Json
  foreach ($m in $reg.models) {
    Log ("--- {0} [{1}]" -f $m.name, $m.status)
    foreach ($f in $m.files) {
      $full = Join-Path $ComfyDir ($f.dest -replace '/', '\')
      if (Test-Path $full) {
        $size = (Get-Item $full).Length
        $okSize = ($size -eq $f.size_bytes)
        $line = "    {0}  {1:N0} bytes (expected {2:N0}) {3}" -f $f.dest, $size, $f.size_bytes, $(if ($okSize) { 'OK' } else { 'SIZE MISMATCH' })
        if ($HashModels -and $f.sha256) {
          $h = (Get-FileHash $full -Algorithm SHA256).Hash.ToLowerInvariant()
          $line += if ($h -eq $f.sha256.ToLowerInvariant()) { '  sha256 OK' } else { "  SHA256 MISMATCH ($h)" }
        }
        Log $line
      } else {
        Log ("    {0}  not installed" -f $f.dest)
      }
    }
  }
} else { Log 'registry.json missing!' }

Section '7. Ports / running services'
foreach ($port in 8317, 8188) {
  $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  if ($conns) {
    $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($procId in $pids) {
      $p = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
      Log ("port {0}: LISTENING (PID {1} - {2})" -f $port, $procId, $(if ($p) { $p.Name } else { '?' }))
    }
  } else { Log ("port {0}: free (service not running)" -f $port) }
}
try {
  $h = Invoke-WebRequest -Uri 'http://127.0.0.1:8317/api/health' -UseBasicParsing -TimeoutSec 4
  Log ("backend /api/health: HTTP {0} {1}" -f $h.StatusCode, $h.Content)
} catch { Log 'backend /api/health: NOT RESPONDING (start it with Start-Studio.bat)' }
try {
  $rd = Invoke-WebRequest -Uri 'http://127.0.0.1:8317/api/system/readiness' -UseBasicParsing -TimeoutSec 6
  Log ("readiness: {0}" -f $rd.Content)
} catch { Log 'readiness: unavailable (backend not running)' }

Section '8. Recent log tails'
foreach ($lf in @('logs\app.log', 'logs\engine_comfyui.log')) {
  $p = Join-Path $Root $lf
  Log "--- $lf"
  if (Test-Path $p) { Get-Content $p -Tail 8 | ForEach-Object { Log "    $_" } }
  else { Log '    (no log file yet)' }
}

$out = Join-Path $Root ("logs\diagnostic-{0}.txt" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force -Path (Join-Path $Root 'logs') | Out-Null
$report | Set-Content -Path $out -Encoding UTF8
Write-Host ''
Write-Host "Report saved to: $out" -ForegroundColor Green
Write-Host 'Attach this file when asking for help. It contains no personal data beyond hardware specs.' -ForegroundColor DarkGray
