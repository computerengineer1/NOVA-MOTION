"""Hardware/system schemas.

Honesty rules baked into the types:
  * every measured field is Optional — None means "could not be measured",
    never zero, never fabricated;
  * `*_available` flags tell the UI whether a value is real;
  * dedicated VRAM and shared graphics memory are separate fields.
"""
from __future__ import annotations

from pydantic import BaseModel


class CpuInfo(BaseModel):
    name: str | None = None
    physical_cores: int | None = None
    logical_cores: int | None = None
    available: bool = False


class MemoryInfo(BaseModel):
    total_gb: float | None = None
    available_gb: float | None = None
    used_percent: float | None = None
    available: bool = False


class GpuInfo(BaseModel):
    name: str | None = None
    driver_version: str | None = None
    # Dedicated VRAM only — never the WMI "AdapterRAM" shared figure.
    vram_total_mb: int | None = None
    vram_free_mb: int | None = None
    vram_used_mb: int | None = None
    utilization_percent: int | None = None
    temperature_c: int | None = None
    compute_capability: str | None = None
    source: str | None = None  # e.g. "nvidia-smi", "pynvml", "comfyui:/system_stats"
    available: bool = False
    cuda_available: bool | None = None  # None = unknown


class DiskInfo(BaseModel):
    path: str
    total_gb: float | None = None
    free_gb: float | None = None
    available: bool = False


class OsInfo(BaseModel):
    system: str | None = None
    release: str | None = None
    version: str | None = None
    machine: str | None = None


class EngineStatus(BaseModel):
    online: bool = False
    managed_process_running: bool = False
    base_url: str | None = None
    comfyui_version: str | None = None
    torch_version: str | None = None
    devices: list[dict] = []
    queue_remaining: int | None = None
    last_error: str | None = None
    checked_at: str | None = None


class ReadinessVerdict(BaseModel):
    level: str  # READY | WARNING | NOT_READY
    reasons: list[str] = []
    warnings: list[str] = []


class SystemReport(BaseModel):
    generated_at: str
    os: OsInfo
    cpu: CpuInfo
    memory: MemoryInfo
    gpu: GpuInfo | None = None
    gpus: list[GpuInfo] = []
    disks: list[DiskInfo] = []
    python_version: str
    backend_version: str
    engine: EngineStatus
    ffmpeg: dict
    installed_models: list[str] = []
    queue: dict
    readiness: ReadinessVerdict
