"""Path security: every filesystem operation goes through these helpers.

Rules enforced here:
  * resolved paths must stay inside an allowed root (no traversal),
  * symlinks are resolved before the containment check,
  * filenames supplied by clients may never contain separators,
  * deletions only ever touch files inside application-owned directories.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .errors import ErrorCode, NovaError

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def is_safe_identifier(value: str) -> bool:
    """True for job ids, model ids, video ids we generate or accept."""
    return bool(value) and bool(_SAFE_ID_RE.match(value))


def require_safe_identifier(value: str, what: str = "identifier") -> str:
    if not is_safe_identifier(value):
        raise NovaError(
            ErrorCode.VALIDATION_ERROR,
            f"Invalid {what}.",
            detail=f"Rejected value: {value!r}",
            http_status=422,
        )
    return value


def safe_subpath(root: Path, *parts: str) -> Path:
    """Join `parts` under `root`, guaranteeing the result stays inside root.

    Rejects absolute parts, drive letters, '..' traversal, and NULs.
    """
    root_resolved = root.resolve()
    candidate = root_resolved
    for part in parts:
        if part is None:
            raise NovaError(ErrorCode.PATH_SECURITY, "Invalid path component.")
        if "\x00" in part:
            raise NovaError(ErrorCode.PATH_SECURITY, "Invalid path component.")
        p = part.replace("\\", "/")
        if p.startswith("/") or re.match(r"^[A-Za-z]:", p):
            raise NovaError(
                ErrorCode.PATH_SECURITY,
                "Absolute paths are not permitted here.",
                http_status=422,
            )
        candidate = candidate / p
    resolved = candidate.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise NovaError(
            ErrorCode.PATH_SECURITY,
            "Path escapes the permitted application directory.",
            detail=f"root={root_resolved} resolved={resolved}",
            http_status=422,
        )
    return resolved


def assert_within(root: Path, path: Path) -> Path:
    """Assert `path` (arbitrary) resolves inside `root`; return resolved path."""
    root_resolved = root.resolve()
    resolved = path.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise NovaError(
            ErrorCode.PATH_SECURITY,
            "Operation refused: target is outside the application directory.",
            detail=f"root={root_resolved} target={resolved}",
            http_status=403,
        )
    return resolved


def atomic_write_bytes(target: Path, data: bytes) -> None:
    """Write bytes via a temp file + rename (never leaves partial content)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, target)
