"""Shared fixtures.

Every test runs against an isolated project root under tmp_path — no test
ever touches the real data/, outputs/, or logs/ directories.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import Settings, get_settings, reset_settings_for_tests  # noqa: E402
from app.deps import Container, build_container  # noqa: E402


@pytest.fixture()
def nova_root(tmp_path: Path) -> Path:
    root = tmp_path / "nova-project"
    for d in ("data", "logs", "outputs", "thumbnails", "engine", "workflows",
              "models", "frontend"):
        (root / d).mkdir(parents=True, exist_ok=True)
    shutil.copy(PROJECT_ROOT / "models" / "registry.json",
                root / "models" / "registry.json")
    for wf in (PROJECT_ROOT / "workflows").glob("*.json"):
        shutil.copy(wf, root / "workflows" / wf.name)
    return root


@pytest.fixture()
def settings(nova_root: Path, monkeypatch) -> Settings:
    monkeypatch.setenv("NOVA_PROJECT_ROOT", str(nova_root))
    monkeypatch.setenv("NOVA_AUTOSTART_ENGINE", "false")
    monkeypatch.setenv("NOVA_BACKEND_PORT", "8317")
    monkeypatch.setenv("NOVA_LOG_LEVEL", "WARNING")
    reset_settings_for_tests()
    s = get_settings()
    # sandbox/test-friendly thresholds (documented in tests, not shipped defaults)
    s.min_free_ram_gb_block = 0.05
    s.min_free_ram_gb_warn = 0.1
    s.min_free_disk_gb_block = 0.05
    s.min_free_disk_gb_warn = 0.1
    s.engine_startup_timeout_s = 5
    s.job_heartbeat_timeout_s = 60
    s.ensure_directories()
    yield s
    reset_settings_for_tests()


@pytest.fixture()
def container(settings: Settings) -> Container:
    return build_container(settings)


@pytest.fixture()
def app_client(container: Container, settings: Settings):
    from starlette.testclient import TestClient
    from app.main import create_app
    app = create_app(container=container, settings=settings)
    with TestClient(app) as client:
        yield client


def start_fake_engine(container: Container, settings: Settings, **kwargs):
    """Start the fake ComfyUI bound to this container's paths and point the
    container at it. Returns the FakeComfyUI instance."""
    from tests.fake_comfyui import FakeComfyUI
    output_root = settings.comfyui_root / "output"
    output_root.mkdir(parents=True, exist_ok=True)
    fake = FakeComfyUI(output_root, **kwargs)
    port = fake.start()
    settings.engine_port = port
    # rebuild engine adapter URLs (base_url captured at construction)
    container.engines.adapter.base_url = f"http://127.0.0.1:{port}"  # type: ignore[attr-defined]
    container.engines.last_status.base_url = f"http://127.0.0.1:{port}"
    return fake


@pytest.fixture()
def tiny_model(container: Container, monkeypatch):
    """Make the recommended profile 'installed' with a tiny test resolution.

    This is explicit plumbing-test scaffolding: file-presence checks are
    bypassed and a 64x64 resolution is added so frame generation in the fake
    engine stays fast. It never claims real model inference happened.
    """
    profile = container.registry.get("animatediff-sd15")
    profile.capabilities.setdefault("resolutions", []).insert(0, {
        "id": "test_tiny_64", "width": 64, "height": 64, "aspect": "1:1",
        "default": True,
    })
    # make the tiny resolution the default for 1:1 and hide bigger defaults
    for res in profile.capabilities["resolutions"]:
        if res["id"] != "test_tiny_64":
            res["default"] = False
    monkeypatch.setattr(container.registry, "is_installed", lambda p: True)
    return profile
