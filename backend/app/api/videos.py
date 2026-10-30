"""Video library endpoints: list / get / stream (HTTP Range) / thumbnail /
delete / reveal-in-explorer / open outputs folder.

Security:
  * IDs come from the DB; filesystem paths are never accepted from clients.
  * Served files must resolve inside outputs/ or thumbnails/.
  * Reveal/Open use fixed commands with argument arrays; only DB-registered,
    containment-checked paths are ever passed to the OS.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from fastapi import APIRouter, Header, Request, Response
from starlette.responses import FileResponse

from ..core.errors import ErrorCode, NovaError
from ..core.path_security import assert_within, require_safe_identifier
from ..schemas.common import OkResponse
from ..schemas.generation import VideoOut
from .views import record_to_video

router = APIRouter(prefix="/api/videos", tags=["videos"])

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def _get_container(request: Request):
    return request.app.state.container


def _load_record(container, video_id: str):
    require_safe_identifier(video_id, "video id")
    record = container.generations.get(video_id)
    if record is None:
        raise NovaError(ErrorCode.FILE_NOT_FOUND, f"Unknown video '{video_id}'.",
                        http_status=404)
    return record


@router.get("", response_model=list[VideoOut])
async def list_videos(
    request: Request,
    q: str | None = None,
    model_id: str | None = None,
    sort: str = "newest",
    limit: int = 100,
    offset: int = 0,
) -> list[VideoOut]:
    container = _get_container(request)
    records = container.generations.list(limit=500, offset=0)
    videos = []
    for rec in records:
        # A library entry = any generation that produced (or once produced) an output.
        has_output = rec.output_path is not None
        deleted = bool((rec.metrics or {}).get("output_deleted"))
        if not (has_output or deleted):
            continue
        if q:
            needle = q.lower()
            if needle not in rec.original_prompt.lower():
                continue
        if model_id and rec.model_id != model_id:
            continue
        videos.append(record_to_video(rec))
    reverse = sort in ("newest", "duration_desc", "size_desc")
    keymap = {
        "newest": lambda v: v.created_at or "",
        "oldest": lambda v: v.created_at or "",
        "duration": lambda v: v.duration_seconds or 0,
        "duration_desc": lambda v: v.duration_seconds or 0,
        "size": lambda v: v.size_bytes or 0,
        "size_desc": lambda v: v.size_bytes or 0,
    }
    key = keymap.get(sort, keymap["newest"])
    videos.sort(key=key, reverse=reverse)
    return videos[max(0, offset): max(0, offset) + max(1, min(limit, 200))]


@router.get("/{video_id}", response_model=VideoOut)
async def get_video(video_id: str, request: Request) -> VideoOut:
    container = _get_container(request)
    record = _load_record(container, video_id)
    if record.output_path is None and not (record.metrics or {}).get("output_deleted"):
        raise NovaError(ErrorCode.FILE_NOT_FOUND,
                        "This generation has no output file (it may have failed).",
                        http_status=404)
    return record_to_video(record)


def _resolve_media(container, video_id: str, kind: str) -> Path:
    record = _load_record(container, video_id)
    raw = record.output_path if kind == "file" else record.thumbnail_path
    if not raw:
        raise NovaError(ErrorCode.FILE_NOT_FOUND, f"No {kind} exists for this video.",
                        http_status=404)
    path = Path(raw)
    root = container.settings.outputs_dir if kind == "file" else container.settings.thumbnails_dir
    assert_within(root, path)
    if not path.is_file():
        raise NovaError(
            ErrorCode.FILE_NOT_FOUND,
            "The output file is missing on disk (it may have been moved or deleted "
            "outside NOVA MOTION).",
            detail=str(path),
            recovery="The metadata record is preserved. Regenerate if you need the video.",
            http_status=410,
        )
    return path


@router.get("/{video_id}/file")
async def get_video_file(video_id: str, request: Request,
                         range_header: str | None = Header(default=None, alias="Range")) -> Response:
    container = _get_container(request)
    path = _resolve_media(container, video_id, "file")
    file_size = path.stat().st_size
    media_type = "video/mp4"

    if range_header:
        match = _RANGE_RE.match(range_header.strip())
        if match:
            start_s, end_s = match.group(1), match.group(2)
            start = int(start_s) if start_s else 0
            end = int(end_s) if end_s else file_size - 1
            if start_s == "" and end_s != "":  # suffix range: bytes=-N
                start = max(0, file_size - end)
                end = file_size - 1
            end = min(end, file_size - 1)
            if start <= end < file_size:
                length = end - start + 1

                def _iter():
                    with path.open("rb") as fh:
                        fh.seek(start)
                        remaining = length
                        while remaining > 0:
                            chunk = fh.read(min(256 * 1024, remaining))
                            if not chunk:
                                break
                            remaining -= len(chunk)
                            yield chunk

                from starlette.responses import StreamingResponse
                return StreamingResponse(
                    _iter(), status_code=206, media_type=media_type,
                    headers={
                        "Content-Range": f"bytes {start}-{end}/{file_size}",
                        "Accept-Ranges": "bytes",
                        "Content-Length": str(length),
                        "Cache-Control": "no-store",
                    },
                )
    return FileResponse(path, media_type=media_type, filename=path.name,
                        headers={"Accept-Ranges": "bytes", "Cache-Control": "no-store"})


@router.get("/{video_id}/thumbnail")
async def get_thumbnail(video_id: str, request: Request) -> Response:
    container = _get_container(request)
    path = _resolve_media(container, video_id, "thumbnail")
    return FileResponse(path, media_type="image/jpeg", filename=path.name,
                        headers={"Cache-Control": "no-store"})


@router.delete("/{video_id}", response_model=OkResponse)
async def delete_video(video_id: str, request: Request) -> OkResponse:
    """Delete output + thumbnail files. Metadata is kept (marked deleted) so
    history remains consistent — a record is never silently rewritten."""
    container = _get_container(request)
    record = _load_record(container, video_id)
    deleted = []
    for raw, root in ((record.output_path, container.settings.outputs_dir),
                      (record.thumbnail_path, container.settings.thumbnails_dir)):
        if raw:
            path = assert_within(root, Path(raw))
            if path.is_file():
                path.unlink()
                deleted.append(path.name)
    metrics = dict(record.metrics or {})
    metrics["output_deleted"] = True
    import json as _json
    container.generations.update(video_id, metrics_json=_json.dumps(metrics),
                                 output_path=None, thumbnail_path=None)
    return OkResponse(ok=True, detail=f"Deleted {len(deleted)} file(s): {', '.join(deleted) or 'none'}.")


@router.post("/{video_id}/reveal", response_model=OkResponse)
async def reveal_in_explorer(video_id: str, request: Request) -> OkResponse:
    """Open the OS file manager and select the video. The path comes ONLY from
    the DB record and must resolve inside outputs/. No client-supplied paths,
    no shell, fixed argument arrays."""
    container = _get_container(request)
    path = _resolve_media(container, video_id, "file")
    try:
        if os.name == "nt":
            subprocess.Popen(["explorer", f"/select,{path}"])
        elif os.uname().sysname == "Darwin":  # type: ignore[attr-defined]
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
    except OSError as exc:
        raise NovaError(ErrorCode.INTERNAL, "Could not launch the system file manager.",
                        detail=str(exc), http_status=500)
    return OkResponse(ok=True, detail=f"Revealed {path.name} in the file manager.")


@router.post("/folder/open", response_model=OkResponse)
async def open_outputs_folder(request: Request) -> OkResponse:
    """Opens the fixed outputs directory — takes no parameters by design."""
    container = _get_container(request)
    folder = container.settings.outputs_dir.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    try:
        if os.name == "nt":
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif os.uname().sysname == "Darwin":  # type: ignore[attr-defined]
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except OSError as exc:
        raise NovaError(ErrorCode.INTERNAL, "Could not open the outputs folder.",
                        detail=str(exc), http_status=500)
    return OkResponse(ok=True, detail=str(folder))
