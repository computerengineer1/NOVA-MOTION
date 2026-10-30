"""Database, repository resilience, and job state-machine tests."""
from __future__ import annotations

import json

import pytest

from app.database.db import Database
from app.database.models import JobStatus, can_transition
from app.database.repositories import GenerationRepository, ModelRepository, SettingsRepository
from app.database.models import GenerationRecord


@pytest.fixture()
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    d.initialize()
    d.initialize()  # idempotent
    return d


def make_record(id="job-1", status=JobStatus.QUEUED, **kw) -> GenerationRecord:
    return GenerationRecord(
        id=id, status=str(status), original_prompt=kw.pop("prompt", "test prompt"),
        negative_prompt="", model_id="animatediff-sd15", workflow_id="animatediff_t2v",
        generation_mode="native_long", **kw,
    )


def test_insert_and_get(db):
    repo = GenerationRepository(db)
    repo.insert(make_record(seed=42, configuration={"a": 1}))
    rec = repo.get("job-1")
    assert rec is not None
    assert rec.seed == 42
    assert rec.configuration == {"a": 1}


def test_update_only_allowed_fields(db):
    repo = GenerationRepository(db)
    repo.insert(make_record())
    repo.update("job-1", status="GENERATING", progress=0.5)
    rec = repo.get("job-1")
    assert rec.status == "GENERATING" and rec.progress == 0.5
    with pytest.raises(ValueError):
        repo.update("job-1", original_prompt="hacked")  # immutable


def test_malformed_row_does_not_crash_listing(db):
    repo = GenerationRepository(db)
    repo.insert(make_record(id="good-1"))
    # corrupt a row behind the repository's back
    with db.connect() as conn:
        conn.execute(
            "UPDATE generations SET configuration_json=?, progress=? WHERE id=?",
            ("{not json", "NaN-ish", "good-1"),
        )
    rec = repo.get("good-1")
    assert rec is not None
    assert rec.configuration == {}  # fallback, no exception
    repo.insert(make_record(id="good-2"))
    assert len(repo.list()) == 2


def test_stale_active_jobs_marked_failed_on_startup(db):
    repo = GenerationRepository(db)
    repo.insert(make_record(id="stale-1", status=JobStatus.GENERATING))
    repo.insert(make_record(id="stale-2", status=JobStatus.QUEUED))
    repo.insert(make_record(id="done-1", status=JobStatus.COMPLETED))
    count = repo.mark_stale_active_as_failed(
        "INTERRUPTED_RESTART", "Backend restarted.", "Retry safely.")
    assert count == 2
    assert repo.get("stale-1").status == "FAILED"
    assert repo.get("stale-1").error_code == "INTERRUPTED_RESTART"
    assert repo.get("stale-2").status == "FAILED"
    assert repo.get("done-1").status == "COMPLETED"
    assert repo.list_active() == []


def test_settings_defaults_and_roundtrip(db):
    repo = SettingsRepository(db)
    values = repo.get_all()
    assert values["default_duration_seconds"] == 8.0
    repo.set("default_steps", 20)
    assert repo.get_all()["default_steps"] == 20


def test_settings_corrupt_value_ignored(db):
    repo = SettingsRepository(db)
    with db.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value_json, updated_at) VALUES (?,?,?)",
            ("default_steps", "{{{corrupt", "now"),
        )
    values = repo.get_all()
    assert values["default_steps"] == SettingsRepository.DEFAULTS["default_steps"]


def test_model_repo_upsert_and_delete(db):
    repo = ModelRepository(db)
    repo.upsert("m1", version="v", source="s", license_="Apache-2.0",
                installed_files=[{"id": "f"}], validation_status="valid")
    row = repo.get("m1")
    assert row["validation_status"] == "valid"
    repo.upsert("m1", validation_status="invalid", validation_note="missing file")
    assert repo.get("m1")["validation_status"] == "invalid"
    repo.delete("m1")
    assert repo.get("m1") is None


@pytest.mark.parametrize("src,dst,allowed", [
    (JobStatus.QUEUED, JobStatus.PREFLIGHT, True),
    (JobStatus.QUEUED, JobStatus.GENERATING, False),
    (JobStatus.GENERATING, JobStatus.ASSEMBLING, True),
    (JobStatus.GENERATING, JobStatus.COMPLETED, False),
    (JobStatus.ASSEMBLING, JobStatus.INTERPOLATING, True),
    (JobStatus.ASSEMBLING, JobStatus.ENCODING, True),
    (JobStatus.VALIDATING, JobStatus.COMPLETED, True),
    (JobStatus.COMPLETED, JobStatus.FAILED, False),
    (JobStatus.FAILED, JobStatus.QUEUED, False),
    (JobStatus.CANCELLED, JobStatus.GENERATING, False),
    (JobStatus.GENERATING, JobStatus.CANCELLED, True),
    (JobStatus.PREFLIGHT, JobStatus.FAILED, True),
])
def test_state_machine_transitions(src, dst, allowed):
    assert can_transition(src, dst) is allowed
