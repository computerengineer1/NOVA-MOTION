"""Model registry: loads/validates models/registry.json and tracks install state.

The registry is the ONLY source of downloadable models. The frontend can never
introduce a URL, filename, or path that is not already present here — this is
what keeps model installation free of arbitrary-download and path-traversal
risk.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import Settings
from ..logging_config import get_logger
from .errors import ErrorCode, NovaError
from .path_security import safe_subpath

log = get_logger(__name__)

INSTALLABLE_STATUSES = {"recommended", "supported", "experimental"}


@dataclass
class ModelFile:
    id: str
    dest: str
    size_bytes: int
    url: str
    sha256: str | None = None
    required: bool = True


@dataclass
class ModelProfile:
    model_id: str
    name: str
    model_type: str
    adapter: str
    status: str
    license_id: str
    source: str
    version: str | None = None
    license_urls: list[str] = field(default_factory=list)
    license_requires_acceptance: bool = False
    total_download_bytes: int = 0
    requirements: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)
    memory_notes: str | None = None
    quality_notes: str | None = None
    incompatible_reason: str | None = None
    files: list[ModelFile] = field(default_factory=list)
    workflow_ids: list[str] = field(default_factory=list)


class ModelRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.profiles: dict[str, ModelProfile] = {}
        self.host_allowlist: set[str] = set()
        self.load()

    # -- loading ----------------------------------------------------------
    def load(self) -> None:
        path = self.settings.models_registry_file
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise NovaError(
                ErrorCode.INTERNAL,
                "Model registry file is missing from the installation.",
                detail=str(path),
                recovery="Re-run scripts/Repair-Environment.ps1 to restore project files.",
                http_status=500,
            )
        except json.JSONDecodeError as exc:
            raise NovaError(
                ErrorCode.INTERNAL,
                "Model registry file is corrupt.",
                detail=f"{path}: {exc}",
                recovery="Restore models/registry.json from the project source.",
                http_status=500,
            )
        self.host_allowlist = set(raw.get("host_allowlist", []))
        profiles: dict[str, ModelProfile] = {}
        for entry in raw.get("models", []):
            try:
                files = [
                    ModelFile(
                        id=f["id"], dest=f["dest"], size_bytes=int(f["size_bytes"]),
                        url=f["url"], sha256=f.get("sha256"),
                        required=bool(f.get("required", True)),
                    )
                    for f in entry.get("files", [])
                ]
                profile = ModelProfile(
                    model_id=entry["model_id"],
                    name=entry["name"],
                    model_type=entry["model_type"],
                    adapter=entry["adapter"],
                    status=entry["status"],
                    license_id=entry["license_id"],
                    source=entry["source"],
                    version=entry.get("version"),
                    license_urls=entry.get("license_urls", []),
                    license_requires_acceptance=bool(entry.get("license_requires_acceptance")),
                    total_download_bytes=int(entry.get("total_download_bytes", 0)),
                    requirements=entry.get("requirements", {}),
                    capabilities=entry.get("capabilities", {}),
                    memory_notes=entry.get("memory_notes"),
                    quality_notes=entry.get("quality_notes"),
                    incompatible_reason=entry.get("incompatible_reason"),
                    files=files,
                    workflow_ids=entry.get("workflow_ids", []),
                )
                self._validate_profile(profile)
                profiles[profile.model_id] = profile
            except (KeyError, ValueError, NovaError) as exc:
                # A malformed entry must not take down the whole registry.
                log.error("Skipping malformed registry entry %r: %s", entry.get("model_id"), exc)
        self.profiles = profiles
        log.info("Model registry loaded: %d profiles (%d installable)",
                 len(profiles),
                 sum(1 for p in profiles.values() if p.status in INSTALLABLE_STATUSES))

    @staticmethod
    def _validate_profile(p: ModelProfile) -> None:
        if p.status not in {"recommended", "supported", "experimental", "incompatible"}:
            raise ValueError(f"bad status {p.status!r}")
        from urllib.parse import urlparse

        for f in p.files:
            parsed = urlparse(f.url)
            if parsed.scheme != "https":
                raise ValueError(f"file {f.id}: only https URLs are allowed")
            if f.size_bytes <= 0:
                raise ValueError(f"file {f.id}: bad size")
            # dest must be a relative path without traversal
            if ".." in Path(f.dest).parts or Path(f.dest).is_absolute():
                raise ValueError(f"file {f.id}: unsafe dest {f.dest}")

    # -- queries ------------------------------------------------------------
    def get(self, model_id: str) -> ModelProfile:
        profile = self.profiles.get(model_id)
        if profile is None:
            raise NovaError(
                ErrorCode.MODEL_NOT_INSTALLED,
                f"Unknown model '{model_id}'.",
                recovery="Choose one of the models listed on the Models page.",
                http_status=404,
            )
        return profile

    def get_installable(self, model_id: str) -> ModelProfile:
        profile = self.get(model_id)
        if profile.status not in INSTALLABLE_STATUSES:
            raise NovaError(
                ErrorCode.MODEL_NOT_INSTALLED,
                f"'{profile.name}' is not installable on this machine.",
                detail=profile.incompatible_reason or f"status={profile.status}",
                recovery="Use a model marked 'recommended' or 'supported'.",
                http_status=409,
            )
        return profile

    def list_all(self) -> list[ModelProfile]:
        return list(self.profiles.values())

    # -- filesystem state -----------------------------------------------------
    def file_path(self, f: ModelFile) -> Path:
        """Absolute path of a model file inside the managed ComfyUI root."""
        return safe_subpath(self.settings.comfyui_root, f.dest)

    def file_state(self, f: ModelFile) -> dict[str, Any]:
        path = self.file_path(f)
        state: dict[str, Any] = {
            "id": f.id, "dest": f.dest, "size_bytes": f.size_bytes, "url": f.url,
            "sha256": f.sha256, "required": f.required,
            "installed": False, "actual_size_bytes": None, "checksum_ok": None,
        }
        part = path.with_suffix(path.suffix + ".part")
        if part.exists():
            state["actual_size_bytes"] = part.stat().st_size
        if path.exists():
            size = path.stat().st_size
            state["actual_size_bytes"] = size
            state["installed"] = size == f.size_bytes
            if size != f.size_bytes:
                state["checksum_ok"] = False  # wrong size => definitely not intact
        return state

    def is_installed(self, profile: ModelProfile) -> bool:
        if not profile.files:
            return False
        return all(self.file_state(f)["installed"] for f in profile.files if f.required)

    def verify_checksum(self, f: ModelFile) -> bool | None:
        """SHA256 verification for an installed file. None if no checksum known."""
        if not f.sha256:
            return None
        path = self.file_path(f)
        if not path.exists():
            return False
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest().lower() == f.sha256.lower()

    def checkpoint_name(self, profile: ModelProfile) -> str | None:
        """ComfyUI-relative name used by CheckpointLoaderSimple."""
        for f in profile.files:
            if f.dest.startswith("models/checkpoints/"):
                return f.dest.removeprefix("models/checkpoints/")
        return None

    def motion_model_name(self, profile: ModelProfile) -> str | None:
        """File name ADE_LoadAnimateDiffModel expects (basename in animatediff_models)."""
        for f in profile.files:
            if "animatediff_models/" in f.dest:
                return Path(f.dest).name
        return None

    def is_url_host_allowed(self, url: str) -> bool:
        from urllib.parse import urlparse

        host = (urlparse(url).hostname or "").lower()
        if host in self.host_allowlist:
            return True
        # HF LFS redirects to regional CDN hosts ending in .hf.co / .huggingface.co
        return host.endswith(".huggingface.co") or host.endswith(".hf.co")
