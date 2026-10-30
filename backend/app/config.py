"""NOVA MOTION backend configuration.

All configuration comes from environment variables (optionally loaded from a
`.env` file at the project root). Defaults are safe for a single-user Windows
11 laptop: localhost-only binding, no telemetry, sequential jobs.

Nothing in this module performs I/O beyond reading the optional `.env` file.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Project root = repository root (parent of backend/)
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT_DEFAULT = BACKEND_DIR.parent


def _load_dotenv(env_path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines, '#' comments, optional quotes.

    Existing environment variables always win (explicit env > file).
    """
    try:
        if not env_path.is_file():
            return
        for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        # A broken .env must never prevent startup; defaults apply.
        pass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


@dataclass
class Settings:
    """Runtime settings resolved once at startup (see `get_settings`)."""

    # --- paths -----------------------------------------------------------
    project_root: Path = PROJECT_ROOT_DEFAULT
    data_dir: Path = field(init=False)
    logs_dir: Path = field(init=False)
    outputs_dir: Path = field(init=False)
    thumbnails_dir: Path = field(init=False)
    engine_dir: Path = field(init=False)
    workflows_dir: Path = field(init=False)
    models_registry_file: Path = field(init=False)
    frontend_dist: Path = field(init=False)

    # --- networking (localhost only by default — see SECURITY.md) --------
    backend_host: str = "127.0.0.1"
    backend_port: int = 8317
    engine_host: str = "127.0.0.1"
    engine_port: int = 8188

    # --- engine management -----------------------------------------------
    autostart_engine: bool = True
    engine_startup_timeout_s: int = 240
    # Extra ComfyUI CLI flags. The low-VRAM defaults below were chosen for
    # 4 GB dedicated VRAM + 8 GB system RAM (RTX 2050 Laptop class):
    #   --lowvram             : keep text encoder on CPU, split UNet if needed
    #   --cache-none          : do not cache node results in RAM between runs
    #   --disable-auto-launch : never open ComfyUI's own browser tab
    engine_extra_args: list[str] = field(
        default_factory=lambda: ["--lowvram", "--cache-none", "--disable-auto-launch"]
    )
    # Release engine-side memory after every job (POST /free).
    free_engine_memory_after_job: bool = True

    # --- jobs -------------------------------------------------------------
    max_queue_length: int = 2  # 1 running + 1 queued; more is rejected (8 GB RAM)
    job_heartbeat_timeout_s: int = 1800  # engine silent for 30 min -> fail job

    # --- resource guard thresholds ---------------------------------------
    min_free_ram_gb_block: float = 1.2   # below -> refuse generation
    min_free_ram_gb_warn: float = 2.2    # below -> warn but allow
    min_free_disk_gb_block: float = 1.5  # below -> refuse generation
    min_free_disk_gb_warn: float = 4.0   # below -> warn but allow

    # --- ffmpeg -----------------------------------------------------------
    # Optional explicit path; otherwise detected on PATH, then in tools/.
    ffmpeg_path_override: str = ""

    # --- misc --------------------------------------------------------------
    log_level: str = "INFO"
    request_body_limit_bytes: int = 1_000_000  # ~1 MB; no upload features exist

    def __post_init__(self) -> None:
        root = self.project_root
        self.data_dir = Path(os.environ.get("NOVA_DATA_DIR") or root / "data")
        self.logs_dir = Path(os.environ.get("NOVA_LOGS_DIR") or root / "logs")
        self.outputs_dir = Path(os.environ.get("NOVA_OUTPUTS_DIR") or root / "outputs")
        self.thumbnails_dir = Path(
            os.environ.get("NOVA_THUMBNAILS_DIR") or root / "thumbnails"
        )
        self.engine_dir = Path(os.environ.get("NOVA_ENGINE_DIR") or root / "engine")
        self.workflows_dir = Path(
            os.environ.get("NOVA_WORKFLOWS_DIR") or root / "workflows"
        )
        self.models_registry_file = Path(
            os.environ.get("NOVA_MODELS_REGISTRY")
            or root / "models" / "registry.json"
        )
        self.frontend_dist = Path(
            os.environ.get("NOVA_FRONTEND_DIST") or root / "frontend" / "dist"
        )

    @property
    def engine_base_url(self) -> str:
        return f"http://{self.engine_host}:{self.engine_port}"

    @property
    def comfyui_root(self) -> Path:
        return self.engine_dir / "ComfyUI"

    @property
    def comfyui_venv_python(self) -> Path:
        if os.name == "nt":
            return self.engine_dir / ".venv" / "Scripts" / "python.exe"
        return self.engine_dir / ".venv" / "bin" / "python"

    def ensure_directories(self) -> None:
        for d in (
            self.data_dir,
            self.logs_dir,
            self.outputs_dir,
            self.thumbnails_dir,
            self.engine_dir,
            self.workflows_dir,
            self.project_root / "models",
        ):
            d.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the process-wide Settings, resolving env on first call."""
    global _settings
    if _settings is None:
        root = Path(os.environ.get("NOVA_PROJECT_ROOT") or PROJECT_ROOT_DEFAULT)
        _load_dotenv(root / ".env")
        _settings = Settings(
            project_root=root,
            backend_host=os.environ.get("NOVA_BACKEND_HOST", "127.0.0.1"),
            backend_port=_env_int("NOVA_BACKEND_PORT", 8317),
            engine_host=os.environ.get("NOVA_ENGINE_HOST", "127.0.0.1"),
            engine_port=_env_int("NOVA_ENGINE_PORT", 8188),
            autostart_engine=_env_bool("NOVA_AUTOSTART_ENGINE", True),
            engine_startup_timeout_s=_env_int("NOVA_ENGINE_STARTUP_TIMEOUT_S", 240),
            free_engine_memory_after_job=_env_bool("NOVA_FREE_AFTER_JOB", True),
            max_queue_length=_env_int("NOVA_MAX_QUEUE", 2),
            job_heartbeat_timeout_s=_env_int("NOVA_JOB_HEARTBEAT_TIMEOUT_S", 1800),
            log_level=os.environ.get("NOVA_LOG_LEVEL", "INFO"),
            ffmpeg_path_override=os.environ.get("NOVA_FFMPEG_PATH", ""),
        )
        if os.environ.get("NOVA_ENGINE_EXTRA_ARGS") is not None:
            _settings.engine_extra_args = [
                a for a in os.environ["NOVA_ENGINE_EXTRA_ARGS"].split() if a
            ]
    return _settings


def reset_settings_for_tests() -> None:
    global _settings
    _settings = None
