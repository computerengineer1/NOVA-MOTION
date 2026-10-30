"""Generation API schemas — strict validation of every client-supplied value."""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# --- constants mirrored from the model registry / workflow capabilities -----
SUPPORTED_DURATIONS_S = (2.0, 4.0, 6.0, 8.0)   # frames = duration * 8 fps
SUPPORTED_ASPECTS = ("16:9", "9:16", "1:1")
SUPPORTED_EXPORT_FPS = (8, 16, 24)
INTERPOLATION_METHODS = ("none", "minterpolate", "rife")
GENERATION_MODES = ("auto", "native_long", "multi_shot")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class GenerationRequest(BaseModel):
    """POST /api/generations body."""

    prompt: str = Field(min_length=1, max_length=2000)
    negative_prompt: str = Field(default="", max_length=1000)
    model_id: str = Field(min_length=1, max_length=128)
    duration_seconds: float = Field(default=8.0)
    aspect_ratio: Literal["16:9", "9:16", "1:1"] = "16:9"
    resolution_id: str | None = Field(default=None, max_length=64)
    steps: int = Field(default=16, ge=4, le=40)
    cfg: float = Field(default=7.5, ge=1.0, le=15.0)
    sampler: Literal["euler", "euler_ancestral", "dpmpp_2m", "dpmpp_sde", "uni_pc"] = "dpmpp_2m"
    scheduler: Literal["normal", "karras", "exponential", "sgm_uniform"] = "karras"
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)
    random_seed: bool = True
    generation_mode: Literal["auto", "native_long", "multi_shot"] = "auto"
    export_fps: Literal[8, 16, 24] = 8
    interpolation: Literal["none", "minterpolate", "rife"] = "none"
    upscale_export: bool = False

    @field_validator("prompt", "negative_prompt")
    @classmethod
    def _strip_control(cls, v: str) -> str:
        cleaned = _CONTROL_CHARS.sub(" ", v).strip()
        return cleaned

    @field_validator("prompt")
    @classmethod
    def _prompt_not_blank(cls, v: str) -> str:
        if not v:
            raise ValueError("Prompt must not be blank.")
        return v

    @field_validator("duration_seconds")
    @classmethod
    def _duration_supported(cls, v: float) -> float:
        if v not in SUPPORTED_DURATIONS_S:
            raise ValueError(
                f"Duration must be one of {SUPPORTED_DURATIONS_S} seconds "
                "(8s target = 64 model frames at the model's native 8 fps)."
            )
        return v

    @field_validator("model_id")
    @classmethod
    def _model_id_safe(cls, v: str) -> str:
        if not re.match(r"^[a-z0-9][a-z0-9._-]{0,127}$", v):
            raise ValueError("Invalid model identifier.")
        return v

    @model_validator(mode="after")
    def _cross_checks(self) -> "GenerationRequest":
        if self.interpolation != "none" and self.export_fps <= 8:
            raise ValueError(
                "Interpolation requires an output frame rate above the model's "
                "native 8 fps (choose 16 or 24)."
            )
        if not self.random_seed and self.seed is None:
            raise ValueError("Provide a seed or enable random_seed.")
        return self


class EffectiveSettings(BaseModel):
    """Server-computed parameters that will actually be used."""

    width: int
    height: int
    resolution_id: str
    source_fps: int
    total_frames: int
    segments: int
    frames_per_segment: int
    context_length: int
    route: str            # native_long | multi_shot
    route_label: str      # human-readable, honest description
    export_fps: int
    interpolation: str
    upscale_export: bool
    upscale_factor: int = 1
    final_width: int = 0
    final_height: int = 0
    estimated_output_size_mb: float | None = None
    estimated_minutes_low: float | None = None
    estimated_minutes_high: float | None = None


class PreflightResult(BaseModel):
    ok: bool
    level: Literal["READY", "WARNING", "BLOCKED"]
    checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    blockers: list[str] = []
    effective: EffectiveSettings | None = None


class GenerationJobOut(BaseModel):
    id: str
    status: str
    stage_detail: str | None = None
    progress: float = 0.0
    original_prompt: str
    negative_prompt: str
    seed: int | None = None
    model_id: str
    workflow_id: str
    generation_mode: str
    effective_settings: dict[str, Any] = {}
    request: dict[str, Any] = {}   # the original accepted request (for "reuse settings")
    error: dict[str, Any] | None = None
    output: "VideoOut | None" = None
    metrics: dict[str, Any] = {}
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class VideoOut(BaseModel):
    video_id: str  # == generation id (single source of truth)
    generation_id: str
    status: str
    file_exists: bool
    prompt: str
    negative_prompt: str
    seed: int | None = None
    model_id: str
    generation_mode: str
    route_label: str | None = None
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    size_bytes: int | None = None
    codec: str | None = None
    interpolated: bool = False
    upscaled: bool = False
    created_at: str | None = None
    file_url: str | None = None
    thumbnail_url: str | None = None


class CancelResponse(BaseModel):
    id: str
    status: str
    cancel_requested: bool
    detail: str


class EnhanceRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    style_preset: str | None = Field(default=None, max_length=64)


class EnhanceResponse(BaseModel):
    enhanced_prompt: str
    method: Literal["template"]
    explanation: str
    original_preserved: bool = True


GenerationJobOut.model_rebuild()
