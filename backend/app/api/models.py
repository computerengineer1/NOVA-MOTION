"""Model management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..core.errors import ErrorCode, NovaError
from ..core.hardware_detection import detect_disks, detect_gpus, detect_memory
from ..core.model_registry import INSTALLABLE_STATUSES
from ..core.path_security import require_safe_identifier
from ..schemas.models import (
    ModelDeleteRequest,
    ModelFileInfo,
    ModelInstallRequest,
    ModelInstallStatus,
    ModelProfileOut,
    ModelValidateResult,
)

router = APIRouter(prefix="/api/models", tags=["models"])


def _get_container(request: Request):
    return request.app.state.container


def _compatibility(container, profile) -> dict:
    """Assessed against REAL detected hardware — never against assumptions."""
    reqs = profile.requirements or {}
    checks: list[dict] = []
    installable = profile.status in INSTALLABLE_STATUSES
    if not installable:
        checks.append({
            "name": "status", "ok": False,
            "message": profile.incompatible_reason or
            f"Profile status '{profile.status}' is not installable.",
        })
        return {"installable": False, "checks": checks}

    gpus = detect_gpus()
    need_vram = reqs.get("min_dedicated_vram_mb")
    if need_vram and gpus and gpus[0].vram_total_mb is not None:
        ok = gpus[0].vram_total_mb >= need_vram
        checks.append({
            "name": "dedicated_vram", "ok": ok,
            "message": f"GPU has {gpus[0].vram_total_mb} MB dedicated VRAM "
                       f"({'≥' if ok else '<'} required {need_vram} MB).",
        })
    elif need_vram:
        checks.append({"name": "dedicated_vram", "ok": None,
                       "message": "Could not measure dedicated VRAM from the backend."})

    mem = detect_memory()
    need_ram = reqs.get("recommended_system_ram_gb")
    if need_ram and mem.available and mem.total_gb is not None:
        ok = mem.total_gb >= float(need_ram) * 0.9
        checks.append({
            "name": "system_ram", "ok": ok,
            "message": f"System RAM {mem.total_gb:.1f} GB "
                       f"(recommended ≥ {need_ram} GB).",
        })

    disks = detect_disks([str(container.settings.engine_dir)])
    need_disk = float(reqs.get("min_free_disk_gb", 0) or 0)
    dl_gb = profile.total_download_bytes / 1024**3
    if disks and disks[0].available and disks[0].free_gb is not None:
        ok = disks[0].free_gb >= max(need_disk, dl_gb * 1.15)
        checks.append({
            "name": "disk", "ok": ok,
            "message": f"Free disk {disks[0].free_gb:.1f} GB "
                       f"(needs ~{max(need_disk, dl_gb * 1.15):.1f} GB for this model).",
        })

    failed = [c for c in checks if c["ok"] is False]
    return {"installable": not failed, "checks": checks}


def _profile_out(container, profile) -> ModelProfileOut:
    installed = container.registry.is_installed(profile)
    st = container.installer.status(profile.model_id)
    db_row = container.models_repo.get(profile.model_id)
    files = [ModelFileInfo(**container.registry.file_state(f)) for f in profile.files]
    return ModelProfileOut(
        model_id=profile.model_id,
        name=profile.name,
        model_type=profile.model_type,
        adapter=profile.adapter,
        status=profile.status,  # type: ignore[arg-type]
        license_id=profile.license_id,
        license_url=(profile.license_urls or [None])[0],
        source=profile.source,
        version=profile.version,
        total_download_bytes=profile.total_download_bytes,
        installed=installed,
        install_progress=(st.percent if st.state in ("downloading", "verifying") else None),
        validation_status=(db_row or {}).get("validation_status", "unknown"),
        validation_note=(db_row or {}).get("validation_note"),
        compatibility=_compatibility(container, profile),
        capabilities={
            **profile.capabilities,
            "memory_notes": profile.memory_notes,
            "quality_notes": profile.quality_notes,
            "incompatible_reason": profile.incompatible_reason,
        },
        memory_notes=profile.memory_notes,
        files=files,
        last_validated_at=(db_row or {}).get("last_validated_at"),
    )


@router.get("", response_model=list[ModelProfileOut])
async def list_models(request: Request) -> list[ModelProfileOut]:
    container = _get_container(request)
    return [_profile_out(container, p) for p in container.registry.list_all()]


@router.get("/installed", response_model=list[ModelProfileOut])
async def installed_models(request: Request) -> list[ModelProfileOut]:
    container = _get_container(request)
    return [
        _profile_out(container, p) for p in container.registry.list_all()
        if container.registry.is_installed(p)
    ]


@router.post("/install", response_model=ModelInstallStatus, status_code=202)
async def install_model(req: ModelInstallRequest, request: Request) -> ModelInstallStatus:
    container = _get_container(request)
    require_safe_identifier(req.model_id, "model id")
    state = container.installer.start_install(req.model_id, req.accept_license)
    return ModelInstallStatus(**state.to_dict())


@router.get("/install/{model_id}/status", response_model=ModelInstallStatus)
async def install_status(model_id: str, request: Request) -> ModelInstallStatus:
    container = _get_container(request)
    require_safe_identifier(model_id, "model id")
    state = container.installer.status(model_id)
    return ModelInstallStatus(**state.to_dict())


@router.post("/install/{model_id}/cancel", response_model=ModelInstallStatus)
async def cancel_install(model_id: str, request: Request) -> ModelInstallStatus:
    container = _get_container(request)
    require_safe_identifier(model_id, "model id")
    container.installer.cancel(model_id)
    state = container.installer.status(model_id)
    return ModelInstallStatus(**state.to_dict())


@router.post("/validate", response_model=ModelValidateResult)
async def validate_model(request: Request, model_id: str) -> ModelValidateResult:
    container = _get_container(request)
    require_safe_identifier(model_id, "model id")
    result = container.installer.validate(model_id)
    return ModelValidateResult(
        model_id=result["model_id"], valid=result["valid"], note=result["note"],
        files=[ModelFileInfo(**f) for f in result["files"]],
    )


@router.delete("/{model_id}")
async def delete_model(model_id: str, request: Request,
                       body: ModelDeleteRequest | None = None) -> dict:
    container = _get_container(request)
    require_safe_identifier(model_id, "model id")
    if body is None or body.confirm_model_id != model_id:
        raise NovaError(
            ErrorCode.VALIDATION_ERROR,
            "Deletion requires confirm_model_id to exactly match the model id.",
            http_status=422,
        )
    return container.installer.remove(model_id, body.confirm_model_id)
