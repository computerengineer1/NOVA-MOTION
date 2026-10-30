"""FFmpeg/ffprobe discovery and safe subprocess execution.

Rules:
  * argument arrays only — never a shell string,
  * every call has a timeout,
  * success is determined by return code AND (for probes) parsable output,
  * if ffmpeg is missing, everything raises NovaError(FFMPEG_MISSING) with a
    concrete Windows installation hint (winget Gyan.FFmpeg / gyan.dev zip).
"""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any, Sequence

from ..config import Settings
from ..core.errors import ErrorCode, NovaError
from ..logging_config import get_logger

log = get_logger(__name__)


class FFmpegService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._ffmpeg: str | None = None
        self._ffprobe: str | None = None
        self._version: str | None = None
        self._checked = False

    # ------------------------------------------------------------ discovery
    def _candidate_dirs(self) -> list[Path]:
        dirs = [Path(self.settings.project_root / "tools" / "ffmpeg" / "bin")]
        if self.settings.ffmpeg_path_override:
            p = Path(self.settings.ffmpeg_path_override)
            return [p.parent] + dirs
        return dirs

    def discover(self) -> dict[str, Any]:
        if self._checked:
            return self.info()
        self._checked = True
        override = self.settings.ffmpeg_path_override

        def _find(name: str) -> str | None:
            if override and name == "ffmpeg":
                if Path(override).is_file():
                    return override
            found = shutil.which(name)
            if found:
                return found
            for d in self._candidate_dirs():
                for suffix in (".exe", ""):
                    cand = d / f"{name}{suffix}"
                    if cand.is_file():
                        return str(cand)
            return None

        self._ffmpeg = _find("ffmpeg")
        self._ffprobe = _find("ffprobe")
        if self._ffmpeg:
            try:
                out = self._run_sync([self._ffmpeg, "-version"], timeout=15)
                first = out.splitlines()[0] if out else ""
                self._version = first.replace("ffmpeg version", "").strip() or None
            except Exception:  # noqa: BLE001
                log.exception("ffmpeg found but -version failed")
        return self.info()

    def info(self) -> dict[str, Any]:
        return {
            "available": bool(self._ffmpeg and self._ffprobe),
            "ffmpeg_path": self._ffmpeg,
            "ffprobe_path": self._ffprobe,
            "version": self._version,
            "hint": None if (self._ffmpeg and self._ffprobe) else (
                "FFmpeg was not found. On Windows run: winget install Gyan.FFmpeg "
                "(or download the GPL 'release essentials' build from "
                "https://www.gyan.dev/ffmpeg/builds/ and put bin/ on PATH). "
                "Install-Studio.ps1 does this automatically."
            ),
        }

    def require(self) -> tuple[str, str]:
        info = self.discover()
        if not info["available"]:
            raise NovaError(
                ErrorCode.FFMPEG_MISSING,
                "FFmpeg is not installed or not on PATH — video assembly is impossible without it.",
                detail=info.get("hint"),
                recovery="Run scripts/Install-Studio.ps1 (installs FFmpeg via winget or the official gyan.dev build).",
                http_status=503,
            )
        return self._ffmpeg, self._ffprobe  # type: ignore[return-value]

    # ------------------------------------------------------------- execution
    def _run_sync(self, args: Sequence[str], timeout: float) -> str:
        import subprocess
        proc = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if proc.returncode != 0:
            raise NovaError(
                ErrorCode.ENCODE_FAILED,
                f"{Path(args[0]).name} failed (exit {proc.returncode}).",
                detail=(proc.stderr or proc.stdout)[-3000:],
            )
        return proc.stdout

    async def run(self, args: Sequence[str], *, timeout: float = 600,
                  log_label: str = "ffmpeg") -> str:
        """Async execution with timeout. Raises NovaError on failure."""
        self.require()
        log.debug("%s: %s", log_label, " ".join(str(a) for a in args))
        proc = await asyncio.create_subprocess_exec(
            *[str(a) for a in args],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutExpired:
            proc.kill()
            await proc.wait()
            raise NovaError(
                ErrorCode.ENCODE_FAILED,
                f"{log_label} timed out after {timeout:.0f}s.",
                recovery="The operation was too slow (very high frame count or heavy filter). "
                         "Retry with interpolation disabled.",
            )
        if proc.returncode != 0:
            text = (stderr or b"").decode(errors="replace")[-3000:]
            raise NovaError(
                ErrorCode.ENCODE_FAILED,
                f"{log_label} failed with exit code {proc.returncode}.",
                detail=text,
            )
        return (stderr or b"").decode(errors="replace")

    async def probe(self, path: Path) -> dict[str, Any]:
        """ffprobe JSON output; raises if the file cannot be probed."""
        self.require()
        _, ffprobe = self._ffmpeg, self._ffprobe
        args = [
            ffprobe, "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutExpired:
            proc.kill()
            raise NovaError(ErrorCode.OUTPUT_INVALID, "ffprobe timed out inspecting the file.")
        if proc.returncode != 0:
            raise NovaError(
                ErrorCode.OUTPUT_INVALID,
                "ffprobe could not read the media file (it is not valid media).",
                detail=(stderr or b"").decode(errors="replace")[-2000:],
            )
        try:
            return json.loads(stdout.decode())
        except ValueError as exc:
            raise NovaError(ErrorCode.OUTPUT_INVALID,
                            "ffprobe output was not parsable JSON.",
                            detail=str(exc)) from exc
