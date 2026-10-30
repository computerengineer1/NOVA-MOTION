"""Health + system report endpoints."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

from ..core.hardware_detection import detect_cpu, detect_disks, detect_gpus, detect_memory, detect_os
from ..engines.base import EngineStatus as EngineStatusData
from ..schemas.hardware import EngineStatus, ReadinessVerdict, SystemReport
from ..schemas.common import OkResponse

router = APIRouter(prefix="/api", tags=["system"])

BACKEND_VERSION = "1.0.0"


def _engine_to_schema(status: EngineStatusData) -> EngineStatus:
    return EngineStatus(
        online=status.online,
        managed_process_running=status.managed_process_running,
        base_url=status.base_url,
        comfyui_version=status.comfyui_version,
        torch_version=status.torch_version,
        devices=status.devices,
        queue_remaining=status.queue_remaining,
        last_error=status.last_error,
        checked_at=status.checked_at,
    )


def _get_container(request: Request):
    return request.app.state.container


@router.get("/health")
async def health() -> dict:
    """Liveness only. HTTP 200 here does NOT mean generation is possible —
    see /api/system .readiness for that (by design)."""
    return {
        "status": "ok",
        "service": "nova-motion-backend",
        "version": BACKEND_VERSION,
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _compute_readiness(ctx) -> ReadinessVerdict:
    reasons: list[str] = []
    warnings: list[str] = []
    level = "READY"

    engine = ctx["engine"]
    if not engine.online:
        level = "NOT_READY"
        reasons.append("Inference engine (ComfyUI) is offline." + (
            " No managed installation found — run scripts/Install-Studio.ps1."
            if not ctx["engine_manageable"] else
            " It should autostart; try 'Restart engine' on the System page."))
    else:
        has_cuda = any(d.get("type") == "cuda" for d in engine.devices)
        if not has_cuda:
            warnings.append(
                "Engine is online but reports NO CUDA device — generation would run on CPU "
                "and take many hours. Check your NVIDIA driver and PyTorch installation.")
        if engine.torch_version is None:
            warnings.append("Engine did not report a PyTorch version.")

    if not ctx["ffmpeg_available"]:
        level = "NOT_READY"
        reasons.append("FFmpeg is not installed — video assembly/encoding is impossible. "
                       "Run scripts/Install-Studio.ps1 or: winget install Gyan.FFmpeg")

    if not ctx["installed_model_ids"]:
        level = "NOT_READY" if level != "NOT_READY" else level
        reasons.append("No compatible model is installed. Open the Models page and install "
                       "'AnimateDiff v2 Motion + Stable Diffusion 1.5 (fp16)' (~4 GB).")

    mem = ctx["memory"]
    if mem.available and mem.available_gb is not None:
        if mem.available_gb < ctx["min_free_ram_gb_block"]:
            level = "NOT_READY"
            reasons.append(f"Only {mem.available_gb:.1f} GB of system RAM is free "
                           f"(minimum {ctx['min_free_ram_gb_block']} GB). Close other applications.")
        elif mem.available_gb < ctx["min_free_ram_gb_warn"]:
            warnings.append(f"Free system RAM is low ({mem.available_gb:.1f} GB). "
                            "Generation may fail or thrash the pagefile.")

    gpu = ctx["gpu"]
    if gpu is not None and gpu.available and gpu.vram_total_mb is not None:
        if gpu.vram_total_mb < 2500:
            level = "NOT_READY"
            reasons.append(f"GPU reports only {gpu.vram_total_mb} MB dedicated VRAM "
                           "(~2500 MB minimum for the recommended model).")

    if level == "READY" and warnings:
        level = "WARNING"
    return ReadinessVerdict(level=level, reasons=reasons, warnings=warnings)


@router.get("/system", response_model=SystemReport)
async def system_report(request: Request) -> SystemReport:
    container = _get_container(request)
    settings = container.settings

    engine_status = await container.engines.status(force=True)
    memory = detect_memory()
    gpus = detect_gpus()
    # merge engine-reported CUDA availability into the primary GPU view
    primary_gpu = gpus[0] if gpus else None
    if primary_gpu is not None and engine_status.online and engine_status.devices:
        for d in engine_status.devices:
            if d.get("type") == "cuda":
                primary_gpu.cuda_available = True
                break
        else:
            primary_gpu.cuda_available = False
    ffmpeg_info = container.ffmpeg.discover()

    installed_ids = [
        p.model_id for p in container.registry.list_all()
        if p.status in ("recommended", "supported", "experimental")
        and container.registry.is_installed(p)
    ]

    ctx = {
        "engine": engine_status,
        "engine_manageable": hasattr(container.engines.adapter, "can_manage_process")
        and container.engines.adapter.can_manage_process(),
        "ffmpeg_available": ffmpeg_info["available"],
        "installed_model_ids": installed_ids,
        "memory": memory,
        "gpu": primary_gpu,
        "min_free_ram_gb_block": settings.min_free_ram_gb_block,
        "min_free_ram_gb_warn": settings.min_free_ram_gb_warn,
    }
    readiness = _compute_readiness(ctx)

    disks = detect_disks([str(settings.project_root), str(settings.engine_dir)])

    return SystemReport(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        os=detect_os(),
        cpu=detect_cpu(),
        memory=memory,
        gpu=primary_gpu,
        gpus=gpus,
        disks=disks,
        python_version=__import__("sys").version.split()[0],
        backend_version=BACKEND_VERSION,
        engine=_engine_to_schema(engine_status),
        ffmpeg=ffmpeg_info,
        installed_models=installed_ids,
        queue=container.jobs.queue_state(),
        readiness=readiness,
    )


@router.get("/system/readiness", response_model=ReadinessVerdict)
async def readiness(request: Request) -> ReadinessVerdict:
    report = await system_report(request)
    return report.readiness
