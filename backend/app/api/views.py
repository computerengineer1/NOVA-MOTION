"""Record -> API view conversion (shared by generation + video endpoints)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..database.models import GenerationRecord
from ..schemas.generation import GenerationJobOut, VideoOut


def record_to_job(record: GenerationRecord) -> GenerationJobOut:
    error = None
    if record.error_code:
        error = {
            "code": record.error_code,
            "summary": record.safe_error_summary or "Generation failed.",
            "recovery": record.error_recovery,
            "log_reference": record.error_detail_log_ref,
            "retryable": record.error_code not in ("JOB_CANCELLED",),
        }
    output = None
    if record.status == "COMPLETED" and record.output_path:
        output = record_to_video(record)
    return GenerationJobOut(
        id=record.id,
        status=record.status,
        stage_detail=record.stage_detail,
        progress=record.progress,
        original_prompt=record.original_prompt,
        negative_prompt=record.negative_prompt,
        seed=record.seed,
        model_id=record.model_id,
        workflow_id=record.workflow_id,
        generation_mode=record.generation_mode,
        effective_settings=record.configuration.get("effective", {}),
        request=record.configuration.get("request", {}),
        error=error,
        output=output,
        metrics=record.metrics or {},
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
    )


def record_to_video(record: GenerationRecord) -> VideoOut:
    out_path = Path(record.output_path) if record.output_path else None
    file_exists = bool(out_path and out_path.is_file())
    effective = record.configuration.get("effective", {}) if record.configuration else {}
    deleted = bool((record.metrics or {}).get("output_deleted"))
    return VideoOut(
        video_id=record.id,
        generation_id=record.id,
        status="DELETED" if deleted else record.status,
        file_exists=file_exists,
        prompt=record.original_prompt,
        negative_prompt=record.negative_prompt,
        seed=record.seed,
        model_id=record.model_id,
        generation_mode=record.generation_mode,
        route_label=effective.get("route_label"),
        duration_seconds=record.actual_duration_seconds,
        width=record.actual_width,
        height=record.actual_height,
        fps=record.actual_fps,
        size_bytes=record.output_size_bytes,
        codec=record.output_codec,
        interpolated=bool(record.interpolated),
        upscaled=bool(record.upscaled),
        created_at=record.created_at,
        file_url=f"/api/videos/{record.id}/file" if record.output_path else None,
        thumbnail_url=f"/api/videos/{record.id}/thumbnail"
        if record.thumbnail_path else None,
    )


def job_to_dict(record: GenerationRecord) -> dict[str, Any]:
    return record_to_job(record).model_dump()
