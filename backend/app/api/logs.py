"""Log inspection + sanitized diagnostic export.

Privacy: exports minimize personal data by design — prompts are replaced by
their length + SHA256 prefix, absolute user paths are shortened to project-
relative paths, and token-shaped strings are redacted.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request

from .health import BACKEND_VERSION, system_report

router = APIRouter(prefix="/api/logs", tags=["logs"])

_REDACT_PATTERNS = [
    re.compile(r"hf_[A-Za-z0-9]{16,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),
    re.compile(r"(api[_-]?key|token|secret|password)\s*[=:]\s*\S+", re.IGNORECASE),
]


def sanitize(text: str, project_root: Path) -> str:
    out = text
    for pattern in _REDACT_PATTERNS:
        out = pattern.sub("[REDACTED]", out)
    try:
        root_str = str(project_root)
        out = out.replace(root_str, "<NOVA_HOME>")
        out = out.replace(root_str.replace("\\", "/"), "<NOVA_HOME>")
    except Exception:  # noqa: BLE001
        pass
    return out


def _tail(path: Path, lines: int, project_root: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            block = 64 * 1024
            data = b""
            while size > 0 and data.count(b"\n") <= lines:
                read_size = min(block, size)
                size -= read_size
                fh.seek(size)
                data = fh.read(read_size) + data
        text = data.decode(errors="replace")
        tail = text.splitlines()[-lines:]
        return [sanitize(line, project_root) for line in tail]
    except OSError:
        return []


def _get_container(request: Request):
    return request.app.state.container


@router.get("/app")
async def app_logs(request: Request, lines: int = 200) -> dict:
    container = _get_container(request)
    lines = max(1, min(lines, 2000))
    return {
        "path": "logs/nova-backend.log",
        "lines": _tail(container.settings.logs_dir / "nova-backend.log", lines,
                       container.settings.project_root),
    }


@router.get("/engine")
async def engine_logs(request: Request, lines: int = 200) -> dict:
    container = _get_container(request)
    lines = max(1, min(lines, 2000))
    return {
        "path": "logs/engine_comfyui.log",
        "lines": _tail(container.settings.logs_dir / "engine_comfyui.log", lines,
                       container.settings.project_root),
    }


@router.get("/diagnostic")
async def diagnostic(request: Request, lines: int = 120) -> dict:
    """Sanitized diagnostic bundle for troubleshooting/sharing."""
    container = _get_container(request)
    report = await system_report(request)
    recent = []
    for rec in container.generations.list(limit=20):
        recent.append({
            "id": rec.id,
            "status": rec.status,
            "model_id": rec.model_id,
            "mode": rec.generation_mode,
            "prompt_fingerprint": hashlib.sha256(
                rec.original_prompt.encode("utf-8")).hexdigest()[:12],
            "prompt_length": len(rec.original_prompt),
            "error_code": rec.error_code,
            "error_summary": rec.safe_error_summary,
            "duration_s": rec.actual_duration_seconds,
            "resolution": [rec.actual_width, rec.actual_height],
            "created_at": rec.created_at,
        })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "backend_version": BACKEND_VERSION,
        "system": report.model_dump(),
        "recent_generations": recent,
        "app_log_tail": _tail(container.settings.logs_dir / "nova-backend.log", lines,
                              container.settings.project_root),
        "engine_log_tail": _tail(container.settings.logs_dir / "engine_comfyui.log", lines,
                                 container.settings.project_root),
        "note": "Prompts are represented only by length + fingerprint. "
                "Absolute paths are shortened. Token-shaped strings are redacted.",
    }
