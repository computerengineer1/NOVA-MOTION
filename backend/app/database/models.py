"""Job state machine and row dataclasses."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    PREFLIGHT = "PREFLIGHT"
    INITIALIZING = "INITIALIZING"
    GENERATING = "GENERATING"
    ASSEMBLING = "ASSEMBLING"
    INTERPOLATING = "INTERPOLATING"  # only entered when interpolation selected
    ENCODING = "ENCODING"
    VALIDATING = "VALIDATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


ACTIVE_STATUSES = frozenset(
    {
        JobStatus.QUEUED,
        JobStatus.PREFLIGHT,
        JobStatus.INITIALIZING,
        JobStatus.GENERATING,
        JobStatus.ASSEMBLING,
        JobStatus.INTERPOLATING,
        JobStatus.ENCODING,
        JobStatus.VALIDATING,
    }
)

TERMINAL_STATUSES = frozenset({JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED})

# Legal transitions; the job manager enforces them.
TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.PREFLIGHT, JobStatus.CANCELLED, JobStatus.FAILED}),
    JobStatus.PREFLIGHT: frozenset({JobStatus.INITIALIZING, JobStatus.FAILED, JobStatus.CANCELLED}),
    JobStatus.INITIALIZING: frozenset({JobStatus.GENERATING, JobStatus.FAILED, JobStatus.CANCELLED}),
    JobStatus.GENERATING: frozenset(
        {JobStatus.ASSEMBLING, JobStatus.GENERATING, JobStatus.FAILED, JobStatus.CANCELLED}
    ),
    JobStatus.ASSEMBLING: frozenset(
        {JobStatus.INTERPOLATING, JobStatus.ENCODING, JobStatus.FAILED, JobStatus.CANCELLED}
    ),
    JobStatus.INTERPOLATING: frozenset({JobStatus.ENCODING, JobStatus.FAILED, JobStatus.CANCELLED}),
    JobStatus.ENCODING: frozenset({JobStatus.VALIDATING, JobStatus.FAILED, JobStatus.CANCELLED}),
    JobStatus.VALIDATING: frozenset({JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}


def can_transition(src: JobStatus | str, dst: JobStatus | str) -> bool:
    try:
        return dst in TRANSITIONS[JobStatus(src)]
    except (KeyError, ValueError):
        return False


@dataclass
class GenerationRecord:
    id: str
    status: str
    original_prompt: str
    negative_prompt: str
    model_id: str
    workflow_id: str
    generation_mode: str
    configuration: dict[str, Any] = field(default_factory=dict)
    engine_job_ids: list[str] = field(default_factory=list)
    seed: int | None = None
    stage_detail: str | None = None
    progress: float = 0.0
    output_path: str | None = None
    thumbnail_path: str | None = None
    actual_duration_seconds: float | None = None
    actual_width: int | None = None
    actual_height: int | None = None
    actual_fps: float | None = None
    output_size_bytes: int | None = None
    output_codec: str | None = None
    interpolated: bool = False
    upscaled: bool = False
    error_code: str | None = None
    safe_error_summary: str | None = None
    error_recovery: str | None = None
    error_detail_log_ref: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
