"""Video assembly: PNG frame sequences -> validated MP4.

All operations are explicit and honestly labeled:
  * segment encode        (frames at the model's native fps)
  * concat                (multi-shot mode only; -c copy between identically
                           encoded segments, no hidden re-generation)
  * minterpolate          (conventional motion-compensated interpolation,
                           NOT generative — cannot invent new events)
  * lanczos upscale       (conventional resize, NOT AI super-resolution)
  * final encode          (H.264, yuv420p, exact fps, exact frame count,
                           +faststart for browser playback)
"""
from __future__ import annotations

import shutil
from pathlib import Path

from ..core.errors import ErrorCode, NovaError
from ..logging_config import get_logger
from .ffmpeg import FFmpegService

log = get_logger(__name__)

# Intermediate quality (transcoded once more at the end)
CRF_INTERMEDIATE = "16"
CRF_FINAL = "18"


class VideoAssemblyService:
    def __init__(self, ffmpeg: FFmpegService) -> None:
        self.ffmpeg = ffmpeg

    # -------------------------------------------------------------- helpers
    @staticmethod
    def count_frames(frames_dir: Path, stem: str) -> list[Path]:
        return sorted(frames_dir.glob(f"{stem}_*_.png"))

    async def encode_frames(
        self, frames_dir: Path, stem: str, out_path: Path, *,
        fps: int, expected_frames: int, crf: str = CRF_INTERMEDIATE,
    ) -> int:
        """Encode a SaveImage PNG sequence (%05d_ pattern) to H.264."""
        frames = self.count_frames(frames_dir, stem)
        if len(frames) != expected_frames:
            raise NovaError(
                ErrorCode.OUTPUT_INVALID,
                f"The engine produced {len(frames)} frames but {expected_frames} were expected.",
                recovery="This is usually a cancelled or failed engine run. Retry the generation.",
            )
        if len(frames) == 0:
            raise NovaError(ErrorCode.OUTPUT_INVALID, "No frames were produced by the engine.")
        pattern = str(frames_dir / f"{stem}_%05d_.png")
        await self.ffmpeg.run(
            [
                self.ffmpeg.info()["ffmpeg_path"],
                "-y", "-framerate", str(fps), "-start_number", "1",
                "-i", pattern,
                "-c:v", "libx264", "-preset", "medium", "-crf", crf,
                "-pix_fmt", "yuv420p", "-r", str(fps),
                "-frames:v", str(len(frames)),
                str(out_path),
            ],
            timeout=900, log_label="encode_frames",
        )
        if not out_path.is_file() or out_path.stat().st_size == 0:
            raise NovaError(ErrorCode.ENCODE_FAILED, "Frame encoding produced no output file.")
        return len(frames)

    async def concat_segments(self, segment_paths: list[Path], out_path: Path) -> None:
        """Concat identically-encoded segments via the concat demuxer (-c copy)."""
        if len(segment_paths) == 1:
            shutil.copyfile(segment_paths[0], out_path)
            return
        list_file = out_path.with_suffix(".txt")
        lines = []
        for p in segment_paths:
            if not p.is_file():
                raise NovaError(ErrorCode.ENCODE_FAILED,
                                "A segment file vanished before concatenation.",
                                detail=str(p))
            escaped = str(p.resolve()).replace("\\", "/").replace("'", r"'\''")
            lines.append(f"file '{escaped}'")
        list_file.write_text("\n".join(lines), encoding="utf-8")
        try:
            await self.ffmpeg.run(
                [
                    self.ffmpeg.info()["ffmpeg_path"],
                    "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
                    "-c", "copy", str(out_path),
                ],
                timeout=600, log_label="concat",
            )
        finally:
            list_file.unlink(missing_ok=True)
        if not out_path.is_file() or out_path.stat().st_size == 0:
            raise NovaError(ErrorCode.ENCODE_FAILED, "Concatenation produced no output file.")

    async def interpolate(
        self, src: Path, dst: Path, *, export_fps: int, source_fps: int,
    ) -> None:
        """Conventional motion-compensated interpolation (ffmpeg minterpolate).

        Honest labeling: this estimates in-between frames from pixel motion.
        It does NOT generate new semantic content and can produce artifacts
        on fast/complex motion.

        Duration-exactness note: minterpolate buffers its stream tail and
        emits ~3 output frames fewer than a pure ratio would suggest. To keep
        the final export EXACTLY on the target duration, the tail is padded
        with cloned frames (tpad, <= 0.5 s) and the final encode trims to the
        exact frame count. In the worst case the last <= 3 output frames hold
        the final generated frame — this is documented behavior, not hidden.
        scd=none is correct here: generated clips are continuous shots with
        no scene cuts.
        """
        if export_fps <= source_fps:
            shutil.copyfile(src, dst)
            return
        vf = (
            f"minterpolate=fps={export_fps}:mi_mode=mci:mc_mode=aobmc:"
            f"me_mode=bidir:vsbmc=1:scd=none,"
            f"tpad=stop_mode=clone:stop_duration=0.5"
        )
        await self.ffmpeg.run(
            [
                self.ffmpeg.info()["ffmpeg_path"],
                "-y", "-i", str(src),
                "-vf", vf,
                "-c:v", "libx264", "-preset", "medium", "-crf", CRF_INTERMEDIATE,
                "-pix_fmt", "yuv420p",
                str(dst),
            ],
            timeout=2400, log_label="minterpolate",
        )
        if not dst.is_file() or dst.stat().st_size == 0:
            raise NovaError(ErrorCode.ENCODE_FAILED, "Interpolation produced no output file.")

    async def final_encode(
        self, src: Path, dst: Path, *, export_fps: int, exact_frames: int,
        upscale_factor: int = 1,
    ) -> None:
        """Deliverable encode: exact fps, exact frame count, browser-friendly."""
        filters = []
        if upscale_factor and upscale_factor > 1:
            filters.append(f"scale=iw*{upscale_factor}:ih*{upscale_factor}:flags=lanczos")
        args = [
            self.ffmpeg.info()["ffmpeg_path"],
            "-y", "-i", str(src),
        ]
        if filters:
            args += ["-vf", ",".join(filters)]
        args += [
            "-r", str(export_fps),
            "-frames:v", str(exact_frames),
            "-c:v", "libx264", "-preset", "slow", "-crf", CRF_FINAL,
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-an",  # the model generates no audio; never fake an audio track
            str(dst),
        ]
        await self.ffmpeg.run(args, timeout=1800, log_label="final_encode")
        if not dst.is_file() or dst.stat().st_size == 0:
            raise NovaError(ErrorCode.ENCODE_FAILED, "Final encode produced no output file.")
