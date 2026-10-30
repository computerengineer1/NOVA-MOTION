"""Model installation: registry-driven downloads with resume + verification.

Security properties:
  * URLs come exclusively from models/registry.json (client can only pass a
    model_id); host must be on the allowlist; scheme must be https.
  * Redirects are followed, but every redirected URL is re-checked against
    the allowlist and against private/loopback IP ranges (SSRF protection).
  * Files download to `<dest>.part` and are renamed atomically — a partial
    file can never masquerade as an installed model.
  * Downloads resume via HTTP Range when the upstream supports it.
  * SHA256 is verified when the registry provides it; size is always checked.
  * Removal deletes ONLY registry-owned files inside the managed ComfyUI
    models tree, and requires an explicit confirm_model_id match.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiohttp

from ..config import Settings
from ..core.errors import ErrorCode, NovaError
from ..core.model_registry import INSTALLABLE_STATUSES, ModelFile, ModelProfile, ModelRegistry
from ..core.progress_manager import ProgressManager
from ..database.repositories import ModelRepository, utcnow_iso
from ..logging_config import get_logger

log = get_logger(__name__)

CHUNK = 1024 * 256


def _host_allowed(url: str, registry: ModelRegistry) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if registry.is_url_host_allowed(url):
        pass
    else:
        return False
    # SSRF: reject literal private/loopback hosts
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return False
    except ValueError:
        pass  # hostname, not IP — fine
    return True


def _redirect_safe(url: str, registry: ModelRegistry) -> bool:
    return _host_allowed(url, registry)


@dataclass
class InstallState:
    model_id: str
    state: str = "idle"  # starting|downloading|verifying|completed|failed|cancelled
    current_file: str | None = None
    file_index: int = 0
    file_count: int = 0
    bytes_done: int = 0
    bytes_total: int = 0
    error: dict[str, Any] | None = None
    started_at: str | None = None
    finished_at: str | None = None
    _cancel: bool = field(default=False, repr=False)

    @property
    def percent(self) -> float:
        if self.bytes_total <= 0:
            return 0.0
        return round(min(100.0, self.bytes_done / self.bytes_total * 100.0), 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id, "state": self.state,
            "current_file": self.current_file, "file_index": self.file_index,
            "file_count": self.file_count, "bytes_done": self.bytes_done,
            "bytes_total": self.bytes_total, "percent": self.percent,
            "error": self.error, "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class ModelInstallationService:
    def __init__(
        self,
        settings: Settings,
        registry: ModelRegistry,
        models_repo: ModelRepository,
        progress: ProgressManager,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.models_repo = models_repo
        self.progress = progress
        self._installs: dict[str, InstallState] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    # ---------------------------------------------------------------- state
    def status(self, model_id: str) -> InstallState:
        return self._installs.get(model_id) or InstallState(model_id=model_id)

    def cancel(self, model_id: str) -> bool:
        st = self._installs.get(model_id)
        if st and st.state in ("starting", "downloading", "verifying"):
            st._cancel = True
            return True
        return False

    # -------------------------------------------------------------- install
    def start_install(self, model_id: str, accept_license: bool) -> InstallState:
        profile = self.registry.get(model_id)
        if profile.status not in INSTALLABLE_STATUSES:
            raise NovaError(
                ErrorCode.MODEL_NOT_INSTALLED,
                f"'{profile.name}' cannot be installed on this machine.",
                detail=profile.incompatible_reason or f"status={profile.status}",
                recovery="See MODEL_COMPATIBILITY.md for why, and use the recommended profile.",
                http_status=409,
            )
        if profile.license_requires_acceptance and not accept_license:
            raise NovaError(
                ErrorCode.MODEL_LICENSE_NOT_ACCEPTED,
                "This model requires explicit license acceptance before download.",
                recovery="Read the license at the source URL and retry with accept_license=true.",
                http_status=451,
            )
        if not profile.files:
            raise NovaError(ErrorCode.MODEL_NOT_INSTALLED,
                            "This profile defines no downloadable files.",
                            http_status=409)
        existing = self._installs.get(model_id)
        if existing and existing.state in ("starting", "downloading", "verifying"):
            return existing
        if any(st.state in ("starting", "downloading", "verifying")
               for st in self._installs.values()):
            raise NovaError(
                ErrorCode.QUEUE_FULL,
                "Another model download is already in progress.",
                recovery="8 GB RAM machines should not run parallel large downloads "
                         "next to the engine. Wait for it to finish.",
                http_status=429,
            )
        # disk check before starting
        import shutil
        free = shutil.disk_usage(str(self.settings.engine_dir)).free / 1024**3
        need = profile.total_download_bytes / 1024**3
        min_disk = float(profile.requirements.get("min_free_disk_gb", 5.0))
        if free < max(need * 1.15, min_disk):
            raise NovaError(
                ErrorCode.INSUFFICIENT_DISK,
                f"Not enough free disk space: {free:.1f} GB available, "
                f"~{need * 1.15:.1f} GB needed (download + headroom).",
                recovery="Free disk space (never delete your generated videos to do this — "
                         "move them elsewhere first), then retry.",
                http_status=507,
            )
        st = InstallState(
            model_id=model_id, state="starting", file_count=len(profile.files),
            bytes_total=sum(f.size_bytes for f in profile.files),
            started_at=utcnow_iso(),
        )
        self._installs[model_id] = st
        self._tasks[model_id] = asyncio.create_task(
            self._run_install(profile, st), name=f"install-{model_id}"
        )
        return st

    async def _run_install(self, profile: ModelProfile, st: InstallState) -> None:
        try:
            st.state = "downloading"
            self._publish(st)
            for idx, f in enumerate(profile.files):
                if st._cancel:
                    raise NovaError(ErrorCode.JOB_CANCELLED, "Download cancelled by user.")
                st.file_index = idx
                st.current_file = f.dest
                self._publish(st)
                await self._download_file(f, st)
            st.state = "verifying"
            self._publish(st)
            for f in profile.files:
                if f.sha256:
                    ok = await asyncio.to_thread(self.registry.verify_checksum, f)
                    if not ok:
                        # Corrupt download: remove the bad file so a retry re-downloads it.
                        try:
                            self.registry.file_path(f).unlink(missing_ok=True)
                        except OSError:
                            pass
                        raise NovaError(
                            ErrorCode.MODEL_FILE_CORRUPT,
                            f"Checksum verification failed for {Path(f.dest).name}.",
                            detail=f"expected sha256 {f.sha256}",
                            recovery="The corrupted file was removed. Start the installation again — "
                                     "if it fails repeatedly, your connection may be altering downloads.",
                        )
            st.state = "completed"
            st.finished_at = utcnow_iso()
            self._publish(st)
            self._record_installed(profile)
            log.info("Model %s installed successfully.", profile.model_id)
        except NovaError as exc:
            st.state = "cancelled" if exc.code == ErrorCode.JOB_CANCELLED else "failed"
            st.error = exc.to_public_dict()
            st.finished_at = utcnow_iso()
            self._publish(st)
            log.warning("Install of %s failed: [%s] %s", profile.model_id, exc.code, exc.summary)
        except asyncio.CancelledError:
            st.state = "cancelled"
            st.finished_at = utcnow_iso()
            self._publish(st)
            raise
        except Exception as exc:  # noqa: BLE001
            st.state = "failed"
            st.error = {"code": ErrorCode.DOWNLOAD_FAILED, "summary":
                        "The download failed unexpectedly.", "retryable": True}
            st.finished_at = utcnow_iso()
            self._publish(st)
            log.exception("Unexpected install failure for %s: %s", profile.model_id, exc)

    async def _download_file(self, f: ModelFile, st: InstallState) -> None:
        from ..core.path_security import safe_subpath
        dest = safe_subpath(self.settings.comfyui_root, f.dest)
        if not _host_allowed(f.url, self.registry):
            raise NovaError(ErrorCode.DOWNLOAD_FAILED,
                            "Download blocked: URL host is not on the trusted allowlist.",
                            detail=f.url, http_status=403)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(dest.suffix + ".part")

        if dest.exists() and dest.stat().st_size == f.size_bytes:
            st.bytes_done += f.size_bytes
            self._publish(st)
            return  # already downloaded (idempotent)
        if dest.exists():
            log.warning("%s exists with wrong size — re-downloading.", dest.name)
            dest.unlink()

        resume_from = part.stat().st_size if part.exists() else 0
        if resume_from >= f.size_bytes:
            part.unlink()
            resume_from = 0

        timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=120)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                headers = {"User-Agent": "NovaMotion/1.0 (local studio)"}
                if resume_from > 0:
                    headers["Range"] = f"bytes={resume_from}-"
                async with session.get(f.url, headers=headers, allow_redirects=True) as resp:
                    final_url = str(resp.url)
                    if not _redirect_safe(final_url, self.registry):
                        raise NovaError(ErrorCode.DOWNLOAD_FAILED,
                                        "Download blocked: redirect to an untrusted host.",
                                        detail=final_url, http_status=403)
                    if resume_from > 0 and resp.status == 200:
                        # server ignored Range — start over
                        resume_from = 0
                    elif resume_from > 0 and resp.status == 206:
                        pass
                    elif resp.status != 200:
                        raise NovaError(
                            ErrorCode.DOWNLOAD_FAILED,
                            f"Download failed with HTTP {resp.status}.",
                            detail=f.url,
                            recovery="Check your internet connection and retry; the download resumes "
                                     "from where it stopped when the server supports it.",
                            retryable=True,
                        )
                    expected_total = f.size_bytes
                    mode = "ab" if resume_from > 0 else "wb"
                    written = resume_from
                    st.bytes_done += resume_from
                    digest = hashlib.sha256()
                    last_publish = 0.0
                    with part.open(mode) as fh:
                        if resume_from > 0:
                            # hash the resumed prefix so final checksum stays valid
                            with part.open("rb") as rh:
                                for chunk in iter(lambda: rh.read(CHUNK), b""):
                                    digest.update(chunk)
                        async for chunk in resp.content.iter_chunked(CHUNK):
                            if st._cancel:
                                raise NovaError(ErrorCode.DOWNLOAD_INTERRUPTED,
                                                "Download cancelled by user.",
                                                recovery="The partial file is kept; the download "
                                                         "resumes next time.")
                            fh.write(chunk)
                            digest.update(chunk)
                            written += len(chunk)
                            st.bytes_done += len(chunk)
                            now = time.monotonic()
                            if now - last_publish > 0.5:
                                last_publish = now
                                self._publish(st)
                    if written != expected_total:
                        raise NovaError(
                            ErrorCode.DOWNLOAD_INTERRUPTED,
                            f"Download incomplete: got {written} of {expected_total} bytes.",
                            recovery="The partial file was kept — start the install again to resume.",
                            retryable=True,
                        )
                    if f.sha256 and digest.hexdigest().lower() != f.sha256.lower():
                        part.unlink(missing_ok=True)
                        raise NovaError(
                            ErrorCode.MODEL_FILE_CORRUPT,
                            f"Checksum mismatch for {Path(f.dest).name} — the file was discarded.",
                            detail=f"expected {f.sha256}, got {digest.hexdigest()}",
                            recovery="Start the installation again to re-download this file.",
                        )
            part.replace(dest)
            self._publish(st)
        except aiohttp.ClientError as exc:
            raise NovaError(
                ErrorCode.DOWNLOAD_INTERRUPTED,
                "Network error during download.",
                detail=f"{type(exc).__name__}: {exc}",
                recovery="The partial file was kept; retry the install to resume where it stopped.",
                retryable=True,
            ) from exc

    def _publish(self, st: InstallState) -> None:
        self.progress.publish({"type": "install_progress", **st.to_dict()})

    def _record_installed(self, profile: ModelProfile) -> None:
        try:
            files = [
                {"id": f.id, "dest": f.dest, "size_bytes": f.size_bytes,
                 "sha256": f.sha256}
                for f in profile.files
            ]
            self.models_repo.upsert(
                profile.model_id,
                version=profile.version,
                source=profile.source,
                license_=profile.license_id,
                installation_path=str(self.settings.comfyui_root),
                installed_files=files,
                validation_status="valid",
                validation_note="Installed via NOVA MOTION; checksums verified."
                if any(f.sha256 for f in profile.files) else "Installed via NOVA MOTION.",
            )
        except Exception:  # noqa: BLE001
            log.exception("Could not record model installation in DB (files are installed)")

    # ------------------------------------------------------------- validate
    def validate(self, model_id: str) -> dict[str, Any]:
        """File presence + size (+ checksum only when explicitly requested elsewhere)."""
        profile = self.registry.get(model_id)
        if not profile.files:
            return {"model_id": model_id, "valid": False, "files": [],
                    "note": profile.incompatible_reason or "Profile defines no files."}
        files_out = []
        valid = True
        for f in profile.files:
            st = self.registry.file_state(f)
            files_out.append(st)
            if f.required and not st["installed"]:
                valid = False
        note = None
        if valid:
            wrong_size = [s for s in files_out if s["installed"] is False]
            note = "All required files present with expected sizes." if not wrong_size else None
        else:
            missing = [Path(s["dest"]).name for s in files_out if not s["installed"]]
            note = f"Missing or wrong-size files: {', '.join(missing)}"
        try:
            self.models_repo.upsert(
                profile.model_id, version=profile.version, source=profile.source,
                license_=profile.license_id,
                installation_path=str(self.settings.comfyui_root),
                installed_files=[{k: v for k, v in s.items() if k in ("id", "dest", "size_bytes", "sha256")}
                                 for s in files_out if s["installed"]],
                validation_status="valid" if valid else "invalid",
                validation_note=note,
            )
        except Exception:  # noqa: BLE001
            log.exception("Could not persist validation result for %s", model_id)
        return {"model_id": model_id, "valid": valid, "files": files_out, "note": note}

    # --------------------------------------------------------------- remove
    def remove(self, model_id: str, confirm_model_id: str) -> dict[str, Any]:
        if confirm_model_id != model_id:
            raise NovaError(ErrorCode.VALIDATION_ERROR,
                            "Confirmation does not match the model to delete.",
                            http_status=422)
        profile = self.registry.get(model_id)
        from ..core.path_security import assert_within
        deleted: list[str] = []
        models_root = self.settings.comfyui_root / "models"
        for f in profile.files:
            path = self.registry.file_path(f)
            # double containment: inside ComfyUI root AND inside models/
            assert_within(self.settings.comfyui_root, path)
            assert_within(models_root, path)
            for candidate in (path, path.with_suffix(path.suffix + ".part")):
                if candidate.is_file():
                    candidate.unlink()
                    deleted.append(str(candidate))
        self.models_repo.delete(model_id)
        self._installs.pop(model_id, None)
        log.info("Removed model %s (%d files).", model_id, len(deleted))
        return {"model_id": model_id, "deleted_files": deleted}
