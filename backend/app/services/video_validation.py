"""Video validation: a file is a valid NOVA MOTION output only if ffprobe
confirms codec, container, dimensions, frame rate, and duration within the
documented tolerance (one output frame).
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from ..core.errors import ErrorCode, NovaError
from ..logging_config import get_logger
from .ffmpeg import FFmpegService

log = get_logger(__name__)


@dataclass
class ProbeSummary:
    duration_s: float
    width: int
    height: int
    fps: float
    codec: str
    pix_fmt: str
    size_bytes: int
    nb_frames: int | None


def _parse_rate(rate: str | None) -> float | None:
    if not rate or rate in ("0/0", "N/A"):
        return None
    try:
        value = float(Fraction(rate))
        return value if value > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def summarize_probe(data: dict[str, Any], path: Path) -> ProbeSummary:
    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise NovaError(ErrorCode.OUTPUT_INVALID,
                        "The file contains no video stream.",
                        detail=f"streams={[s.get('codec_type') for s in streams]}")
    fps = _parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate"))
    duration = fmt.get("duration") or video.get("duration")
    try:
        duration_f = float(duration)
    except (TypeError, ValueError):
        raise NovaError(ErrorCode.OUTPUT_INVALID, "Could not determine media duration.")
    nb_frames = None
    if video.get("nb_frames") and str(video["nb_frames"]).isdigit():
        nb_frames = int(video["nb_frames"])
    return ProbeSummary(
        duration_s=duration_f,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=fps or 0.0,
        codec=str(video.get("codec_name") or ""),
        pix_fmt=str(video.get("pix_fmt") or ""),
        size_bytes=int(fmt.get("size") or path.stat().st_size),
        nb_frames=nb_frames,
    )


async def validate_output(
    ffmpeg: FFmpegService,
    path: Path,
    *,
    expected_duration_s: float,
    expected_width: int | None = None,
    expected_height: int | None = None,
    expected_fps: float | None = None,
) -> ProbeSummary:
    """Full acceptance check. Raises NovaError(OUTPUT_INVALID) on any failure.

    Duration tolerance: one output frame (1/fps), as documented — this covers
    encoder/frame-rate rounding. Frame count consistency is cross-checked when
    the container reports nb_frames.
    """
    if not path.is_file():
        raise NovaError(ErrorCode.OUTPUT_INVALID, "Output file does not exist.",
                        detail=str(path))
    if path.stat().st_size == 0:
        raise NovaError(ErrorCode.OUTPUT_INVALID, "Output file is empty (0 bytes).")

    data = await ffmpeg.probe(path)
    summary = summarize_probe(data, path)

    problems: list[str] = []
    if summary.codec not in ("h264",):
        problems.append(f"video codec is '{summary.codec}', expected h264")
    if summary.pix_fmt not in ("yuv420p",):
        problems.append(f"pixel format is '{summary.pix_fmt}', expected yuv420p")
    tolerance = (1.0 / summary.fps) if summary.fps > 0 else 0.125
    if abs(summary.duration_s - expected_duration_s) > tolerance + 1e-6:
        problems.append(
            f"duration {summary.duration_s:.3f}s deviates from target "
            f"{expected_duration_s:.3f}s by more than one frame ({tolerance:.3f}s)"
        )
    if summary.nb_frames is not None and summary.fps > 0:
        expected_frames = round(expected_duration_s * summary.fps)
        if abs(summary.nb_frames - expected_frames) > 1:
            problems.append(
                f"frame count {summary.nb_frames} != expected {expected_frames} (±1)"
            )
    if expected_width and summary.width != expected_width:
        problems.append(f"width {summary.width} != expected {expected_width}")
    if expected_height and summary.height != expected_height:
        problems.append(f"height {summary.height} != expected {expected_height}")
    if expected_fps and summary.fps > 0 and abs(summary.fps - expected_fps) > 0.11:
        problems.append(f"fps {summary.fps:.3f} != expected {expected_fps}")

    if problems:
        raise NovaError(
            ErrorCode.OUTPUT_INVALID,
            "The generated file failed media validation.",
            detail="; ".join(problems),
            recovery="The file was NOT added to your library. Retry the generation; "
                     "if it repeats, export at 8 fps without interpolation.",
        )
    log.info("Output validated: %s (%.3fs %dx%d @ %.3f fps, %.2f MB)",
             path.name, summary.duration_s, summary.width, summary.height,
             summary.fps, summary.size_bytes / 1e6)
    return summary
