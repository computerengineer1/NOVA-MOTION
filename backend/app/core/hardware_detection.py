"""Hardware detection.

Principles (per project requirements):
  * Never fabricate a value. If a measurement is unavailable, the field is
    None and the corresponding `available` flag is False.
  * Dedicated VRAM comes ONLY from NVIDIA tooling (nvidia-smi/pynvml/
    ComfyUI /system_stats) — never from WMI Win32_VideoController
    AdapterRAM, which conflates shared system memory (the "7.7 GB" trap on
    this laptop).
  * All subprocess calls use argument arrays with timeouts; no shell.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from typing import Any

import psutil

from ..logging_config import get_logger
from ..schemas.hardware import CpuInfo, DiskInfo, GpuInfo, MemoryInfo, OsInfo

log = get_logger(__name__)

_NVIDIA_QUERY = (
    "--query-gpu=name,driver_version,memory.total,memory.used,memory.free,"
    "utilization.gpu,temperature.gpu,compute_cap"
)
_GPU_CACHE_TTL_S = 2.0
_gpu_cache: tuple[float, list[GpuInfo]] | None = None


def detect_os() -> OsInfo:
    info = OsInfo(
        system=platform.system() or None,
        release=platform.release() or None,
        version=platform.version() or None,
        machine=platform.machine() or None,
    )
    if os.name == "nt":
        try:
            wv = sys.getwindowsversion()  # type: ignore[attr-defined]
            info.version = f"{wv.major}.{wv.minor}.{wv.build}"
        except Exception:  # noqa: BLE001
            pass
    return info


def detect_cpu() -> CpuInfo:
    name: str | None = None
    try:
        if os.name == "nt":
            name = platform.processor() or None
        else:
            with open("/proc/cpuinfo", encoding="utf-8") as fh:
                for line in fh:
                    if line.lower().startswith("model name"):
                        name = line.split(":", 1)[1].strip()
                        break
    except OSError:
        pass
    physical = psutil.cpu_count(logical=False)
    logical = psutil.cpu_count(logical=True)
    return CpuInfo(
        name=name,
        physical_cores=physical,
        logical_cores=logical,
        available=name is not None or logical is not None,
    )


def detect_memory() -> MemoryInfo:
    try:
        vm = psutil.virtual_memory()
        return MemoryInfo(
            total_gb=round(vm.total / 1024**3, 2),
            available_gb=round(vm.available / 1024**3, 2),
            used_percent=vm.percent,
            available=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Memory detection failed: %s", exc)
        return MemoryInfo(available=False)


def detect_disks(paths: list[str]) -> list[DiskInfo]:
    out: list[DiskInfo] = []
    for path in paths:
        try:
            usage = psutil.disk_usage(path)
            out.append(
                DiskInfo(
                    path=path,
                    total_gb=round(usage.total / 1024**3, 1),
                    free_gb=round(usage.free / 1024**3, 1),
                    available=True,
                )
            )
        except OSError as exc:
            log.warning("Disk usage for %s unavailable: %s", path, exc)
            out.append(DiskInfo(path=path, available=False))
    return out


def _run_nvidia_smi(timeout: float = 6.0) -> list[GpuInfo] | None:
    exe = shutil.which("nvidia-smi")
    if exe is None:
        candidate = os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"),
            "System32", "nvidia-smi.exe",
        )
        exe = candidate if os.path.isfile(candidate) else None
    if exe is None:
        return None
    try:
        proc = subprocess.run(
            [exe, _NVIDIA_QUERY, "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode != 0:
            log.debug("nvidia-smi rc=%s stderr=%s", proc.returncode, proc.stderr[:200])
            return None
        gpus: list[GpuInfo] = []
        for line in proc.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 8:
                continue

            def _int(v: str) -> int | None:
                try:
                    return int(float(v))
                except ValueError:
                    return None

            gpus.append(
                GpuInfo(
                    name=parts[0] or None,
                    driver_version=parts[1] or None,
                    vram_total_mb=_int(parts[2]),
                    vram_used_mb=_int(parts[3]),
                    vram_free_mb=_int(parts[4]),
                    utilization_percent=_int(parts[5]),
                    temperature_c=_int(parts[6]),
                    compute_capability=parts[7] or None,
                    source="nvidia-smi",
                    available=True,
                    cuda_available=None,  # determined via engine /system_stats
                )
            )
        return gpus or None
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.debug("nvidia-smi failed: %s", exc)
        return None


def _run_pynvml() -> list[GpuInfo] | None:
    """Optional path when the pynvml package exists in this venv."""
    try:
        import pynvml  # type: ignore
    except ImportError:
        return None
    try:
        pynvml.nvmlInit()
        count = pynvml.nvmlDeviceGetCount()
        gpus: list[GpuInfo] = []
        for i in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
            except Exception:  # noqa: BLE001
                util = None
            try:
                temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            except Exception:  # noqa: BLE001
                temp = None
            try:
                driver = pynvml.nvmlSystemGetDriverVersion()
            except Exception:  # noqa: BLE001
                driver = None
            gpus.append(
                GpuInfo(
                    name=pynvml.nvmlDeviceGetName(handle),
                    driver_version=driver,
                    vram_total_mb=int(mem.total / 1024**2),
                    vram_used_mb=int(mem.used / 1024**2),
                    vram_free_mb=int(mem.free / 1024**2),
                    utilization_percent=int(util) if util is not None else None,
                    temperature_c=int(temp) if temp is not None else None,
                    source="pynvml",
                    available=True,
                )
            )
        pynvml.nvmlShutdown()
        return gpus or None
    except Exception as exc:  # noqa: BLE001
        log.debug("pynvml failed: %s", exc)
        return None


def detect_gpus(force_refresh: bool = False) -> list[GpuInfo]:
    """Detect GPUs with a short cache. Returns [] when nothing is measurable.

    Order: pynvml (if present) -> nvidia-smi -> empty (honest "unknown").
    ComfyUI's /system_stats later fills in CUDA availability + torch view.
    """
    global _gpu_cache
    now = time.monotonic()
    if not force_refresh and _gpu_cache and now - _gpu_cache[0] < _GPU_CACHE_TTL_S:
        return _gpu_cache[1]
    gpus = _run_pynvml() or _run_nvidia_smi() or []
    _gpu_cache = (now, gpus)
    return gpus


def gpu_snapshot() -> dict[str, Any]:
    """Compact live snapshot for the dashboard (never fabricates values)."""
    gpus = detect_gpus()
    primary = gpus[0] if gpus else None
    mem = detect_memory()
    return {
        "gpu": primary.model_dump() if primary else None,
        "gpu_count": len(gpus),
        "memory": mem.model_dump(),
        "cpu_percent": psutil.cpu_percent(interval=None),
        "measured_at": time.time(),
    }
