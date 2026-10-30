"""Thumbnail extraction from the final validated MP4."""
from __future__ import annotations

from pathlib import Path

from ..core.errors import ErrorCode, NovaError
from ..logging_config import get_logger
from .ffmpeg import FFmpegService

log = get_logger(__name__)


class ThumbnailService:
    def __init__(self, ffmpeg: FFmpegService) -> None:
        self.ffmpeg = ffmpeg

    async def create(self, video_path: Path, thumb_path: Path,
                     duration_s: float = 8.0) -> bool:
        """Extract one frame. Returns False (never raises) — a missing
        thumbnail must not fail an otherwise valid generation."""
        try:
            if not video_path.is_file():
                return False
            ts = min(1.0, max(0.1, duration_s * 0.15))
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            await self.ffmpeg.run(
                [
                    self.ffmpeg.info()["ffmpeg_path"],
                    "-y", "-ss", f"{ts:.3f}", "-i", str(video_path),
                    "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "3",
                    str(thumb_path),
                ],
                timeout=120, log_label="thumbnail",
            )
            return thumb_path.is_file() and thumb_path.stat().st_size > 0
        except (NovaError, OSError) as exc:
            log.warning("Thumbnail generation failed for %s: %s", video_path.name,
                        getattr(exc, "summary", exc))
            return False
