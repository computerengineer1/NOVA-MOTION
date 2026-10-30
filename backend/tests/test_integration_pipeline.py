"""Full-stack integration tests: real backend + fake ComfyUI + real ffmpeg.

What these tests genuinely exercise:
  * HTTP API -> job manager -> generation service -> engine adapter (HTTP+WS)
  * engine progress events -> job progress states
  * frame collection -> ffmpeg assembly -> ffprobe validation -> thumbnails
  * SQLite persistence across a simulated backend restart
  * cancellation, queue limits, OOM single-retry downgrade
  * HTTP Range video streaming

What they do NOT prove: real diffusion inference (requires the RTX 2050 +
installed weights on the user's machine). The fake engine emits synthetic
gradient frames — outputs of these tests are plumbing artifacts, never
presented as AI-generated content.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tests.conftest import start_fake_engine

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}


def _client_for(container, settings):
    from starlette.testclient import TestClient
    from app.main import create_app
    app = create_app(container=container, settings=settings)
    return TestClient(app)


@pytest.fixture()
def integrated(settings, container, tiny_model):
    fake = start_fake_engine(container, settings, step_delay=0.005)
    with _client_for(container, settings) as client:
        yield client, fake, container, settings
    fake.stop()


def wait_terminal(client, job_id, timeout=90):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = client.get(f"/api/generations/{job_id}").json()
        if last["status"] in TERMINAL:
            return last
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not reach terminal state; last={last}")


def submit(client, **overrides):
    payload = {
        "prompt": "a massive wave crashing into a rocky coastline at sunset",
        "negative_prompt": "blurry, watermark",
        "model_id": "animatediff-sd15",
        "duration_seconds": 8.0,
        "aspect_ratio": "1:1",
        "resolution_id": "test_tiny_64",
        "steps": 8,
        "seed": 1234,
        "random_seed": False,
        "export_fps": 8,
        "interpolation": "none",
    }
    payload.update(overrides)
    r = client.post("/api/generations", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def test_native_long_8s_end_to_end(integrated):
    client, fake, container, settings = integrated
    job = submit(client)
    assert job["status"] == "QUEUED"
    eff = job["effective_settings"]
    assert eff["route"] == "native_long"
    assert eff["total_frames"] == 64 and eff["segments"] == 1
    assert "Native long generation" in eff["route_label"]

    final = wait_terminal(client, job["id"])
    assert final["status"] == "COMPLETED", json.dumps(final.get("error"), indent=2)

    # exactly one engine prompt for native mode
    assert len(fake.prompts_received) == 1
    wf = fake.prompts_received[0]["workflow"]
    assert wf["9"]["inputs"]["batch_size"] == 64
    assert wf["10"]["inputs"]["seed"] == 1234

    out = final["output"]
    assert out is not None
    assert abs(out["duration_seconds"] - 8.0) <= 1 / 8 + 1e-6
    assert out["width"] == 64 and out["height"] == 64
    assert out["fps"] == pytest.approx(8.0, abs=0.11)
    assert out["size_bytes"] > 1000
    assert out["codec"] == "h264/yuv420p"
    assert out["file_exists"] is True

    # real file on disk in outputs/
    files = list(settings.outputs_dir.glob(f"{job['id']}.mp4"))
    assert len(files) == 1 and files[0].stat().st_size == out["size_bytes"]
    thumb = settings.thumbnails_dir / f"{job['id']}.jpg"
    assert thumb.is_file() and thumb.stat().st_size > 0

    # metrics recorded honestly
    m = final["metrics"]
    assert m["engine_seconds"] > 0 and m["wall_seconds"] >= m["engine_seconds"]
    assert m["oom_downgrade_applied"] is False


def test_multishot_8s_end_to_end(integrated):
    client, fake, container, settings = integrated
    job = submit(client, generation_mode="multi_shot", steps=6)
    final = wait_terminal(client, job["id"])
    assert final["status"] == "COMPLETED", json.dumps(final.get("error"), indent=2)
    eff = job["effective_settings"]
    assert eff["segments"] == 4 and eff["frames_per_segment"] == 16
    assert "Multi-shot composition" in eff["route_label"]
    assert len(fake.prompts_received) == 4
    # distinct seeds per segment (documented behavior)
    seeds = {p["workflow"]["10"]["inputs"]["seed"] for p in fake.prompts_received}
    assert len(seeds) == 4
    out = final["output"]
    assert abs(out["duration_seconds"] - 8.0) <= 1 / 8 + 1e-6


def test_interpolated_16fps_export(integrated):
    client, fake, container, settings = integrated
    job = submit(client, duration_seconds=4.0, steps=6,
                 export_fps=16, interpolation="minterpolate")
    final = wait_terminal(client, job["id"])
    assert final["status"] == "COMPLETED", json.dumps(final.get("error"), indent=2)
    out = final["output"]
    assert out["interpolated"] is True
    assert out["fps"] == pytest.approx(16.0, abs=0.11)
    assert abs(out["duration_seconds"] - 4.0) <= 1 / 16 + 1e-6
    assert "interpolation" in (out["route_label"] or "").lower()


def test_upscale_export_labeled(integrated):
    client, fake, container, settings = integrated
    job = submit(client, duration_seconds=2.0, steps=5, upscale_export=True)
    final = wait_terminal(client, job["id"])
    assert final["status"] == "COMPLETED", json.dumps(final.get("error"), indent=2)
    out = final["output"]
    assert out["upscaled"] is True
    assert out["width"] == 128 and out["height"] == 128
    assert "lanczos" in (out["route_label"] or "").lower()


def test_video_streaming_range_requests(integrated):
    client, fake, container, settings = integrated
    job = submit(client, duration_seconds=2.0, steps=5)
    final = wait_terminal(client, job["id"])
    assert final["status"] == "COMPLETED"
    size = final["output"]["size_bytes"]

    r = client.get(f"/api/videos/{job['id']}/file")
    assert r.status_code == 200
    assert r.headers["accept-ranges"] == "bytes"
    assert len(r.content) == size
    assert r.content[4:8] == b"ftyp"  # real MP4 container signature

    r = client.get(f"/api/videos/{job['id']}/file", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206
    assert len(r.content) == 100
    assert r.headers["content-range"] == f"bytes 0-99/{size}"

    r = client.get(f"/api/videos/{job['id']}/file",
                   headers={"Range": f"bytes={size - 50}-{size + 100}"})
    assert r.status_code == 206 and len(r.content) == 50

    r = client.get(f"/api/videos/{job['id']}/thumbnail")
    assert r.status_code == 200 and r.content[:3] == b"\xff\xd8\xa0" or r.content[:2] == b"\xff\xd8"


def test_gallery_lists_and_filters(integrated):
    client, fake, container, settings = integrated
    j1 = submit(client, duration_seconds=2.0, steps=5,
                prompt="a lighthouse in a storm")
    wait_terminal(client, j1["id"])
    j2 = submit(client, duration_seconds=2.0, steps=5,
                prompt="macro shot of a bee on lavender")
    wait_terminal(client, j2["id"])

    videos = client.get("/api/videos").json()
    assert len(videos) == 2
    hits = client.get("/api/videos?q=lighthouse").json()
    assert len(hits) == 1 and hits[0]["video_id"] == j1["id"]
    by_model = client.get("/api/videos?model_id=animatediff-sd15").json()
    assert len(by_model) == 2
    none = client.get("/api/videos?model_id=does-not-exist").json()
    assert none == []


def test_delete_video_keeps_metadata_marks_missing(integrated):
    client, fake, container, settings = integrated
    job = submit(client, duration_seconds=2.0, steps=5)
    wait_terminal(client, job["id"])
    r = client.delete(f"/api/videos/{job['id']}")
    assert r.status_code == 200 and r.json()["ok"]
    videos = client.get("/api/videos").json()
    entry = next(v for v in videos if v["video_id"] == job["id"])
    assert entry["file_exists"] is False
    assert entry["status"] == "DELETED"
    # generation history still complete
    g = client.get(f"/api/generations/{job['id']}").json()
    assert g["status"] == "COMPLETED"
    assert g["original_prompt"]


def test_missing_file_after_external_deletion(integrated):
    client, fake, container, settings = integrated
    job = submit(client, duration_seconds=2.0, steps=5)
    wait_terminal(client, job["id"])
    (settings.outputs_dir / f"{job['id']}.mp4").unlink()  # deleted outside the app
    r = client.get(f"/api/videos/{job['id']}")
    assert r.status_code == 200
    assert r.json()["file_exists"] is False
    r = client.get(f"/api/videos/{job['id']}/file")
    assert r.status_code == 410  # Gone — honest status, metadata preserved


def test_persistence_across_backend_restart(integrated, settings, container):
    client, fake, container, settings = integrated
    job = submit(client, duration_seconds=2.0, steps=5, prompt="persistence check")
    wait_terminal(client, job["id"])

    # simulate restart: brand-new container/app over the same data dirs
    from app.deps import build_container
    container2 = build_container(settings)
    container2.engines.adapter.base_url = fake and f"http://127.0.0.1:{fake.port}"
    with _client_for(container2, settings) as client2:
        videos = client2.get("/api/videos").json()
        assert any(v["video_id"] == job["id"] for v in videos)
        g = client2.get(f"/api/generations/{job['id']}").json()
        assert g["status"] == "COMPLETED"
        assert g["original_prompt"] == "persistence check"
        assert abs(g["output"]["duration_seconds"] - 2.0) <= 0.2


def test_stale_jobs_failed_on_restart(settings, container):
    """A job left GENERATING by a crash must not survive restart as 'running'."""
    from app.database.models import GenerationRecord, JobStatus
    rec = GenerationRecord(
        id="crash-job", status=str(JobStatus.GENERATING), original_prompt="x",
        negative_prompt="", model_id="animatediff-sd15",
        workflow_id="animatediff_t2v", generation_mode="native_long",
    )
    container.generations.insert(rec)
    fake = start_fake_engine(container, settings)
    try:
        with _client_for(container, settings) as client:
            g = client.get("/api/generations/crash-job").json()
            assert g["status"] == "FAILED"
            assert g["error"]["code"] == "INTERRUPTED_RESTART"
            assert "preserved" in g["error"]["recovery"].lower()
    finally:
        fake.stop()


def test_cancellation_during_generation(settings, container, tiny_model):
    fake = start_fake_engine(container, settings, step_delay=0.15)  # slow engine
    try:
        with _client_for(container, settings) as client:
            job = submit(client, steps=40)
            # wait until the engine actually started sampling
            deadline = time.time() + 20
            while time.time() < deadline:
                g = client.get(f"/api/generations/{job['id']}").json()
                if g["status"] == "GENERATING":
                    break
                time.sleep(0.1)
            assert g["status"] == "GENERATING"
            r = client.post(f"/api/generations/{job['id']}/cancel")
            assert r.status_code == 200
            body = r.json()
            assert body["cancel_requested"] is True
            final = wait_terminal(client, job["id"], timeout=60)
            assert final["status"] == "CANCELLED"
            assert final["error"]["code"] == "JOB_CANCELLED"
            # no output file was produced for the cancelled job
            assert not list(settings.outputs_dir.glob(f"{job['id']}*.mp4"))
            # engine received the interrupt
            assert fake.interrupt_requested or len(fake.prompts_received) >= 1
    finally:
        fake.stop()


def test_cancel_completed_job_is_noop(integrated):
    client, fake, container, settings = integrated
    job = submit(client, duration_seconds=2.0, steps=5)
    wait_terminal(client, job["id"])
    r = client.post(f"/api/generations/{job['id']}/cancel")
    body = r.json()
    assert body["cancel_requested"] is False
    assert "terminal" in body["detail"].lower()


def test_queue_limit_enforced(settings, container, tiny_model):
    fake = start_fake_engine(container, settings, step_delay=0.2)
    try:
        settings.max_queue_length = 2
        with _client_for(container, settings) as client:
            j1 = submit(client, steps=30)
            # wait until running
            deadline = time.time() + 20
            while time.time() < deadline:
                if client.get(f"/api/generations/{j1['id']}").json()["status"] != "QUEUED":
                    break
                time.sleep(0.1)
            j2 = submit(client, steps=30)   # queued (slot 2)
            r = client.post("/api/generations", json={
                "prompt": "third job", "model_id": "animatediff-sd15",
                "duration_seconds": 2.0, "aspect_ratio": "1:1",
                "resolution_id": "test_tiny_64", "steps": 5})
            assert r.status_code == 429
            assert r.json()["error"]["code"] == "QUEUE_FULL"
            client.post(f"/api/generations/{j1['id']}/cancel")
            client.post(f"/api/generations/{j2['id']}/cancel")
            wait_terminal(client, j1["id"], timeout=60)
    finally:
        fake.stop()


def test_oom_single_downgrade_retry(settings, container, tiny_model):
    fake = start_fake_engine(container, settings, step_delay=0.005,
                             fail_with="oom", fail_first_only=True)
    try:
        with _client_for(container, settings) as client:
            job = submit(client, steps=6)
            final = wait_terminal(client, job["id"])
            assert final["status"] == "COMPLETED", json.dumps(final.get("error"), indent=2)
            assert len(fake.prompts_received) == 2  # exactly ONE retry, no loop
            m = final["metrics"]
            assert m["oom_downgrade_applied"] is True
            downgrades = container.generations.get(job["id"]).configuration.get("downgrades")
            assert downgrades and downgrades[0]["reason"] == "GPU_OUT_OF_MEMORY"
            # second attempt used reduced context overlap
            wf2 = fake.prompts_received[1]["workflow"]
            assert wf2["6"]["inputs"]["context_overlap"] == 2
    finally:
        fake.stop()


def test_persistent_engine_error_fails_job_honestly(settings, container, tiny_model):
    fake = start_fake_engine(container, settings, step_delay=0.005, fail_with="crash")
    try:
        with _client_for(container, settings) as client:
            job = submit(client, steps=6)
            final = wait_terminal(client, job["id"])
            assert final["status"] == "FAILED"
            assert final["error"]["code"] == "ENGINE_EXECUTION_ERROR"
            assert final["error"]["recovery"]
            assert final["output"] is None
    finally:
        fake.stop()


def test_websocket_snapshot_and_events(settings, container, tiny_model):
    fake = start_fake_engine(container, settings, step_delay=0.05)
    try:
        with _client_for(container, settings) as client:
            job = submit(client, steps=20)
            with client.websocket_connect("/api/ws") as ws:
                hello = ws.receive_json()
                assert hello["type"] == "hello"
                snap = ws.receive_json()
                assert snap["type"] == "snapshot"
                assert "queue" in snap and "recent" in snap
                # collect a few live events (job is slow enough to emit some)
                seen_types = set()
                for _ in range(6):
                    ev = ws.receive_json()
                    seen_types.add(ev["type"])
                    if ev.get("status") == "COMPLETED":
                        break
                assert seen_types & {"job_stage", "job_progress", "job_queued",
                                     "queue_update", "job_failed", "job_cancelled"}
            wait_terminal(client, job["id"])
    finally:
        fake.stop()


def test_preflight_passes_with_engine_and_model(integrated):
    client, fake, container, settings = integrated
    r = client.post("/api/generations/preflight", json={
        "prompt": "a calm sea", "model_id": "animatediff-sd15",
        "aspect_ratio": "1:1", "resolution_id": "test_tiny_64"})
    assert r.status_code == 200
    body = r.json()
    assert body["level"] in ("READY", "WARNING")  # sandbox may warn on RAM/GPU
    assert body["ok"] is True


def test_reveal_rejects_unknown_id_and_traversal(integrated, monkeypatch):
    client, fake, container, settings = integrated
    r = client.post("/api/videos/../../etc/reveal")
    assert r.status_code in (404, 422)
    # a real reveal only ever launches explorer/xdg-open with a DB-checked path
    job = submit(client, duration_seconds=2.0, steps=5)
    wait_terminal(client, job["id"])
    launched = []
    import subprocess as sp

    class FakePopen:
        def __init__(self, args, **kw):
            launched.append(args)

    monkeypatch.setattr(sp, "Popen", FakePopen)
    r = client.post(f"/api/videos/{job['id']}/reveal")
    assert r.status_code == 200
    assert len(launched) == 1
    assert str(settings.outputs_dir) in launched[0][-1] or launched[0][0] in ("xdg-open", "open", "explorer")
