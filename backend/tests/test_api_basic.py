"""API surface tests (no engine required — honest NOT_READY states expected)."""
from __future__ import annotations

import pytest


def test_health_is_liveness_only(app_client):
    r = app_client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_system_report_structure_and_honesty(app_client):
    r = app_client.get("/api/system")
    assert r.status_code == 200
    body = r.json()
    # measured fields exist; engine offline in this fixture => NOT_READY
    assert body["memory"]["available"] in (True, False)
    assert body["engine"]["online"] is False
    assert body["readiness"]["level"] == "NOT_READY"
    reasons = " ".join(body["readiness"]["reasons"])
    assert "engine" in reasons.lower() or "model" in reasons.lower()
    # RAM fields distinguish total vs available (never conflated)
    if body["memory"]["available"]:
        assert body["memory"]["total_gb"] >= body["memory"]["available_gb"]


def test_engine_status_offline(app_client):
    r = app_client.get("/api/engine/status")
    assert r.status_code == 200
    assert r.json()["online"] is False


def test_models_list_shows_incompatible_with_reasons(app_client):
    r = app_client.get("/api/models")
    assert r.status_code == 200
    models = {m["model_id"]: m for m in r.json()}
    assert models["animatediff-sd15"]["status"] == "recommended"
    assert models["animatediff-sd15"]["installed"] is False
    assert models["ltx-2"]["status"] == "incompatible"
    assert "8 GB" in models["ltx-2"]["capabilities"]["incompatible_reason"]
    # licenses documented for every installable profile
    assert "Apache-2.0" in models["animatediff-sd15"]["license_id"]
    assert "OpenRAIL" in models["animatediff-sd15"]["license_id"]


def test_install_refuses_incompatible_model(app_client):
    r = app_client.post("/api/models/install", json={"model_id": "ltx-2",
                                                     "accept_license": True})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "MODEL_NOT_INSTALLED"


def test_install_refuses_unknown_model(app_client):
    r = app_client.post("/api/models/install", json={"model_id": "totally-made-up",
                                                     "accept_license": True})
    assert r.status_code in (404, 422)


def test_delete_requires_confirmation_match(app_client):
    r = app_client.request("DELETE", "/api/models/animatediff-sd15",
                           json={"confirm_model_id": "something-else"})
    assert r.status_code == 422


def test_validate_missing_model_reports_invalid(app_client):
    r = app_client.post("/api/models/validate?model_id=animatediff-sd15")
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    assert any(not f["installed"] for f in body["files"])


def test_settings_get_and_patch_validation(app_client):
    r = app_client.get("/api/settings")
    assert r.status_code == 200
    assert r.json()["default_duration_seconds"] == 8.0

    r = app_client.patch("/api/settings", json={"values": {"default_steps": 20}})
    assert r.status_code == 200 and r.json()["default_steps"] == 20

    r = app_client.patch("/api/settings", json={"values": {"default_steps": 999}})
    assert r.status_code == 422

    r = app_client.patch("/api/settings", json={"values": {"evil_key": 1}})
    assert r.status_code == 422


def test_generation_validation_rejects_bad_requests(app_client):
    r = app_client.post("/api/generations", json={"prompt": "", "model_id": "animatediff-sd15"})
    assert r.status_code == 422

    r = app_client.post("/api/generations", json={
        "prompt": "x", "model_id": "animatediff-sd15", "duration_seconds": 7.5})
    assert r.status_code == 422


def test_generation_blocked_when_model_not_installed(app_client):
    r = app_client.post("/api/generations", json={
        "prompt": "a serene lake at dawn", "model_id": "animatediff-sd15"})
    # submission itself is accepted (queued); the job then FAILS in preflight
    # OR the API rejects up-front — either way the user gets a clear error, and
    # the app never fabricates success.
    if r.status_code == 201:
        job = r.json()
        import time
        for _ in range(50):
            g = app_client.get(f"/api/generations/{job['id']}").json()
            if g["status"] in ("FAILED", "COMPLETED", "CANCELLED"):
                break
            time.sleep(0.1)
        assert g["status"] == "FAILED"
        assert g["error"]["code"] in ("MODEL_FILE_MISSING", "ENGINE_UNREACHABLE",
                                      "MODEL_NOT_INSTALLED")
    else:
        assert r.status_code in (409, 503)


def test_preflight_endpoint_reports_blockers(app_client):
    r = app_client.post("/api/generations/preflight", json={
        "prompt": "a cat", "model_id": "animatediff-sd15"})
    assert r.status_code == 200
    body = r.json()
    assert body["level"] == "BLOCKED"
    assert body["blockers"]


def test_presets_and_examples(app_client):
    r = app_client.get("/api/generations/meta/presets")
    assert r.status_code == 200
    body = r.json()
    assert len(body["presets"]) == 10
    assert body["default_negative_prompt"]
    assert len(body["examples"]) >= 5


def test_enhance_endpoint(app_client):
    r = app_client.post("/api/generations/meta/enhance",
                        json={"prompt": "a lighthouse", "style_preset": "horror_suspense"})
    assert r.status_code == 200
    body = r.json()
    assert body["enhanced_prompt"].startswith("a lighthouse")
    assert body["method"] == "template"
    assert body["original_preserved"] is True


def test_unknown_generation_404(app_client):
    r = app_client.get("/api/generations/nope-123")
    assert r.status_code == 404


def test_videos_empty_initially(app_client):
    r = app_client.get("/api/videos")
    assert r.status_code == 200 and r.json() == []


def test_video_file_404_for_unknown(app_client):
    r = app_client.get("/api/videos/does-not-exist/file")
    assert r.status_code in (404, 422)


def test_error_envelope_shape(app_client):
    r = app_client.post("/api/models/validate?model_id=../../etc")
    assert r.status_code == 422
    err = r.json()["error"]
    assert {"code", "summary"} <= set(err.keys())


def test_logs_endpoints(app_client):
    r = app_client.get("/api/logs/app?lines=5")
    assert r.status_code == 200
    r = app_client.get("/api/logs/diagnostic")
    assert r.status_code == 200
    body = r.json()
    assert body["system"]["engine"]["online"] is False
    assert "note" in body  # privacy note present


def test_cors_localhost_only(app_client):
    r = app_client.options("/api/health", headers={
        "Origin": "http://evil.example.com",
        "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in {k.lower(): v for k, v in r.headers.items()} \
        or r.headers.get("access-control-allow-origin") != "http://evil.example.com"
    r = app_client.get("/api/health", headers={"Origin": "http://localhost:8317"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:8317"
