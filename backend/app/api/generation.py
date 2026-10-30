"""Generation endpoints: submit / list / get / cancel / preflight / prompts."""
from __future__ import annotations

import random

from fastapi import APIRouter, HTTPException, Request

from ..core.errors import ErrorCode, NovaError
from ..database.models import GenerationRecord
from ..schemas.generation import (
    CancelResponse,
    EffectiveSettings,
    EnhanceRequest,
    EnhanceResponse,
    GenerationJobOut,
    GenerationRequest,
    PreflightResult,
)
from ..services import prompt_tools
from .views import record_to_job

router = APIRouter(prefix="/api/generations", tags=["generations"])


def _get_container(request: Request):
    return request.app.state.container


def _resolve_seed(req: GenerationRequest) -> int:
    if req.random_seed or req.seed is None:
        return random.randrange(0, 2**63 - 1)
    return req.seed


@router.post("", response_model=GenerationJobOut, status_code=201)
async def submit_generation(req: GenerationRequest, request: Request) -> GenerationJobOut:
    container = _get_container(request)
    profile = container.registry.get_installable(req.model_id)

    # interpolation availability check (rife requires the optional node pack)
    if req.interpolation == "rife":
        engine_online = (await container.engines.status()).online
        node_ok = False
        if engine_online:
            try:
                info = await container.engines.adapter.fetch_object_info()
                node_ok = any(k.startswith("RIFE") or "VHS_RIFE" in k
                              for k in info.keys())
            except NovaError:
                node_ok = False
        if not node_ok:
            raise NovaError(
                ErrorCode.CUSTOM_NODE_MISSING,
                "RIFE interpolation was requested but the optional frame-interpolation "
                "node pack is not installed in the engine.",
                recovery="Use 'minterpolate' (built into FFmpeg) instead, or install "
                         "ComfyUI-Frame-Interpolation as described in the Help page.",
                http_status=409,
            )

    seed = _resolve_seed(req)
    effective = container.generation_service.compute_effective(req, profile)
    record = container.generation_service.create_record(req, effective, seed)
    try:
        container.jobs.submit(record)
    except NovaError:
        raise
    return record_to_job(record)


@router.get("", response_model=list[GenerationJobOut])
async def list_generations(request: Request, limit: int = 50, offset: int = 0) -> list[GenerationJobOut]:
    container = _get_container(request)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    records = container.generations.list(limit=limit, offset=offset)
    # merge in-memory state for the active job (fresher than DB during runs)
    out = []
    for rec in records:
        fresh = container.jobs.current_record(rec.id)
        out.append(record_to_job(fresh or rec))
    return out


@router.get("/{generation_id}", response_model=GenerationJobOut)
async def get_generation(generation_id: str, request: Request) -> GenerationJobOut:
    container = _get_container(request)
    record = container.jobs.current_record(generation_id) or container.generations.get(generation_id)
    if record is None:
        raise NovaError(ErrorCode.FILE_NOT_FOUND, f"Unknown generation '{generation_id}'.",
                        http_status=404)
    return record_to_job(record)


@router.post("/{generation_id}/cancel", response_model=CancelResponse)
async def cancel_generation(generation_id: str, request: Request) -> CancelResponse:
    container = _get_container(request)
    accepted, detail = container.jobs.request_cancel(generation_id)
    record = container.jobs.current_record(generation_id) or container.generations.get(generation_id)
    return CancelResponse(
        id=generation_id,
        status=record.status if record else "UNKNOWN",
        cancel_requested=accepted,
        detail=detail,
    )


@router.post("/preflight", response_model=PreflightResult)
async def preflight(req: GenerationRequest, request: Request) -> PreflightResult:
    """Dry-run of every check that would run before generation, without queuing."""
    container = _get_container(request)
    profile = container.registry.get_installable(req.model_id)
    seed = _resolve_seed(req)
    effective = container.generation_service.compute_effective(req, profile)
    temp = GenerationRecord(
        id="preflight", status="QUEUED", original_prompt=req.prompt,
        negative_prompt=req.negative_prompt, model_id=req.model_id,
        workflow_id="animatediff_t2v", generation_mode=effective["route"],
        seed=seed, configuration={"request": req.model_dump(), "effective": effective},
    )
    result = await container.generation_service.preflight(temp)
    running = container.jobs.queue_state()["running_job_id"] is not None
    if running:
        result["level"] = "BLOCKED"
        result["ok"] = False
        result["blockers"].append("Another generation is currently running (sequential-only policy).")
    return PreflightResult(**result, effective=EffectiveSettings(**effective))


@router.get("/meta/presets")
async def presets() -> dict:
    return {"presets": prompt_tools.list_presets(),
            "examples": prompt_tools.list_examples(),
            "default_negative_prompt": prompt_tools.DEFAULT_NEGATIVE_PROMPT}


@router.post("/meta/enhance", response_model=EnhanceResponse)
async def enhance(req: EnhanceRequest) -> EnhanceResponse:
    try:
        result = prompt_tools.enhance(req.prompt, req.style_preset)
    except ValueError as exc:
        raise NovaError(ErrorCode.VALIDATION_ERROR, str(exc), http_status=422)
    return EnhanceResponse(
        enhanced_prompt=result["enhanced_prompt"],
        method="template",
        explanation=result["explanation"] + " Added: " + ", ".join(result["added_tokens"][:12])
        + ("…" if len(result["added_tokens"]) > 12 else ""),
        original_preserved=True,
    )
