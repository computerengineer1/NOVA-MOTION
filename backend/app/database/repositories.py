"""Repositories: the only code that reads/writes DB rows.

Every row->dataclass conversion is defensive: a malformed record is logged and
skipped (or returned with defaults) instead of crashing the application.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..logging_config import get_logger
from .db import Database
from .models import GenerationRecord

log = get_logger(__name__)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _loads(raw: str | None, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        log.warning("Malformed JSON column value; using fallback %r", fallback)
        return fallback


class GenerationRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- write ----------------------------------------------------------
    def insert(self, rec: GenerationRecord) -> None:
        now = utcnow_iso()
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO generations (
                    id, status, stage_detail, progress, original_prompt, negative_prompt,
                    seed, model_id, workflow_id, generation_mode, configuration_json,
                    engine_job_ids_json, interpolated, upscaled, metrics_json,
                    created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    rec.id, rec.status, rec.stage_detail, rec.progress,
                    rec.original_prompt, rec.negative_prompt, rec.seed,
                    rec.model_id, rec.workflow_id, rec.generation_mode,
                    json.dumps(rec.configuration), json.dumps(rec.engine_job_ids),
                    int(rec.interpolated), int(rec.upscaled), json.dumps(rec.metrics),
                    now, now,
                ),
            )

    def update(self, generation_id: str, **fields: Any) -> None:
        if not fields:
            return
        allowed = {
            "status", "stage_detail", "progress", "seed", "engine_job_ids_json",
            "configuration_json", "output_path", "thumbnail_path",
            "actual_duration_seconds", "actual_width", "actual_height", "actual_fps",
            "output_size_bytes", "output_codec", "interpolated", "upscaled",
            "error_code", "safe_error_summary", "error_recovery", "error_detail_log_ref",
            "metrics_json", "started_at", "completed_at",
        }
        sets, params = [], []
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"Field not updatable: {key}")
            sets.append(f"{key}=?")
            params.append(value)
        sets.append("updated_at=?")
        params.append(utcnow_iso())
        params.append(generation_id)
        with self.db.connect() as conn:
            cur = conn.execute(
                f"UPDATE generations SET {', '.join(sets)} WHERE id=?", params
            )
            if cur.rowcount == 0:
                log.warning("Update targeted missing generation %s", generation_id)

    # -- read -----------------------------------------------------------
    def _row_to_record(self, row) -> GenerationRecord | None:
        def _float(key: str, default=None):
            try:
                raw = row[key]
                return default if raw is None else float(raw)
            except (KeyError, ValueError, TypeError):
                log.warning("Malformed numeric column %r in generation row; using default.", key)
                return default

        def _int(key: str, default=None):
            value = _float(key, default)
            return default if value is None else int(value)

        try:
            return GenerationRecord(
                id=row["id"],
                status=row["status"],
                original_prompt=row["original_prompt"],
                negative_prompt=row["negative_prompt"] or "",
                model_id=row["model_id"],
                workflow_id=row["workflow_id"],
                generation_mode=row["generation_mode"],
                configuration=_loads(row["configuration_json"], {}),
                engine_job_ids=_loads(row["engine_job_ids_json"], []),
                seed=_int("seed"),
                stage_detail=row["stage_detail"],
                progress=_float("progress", 0.0) or 0.0,
                output_path=row["output_path"],
                thumbnail_path=row["thumbnail_path"],
                actual_duration_seconds=_float("actual_duration_seconds"),
                actual_width=_int("actual_width"),
                actual_height=_int("actual_height"),
                actual_fps=_float("actual_fps"),
                output_size_bytes=_int("output_size_bytes"),
                output_codec=row["output_codec"],
                interpolated=bool(_int("interpolated", 0)),
                upscaled=bool(_int("upscaled", 0)),
                error_code=row["error_code"],
                safe_error_summary=row["safe_error_summary"],
                error_recovery=row["error_recovery"],
                error_detail_log_ref=row["error_detail_log_ref"],
                metrics=_loads(row["metrics_json"], {}),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                started_at=row["started_at"],
                completed_at=row["completed_at"],
            )
        except (KeyError, TypeError) as exc:
            log.error("Skipping malformed generation row %r: %s",
                      row["id"] if "id" in row.keys() else "?", exc)
            return None

    def get(self, generation_id: str) -> GenerationRecord | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM generations WHERE id=?", (generation_id,)
            ).fetchone()
        return self._row_to_record(row) if row else None

    def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        status: str | None = None,
    ) -> list[GenerationRecord]:
        query = "SELECT * FROM generations"
        params: list[Any] = []
        if status:
            query += " WHERE status=?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self.db.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        out = []
        for row in rows:
            rec = self._row_to_record(row)
            if rec is not None:
                out.append(rec)
        return out

    def list_active(self) -> list[GenerationRecord]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM generations WHERE status NOT IN
                   ('COMPLETED','FAILED','CANCELLED') ORDER BY created_at ASC"""
            ).fetchall()
        out = []
        for row in rows:
            rec = self._row_to_record(row)
            if rec is not None:
                out.append(rec)
        return out

    def mark_stale_active_as_failed(self, code: str, summary: str, recovery: str) -> int:
        """Startup recovery: jobs left active by a crash/restart are failed cleanly."""
        active = self.list_active()
        for rec in active:
            try:
                self.update(
                    rec.id,
                    status="FAILED",
                    error_code=code,
                    safe_error_summary=summary,
                    error_recovery=recovery,
                    completed_at=utcnow_iso(),
                    stage_detail=None,
                )
            except Exception:  # noqa: BLE001 — containment by design
                log.exception("Failed to mark stale job %s", rec.id)
        return len(active)


class ModelRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert(
        self,
        model_id: str,
        *,
        version: str | None = None,
        source: str | None = None,
        license_: str | None = None,
        installation_path: str | None = None,
        installed_files: list[dict] | None = None,
        validation_status: str = "unknown",
        validation_note: str | None = None,
    ) -> None:
        now = utcnow_iso()
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO models (model_id, version, source, license,
                       installation_path, installed_files_json, validation_status,
                       validation_note, last_validated_at, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(model_id) DO UPDATE SET
                       version=excluded.version,
                       source=excluded.source,
                       license=excluded.license,
                       installation_path=excluded.installation_path,
                       installed_files_json=excluded.installed_files_json,
                       validation_status=excluded.validation_status,
                       validation_note=excluded.validation_note,
                       last_validated_at=excluded.last_validated_at,
                       updated_at=excluded.updated_at""",
                (
                    model_id, version, source, license_, installation_path,
                    json.dumps(installed_files or []), validation_status,
                    validation_note, now, now, now,
                ),
            )

    def get(self, model_id: str) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM models WHERE model_id=?", (model_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def list(self) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM models ORDER BY model_id").fetchall()
        out = []
        for row in rows:
            d = self._row_to_dict(row)
            if d:
                out.append(d)
        return out

    def delete(self, model_id: str) -> None:
        with self.db.connect() as conn:
            conn.execute("DELETE FROM models WHERE model_id=?", (model_id,))

    @staticmethod
    def _row_to_dict(row) -> dict | None:
        try:
            return {
                "model_id": row["model_id"],
                "version": row["version"],
                "source": row["source"],
                "license": row["license"],
                "installation_path": row["installation_path"],
                "installed_files": _loads(row["installed_files_json"], []),
                "validation_status": row["validation_status"],
                "validation_note": row["validation_note"],
                "last_validated_at": row["last_validated_at"],
            }
        except (KeyError, TypeError) as exc:
            log.error("Skipping malformed model row: %s", exc)
            return None


class SettingsRepository:
    DEFAULTS: dict[str, Any] = {
        "default_model_id": "animatediff-sd15",
        "default_steps": 16,
        "default_cfg": 7.5,
        "default_sampler": "dpmpp_2m",
        "default_scheduler": "karras",
        "default_aspect_ratio": "16:9",
        "default_duration_seconds": 8.0,
        "default_generation_mode": "auto",
        "default_export_fps": 8,
        "default_interpolation": "none",
        "default_upscale_export": False,
        "random_seed_default": True,
        "oom_auto_downgrade_once": True,
    }

    def __init__(self, db: Database) -> None:
        self.db = db

    def get_all(self) -> dict[str, Any]:
        values = dict(self.DEFAULTS)
        try:
            with self.db.connect() as conn:
                rows = conn.execute("SELECT key, value_json FROM settings").fetchall()
            for row in rows:
                try:
                    values[row["key"]] = json.loads(row["value_json"])
                except (ValueError, TypeError):
                    log.warning("Ignoring corrupt setting %r", row["key"])
        except Exception:  # noqa: BLE001
            log.exception("Settings read failed; falling back to defaults")
        return values

    def set(self, key: str, value: Any) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO settings (key, value_json, updated_at) VALUES (?,?,?)
                   ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,
                       updated_at=excluded.updated_at""",
                (key, json.dumps(value), utcnow_iso()),
            )

    def update_many(self, items: dict[str, Any]) -> None:
        for key, value in items.items():
            self.set(key, value)
