"""Model download mechanics: resume, checksums, corruption, allowlist.

Uses a local aiohttp file server. The production host-allowlist check is
monkeypatched ONLY to reach the local test server; the allowlist logic itself
is tested separately in test_registry.py.
"""
from __future__ import annotations

import asyncio
import hashlib
import threading
from pathlib import Path

import pytest
from aiohttp import web

from app.core.errors import NovaError
from app.core.model_registry import ModelFile, ModelProfile
from app.services import model_installation
from app.services.model_installation import ModelInstallationService

PAYLOAD = bytes(range(256)) * 4096  # 1 MiB deterministic content
SHA = hashlib.sha256(PAYLOAD).hexdigest()


class RangeFileServer:
    """Serves one file with proper HTTP Range support (like HF's CDN)."""

    def __init__(self, payload: bytes = PAYLOAD):
        self.payload = payload
        self.range_requests = 0
        self.port: int | None = None
        self._loop = None
        self._runner = None
        self._thread = None

    async def _handle(self, request: web.Request) -> web.Response:
        rng = request.headers.get("Range")
        if rng and rng.startswith("bytes="):
            self.range_requests += 1
            start_s, _, end_s = rng[6:].partition("-")
            start = int(start_s)
            end = int(end_s) if end_s else len(self.payload) - 1
            end = min(end, len(self.payload) - 1)
            body = self.payload[start:end + 1]
            return web.Response(
                status=206, body=body,
                headers={"Content-Range": f"bytes {start}-{end}/{len(self.payload)}",
                         "Content-Length": str(len(body))},
            )
        return web.Response(status=200, body=self.payload,
                            headers={"Content-Length": str(len(self.payload))})

    def start(self) -> int:
        ready = threading.Event()

        def _run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            app = web.Application()
            app.router.add_get("/file.bin", self._handle)
            self._runner = web.AppRunner(app)
            self._loop.run_until_complete(self._runner.setup())
            site = web.TCPSite(self._runner, "127.0.0.1", 0)
            self._loop.run_until_complete(site.start())
            self.port = site._server.sockets[0].getsockname()[1]
            ready.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        assert ready.wait(10)
        return self.port

    def stop(self):
        if self._loop and self._runner:
            asyncio.run_coroutine_threadsafe(self._runner.cleanup(), self._loop).result(timeout=10)
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=10)


def make_profile(server_port: int, sha: str | None = SHA, size: int = len(PAYLOAD)) -> ModelProfile:
    return ModelProfile(
        model_id="test-download-model",
        name="Test Download Model",
        model_type="test", adapter="comfyui_animatediff", status="supported",
        license_id="test", source="local test server",
        total_download_bytes=size,
        requirements={"min_free_disk_gb": 0.01},
        files=[ModelFile(
            id="main", dest="models/checkpoints/test-model.bin",
            size_bytes=size, sha256=sha,
            url=f"http://127.0.0.1:{server_port}/file.bin",
        )],
    )


@pytest.fixture()
def server():
    s = RangeFileServer()
    s.start()
    yield s
    s.stop()


@pytest.fixture()
def allow_local(monkeypatch):
    """Permit the local test server (production allowlist tested elsewhere)."""
    monkeypatch.setattr(model_installation, "_host_allowed", lambda url, reg: True)
    monkeypatch.setattr(model_installation, "_redirect_safe", lambda url, reg: True)


async def _wait_done(installer: ModelInstallationService, model_id: str, timeout=30):
    task = installer._tasks[model_id]
    await asyncio.wait_for(task, timeout=timeout)
    return installer.status(model_id)


async def test_download_completes_and_records(container, server, allow_local):
    profile = make_profile(server.port)
    container.registry.profiles[profile.model_id] = profile
    installer = container.installer
    st = installer.start_install(profile.model_id, accept_license=False)
    st = await _wait_done(installer, profile.model_id)
    assert st.state == "completed", st.error
    dest = container.registry.file_path(profile.files[0])
    assert dest.is_file() and dest.read_bytes() == PAYLOAD
    assert not dest.with_suffix(dest.suffix + ".part").exists()
    row = container.models_repo.get(profile.model_id)
    assert row and row["validation_status"] == "valid"
    assert container.registry.is_installed(profile)


async def test_resume_from_partial(container, server, allow_local):
    profile = make_profile(server.port)
    container.registry.profiles[profile.model_id] = profile
    dest = container.registry.file_path(profile.files[0])
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    part.write_bytes(PAYLOAD[: len(PAYLOAD) // 2])  # half-finished download
    installer = container.installer
    installer.start_install(profile.model_id, accept_license=False)
    st = await _wait_done(installer, profile.model_id)
    assert st.state == "completed", st.error
    assert server.range_requests >= 1  # resumed via Range
    assert dest.read_bytes() == PAYLOAD


async def test_checksum_mismatch_discards_file(container, server, allow_local):
    profile = make_profile(server.port, sha="0" * 64)  # wrong checksum
    container.registry.profiles[profile.model_id] = profile
    installer = container.installer
    installer.start_install(profile.model_id, accept_license=False)
    st = await _wait_done(installer, profile.model_id)
    assert st.state == "failed"
    assert st.error["code"] == "MODEL_FILE_CORRUPT"
    dest = container.registry.file_path(profile.files[0])
    assert not dest.exists()          # corrupt file discarded
    assert not dest.with_suffix(dest.suffix + ".part").exists()


async def test_truncated_download_detected(container, allow_local):
    server = RangeFileServer(payload=PAYLOAD)
    server.start()
    try:
        profile = make_profile(server.port, size=len(PAYLOAD) + 12345)  # expect more bytes
        container.registry.profiles[profile.model_id] = profile
        installer = container.installer
        installer.start_install(profile.model_id, accept_license=False)
        st = await _wait_done(installer, profile.model_id)
        assert st.state == "failed"
        assert st.error["code"] == "DOWNLOAD_INTERRUPTED"
        assert st.error.get("retryable") is True
    finally:
        server.stop()


async def test_incompatible_profile_refused(container):
    profile = make_profile(1)
    profile.status = "incompatible"
    profile.incompatible_reason = "too big for this machine"
    container.registry.profiles[profile.model_id] = profile
    with pytest.raises(NovaError) as exc:
        container.installer.start_install(profile.model_id, accept_license=True)
    assert exc.value.code == "MODEL_NOT_INSTALLED"
    assert "too big" in (exc.value.detail or "")


async def test_license_acceptance_required(container):
    profile = make_profile(1)
    profile.license_requires_acceptance = True
    container.registry.profiles[profile.model_id] = profile
    with pytest.raises(NovaError) as exc:
        container.installer.start_install(profile.model_id, accept_license=False)
    assert exc.value.code == "MODEL_LICENSE_NOT_ACCEPTED"
    assert exc.value.http_status == 451


def test_validate_and_remove_flow(container, server, allow_local, tmp_path):
    profile = make_profile(server.port)
    container.registry.profiles[profile.model_id] = profile
    dest = container.registry.file_path(profile.files[0])
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(PAYLOAD)

    result = container.installer.validate(profile.model_id)
    assert result["valid"] is True

    # removal requires matching confirmation
    with pytest.raises(NovaError):
        container.installer.remove(profile.model_id, "wrong-id")
    out = container.installer.remove(profile.model_id, profile.model_id)
    assert not dest.exists()
    assert out["deleted_files"]


def test_removal_cannot_escape_models_dir(container, tmp_path, monkeypatch):
    """Even a maliciously-edited registry entry cannot delete files outside
    the managed ComfyUI models tree."""
    profile = ModelProfile(
        model_id="evil", name="evil", model_type="t", adapter="a",
        status="supported", license_id="x", source="s",
        files=[ModelFile(id="f", dest="../../../../etc/important.bin",
                         size_bytes=1, url="https://huggingface.co/x")],
    )
    container.registry.profiles["evil"] = profile
    with pytest.raises(NovaError) as exc:
        container.installer.remove("evil", "evil")
    assert exc.value.code == "PATH_SECURITY"
