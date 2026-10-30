"""Central error taxonomy.

Every failure surfaced to the UI uses one of these codes with a *safe* summary
(no stack traces, no filesystem internals beyond what the user needs).
Full detail always goes to the application log.
"""
from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    # Engine / runtime
    ENGINE_UNREACHABLE = "ENGINE_UNREACHABLE"
    ENGINE_FAILED_TO_START = "ENGINE_FAILED_TO_START"
    ENGINE_TIMEOUT = "ENGINE_TIMEOUT"
    ENGINE_EXECUTION_ERROR = "ENGINE_EXECUTION_ERROR"
    CUDA_UNAVAILABLE = "CUDA_UNAVAILABLE"

    # Models / workflows
    MODEL_NOT_INSTALLED = "MODEL_NOT_INSTALLED"
    MODEL_FILE_MISSING = "MODEL_FILE_MISSING"
    MODEL_FILE_CORRUPT = "MODEL_FILE_CORRUPT"
    MODEL_LICENSE_NOT_ACCEPTED = "MODEL_LICENSE_NOT_ACCEPTED"
    WORKFLOW_INVALID = "WORKFLOW_INVALID"
    CUSTOM_NODE_MISSING = "CUSTOM_NODE_MISSING"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    DOWNLOAD_INTERRUPTED = "DOWNLOAD_INTERRUPTED"

    # Resources
    GPU_OUT_OF_MEMORY = "GPU_OUT_OF_MEMORY"
    CPU_OUT_OF_MEMORY = "CPU_OUT_OF_MEMORY"
    INSUFFICIENT_RAM = "INSUFFICIENT_RAM"
    INSUFFICIENT_DISK = "INSUFFICIENT_DISK"

    # Media pipeline
    FFMPEG_MISSING = "FFMPEG_MISSING"
    ENCODE_FAILED = "ENCODE_FAILED"
    OUTPUT_INVALID = "OUTPUT_INVALID"
    THUMBNAIL_FAILED = "THUMBNAIL_FAILED"

    # Jobs
    JOB_CANCELLED = "JOB_CANCELLED"
    QUEUE_FULL = "QUEUE_FULL"
    INTERRUPTED_RESTART = "INTERRUPTED_RESTART"

    # Persistence / misc
    DATABASE_WRITE_FAILED = "DATABASE_WRITE_FAILED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    PATH_SECURITY = "PATH_SECURITY"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    INTERNAL = "INTERNAL"


class NovaError(Exception):
    """Application error with a stable code and a user-safe summary."""

    def __init__(
        self,
        code: ErrorCode | str,
        summary: str,
        *,
        detail: str | None = None,
        recovery: str | None = None,
        retryable: bool = False,
        http_status: int = 400,
    ) -> None:
        super().__init__(summary)
        self.code = str(code)
        self.summary = summary
        self.detail = detail          # logged, not shown verbatim in UI
        self.recovery = recovery      # suggested safe user action
        self.retryable = retryable
        self.http_status = http_status

    def to_public_dict(self) -> dict:
        return {
            "code": self.code,
            "summary": self.summary,
            "recovery": self.recovery,
            "retryable": self.retryable,
        }


# Heuristics to classify raw engine error text into our taxonomy.
_OOM_SIGNATURES = (
    "out of memory",
    "oom",
    "cuda error: out_of_memory",
    "cublas error: out_of_memory",
    "not enough memory",
)


def classify_engine_error(raw: str) -> tuple[str, str, str | None]:
    """Map raw engine error text -> (code, safe summary, recovery hint)."""
    low = raw.lower()
    if any(sig in low for sig in _OOM_SIGNATURES):
        if "cuda" in low or "gpu" in low or "vram" in low:
            return (
                ErrorCode.GPU_OUT_OF_MEMORY,
                "The GPU ran out of memory (4 GB dedicated VRAM is fully used).",
                "Try a lower resolution preset, fewer steps, or Multi-shot mode. "
                "Close other GPU applications (browser hardware acceleration, games).",
            )
        return (
            ErrorCode.CPU_OUT_OF_MEMORY,
            "The system ran out of memory (8 GB total RAM is a hard limit here).",
            "Close other applications (especially browser tabs) and retry. "
            "Consider Multi-shot mode which holds fewer frames at once.",
        )
    if "no module named" in low or "custom node" in low:
        return (
            ErrorCode.CUSTOM_NODE_MISSING,
            "A required ComfyUI custom node is missing or failed to import.",
            "Run scripts/Repair-Environment.ps1, then check logs/engine_comfyui.log.",
        )
    if "value not in list" in low or "checkpoint" in low and "not" in low:
        return (
            ErrorCode.MODEL_FILE_MISSING,
            "A model file required by the workflow was not found by the engine.",
            "Open the Models page and validate/reinstall the selected model.",
        )
    return (
        ErrorCode.ENGINE_EXECUTION_ERROR,
        "The inference engine reported an execution error.",
        "See logs/engine_comfyui.log for engine-side detail, then retry.",
    )
