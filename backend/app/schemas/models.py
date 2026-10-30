"""Model-management API schemas."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ModelFileInfo(BaseModel):
    id: str
    dest: str                     # relative path under the ComfyUI root
    size_bytes: int
    url: str
    sha256: str | None = None
    required: bool = True
    installed: bool = False
    actual_size_bytes: int | None = None
    checksum_ok: bool | None = None


class ModelProfileOut(BaseModel):
    model_id: str
    name: str
    model_type: str
    adapter: str
    status: Literal["recommended", "supported", "experimental", "incompatible"]
    license_id: str
    license_url: str | None = None
    source: str
    version: str | None = None
    total_download_bytes: int
    installed: bool = False
    install_progress: float | None = None
    validation_status: str = "unknown"
    validation_note: str | None = None
    compatibility: dict[str, Any] = {}
    capabilities: dict[str, Any] = {}
    memory_notes: str | None = None
    files: list[ModelFileInfo] = []
    last_validated_at: str | None = None


class ModelInstallRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=128)
    accept_license: bool = False


class ModelInstallStatus(BaseModel):
    model_id: str
    state: Literal[
        "idle", "starting", "downloading", "verifying", "completed", "failed", "cancelled"
    ]
    current_file: str | None = None
    file_index: int = 0
    file_count: int = 0
    bytes_done: int = 0
    bytes_total: int = 0
    percent: float = 0.0
    error: dict[str, Any] | None = None
    started_at: str | None = None
    finished_at: str | None = None


class ModelValidateResult(BaseModel):
    model_id: str
    valid: bool
    files: list[ModelFileInfo] = []
    note: str | None = None


class ModelDeleteRequest(BaseModel):
    confirm_model_id: str = Field(min_length=1, max_length=128)


class SettingsPatch(BaseModel):
    """Only whitelisted keys may be patched; unknown keys are rejected."""

    values: dict[str, Any] = Field(default_factory=dict)
