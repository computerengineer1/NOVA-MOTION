"""SQLite access layer (stdlib sqlite3 — no external DB dependency).

Design notes:
  * One connection per thread of execution is avoided; we open short-lived
    connections per operation with WAL mode, which is robust for a
    single-user desktop app and survives crashes (WAL recovers on open).
  * Schema versioning via `schema_version` table with forward-only
    migrations. A malformed row anywhere is contained by the repositories
    (they never let one bad record crash the app).
  * The DB file lives in `<project>/data/nova.db`. Nothing here requires
    network access.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..logging_config import get_logger

log = get_logger(__name__)

SCHEMA_VERSION = 1

_DDL_V1 = """
CREATE TABLE IF NOT EXISTS generations (
    id                    TEXT PRIMARY KEY,
    status                TEXT NOT NULL,
    stage_detail          TEXT,
    progress              REAL NOT NULL DEFAULT 0,
    original_prompt       TEXT NOT NULL,
    negative_prompt       TEXT NOT NULL DEFAULT '',
    seed                  INTEGER,
    model_id              TEXT NOT NULL,
    workflow_id           TEXT NOT NULL,
    generation_mode       TEXT NOT NULL,
    configuration_json    TEXT NOT NULL DEFAULT '{}',
    engine_job_ids_json   TEXT NOT NULL DEFAULT '[]',
    output_path           TEXT,
    thumbnail_path        TEXT,
    actual_duration_seconds REAL,
    actual_width          INTEGER,
    actual_height         INTEGER,
    actual_fps            REAL,
    output_size_bytes     INTEGER,
    output_codec          TEXT,
    interpolated          INTEGER NOT NULL DEFAULT 0,
    upscaled              INTEGER NOT NULL DEFAULT 0,
    error_code            TEXT,
    safe_error_summary    TEXT,
    error_recovery        TEXT,
    error_detail_log_ref  TEXT,
    metrics_json          TEXT NOT NULL DEFAULT '{}',
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    started_at            TEXT,
    completed_at          TEXT
);
CREATE INDEX IF NOT EXISTS idx_generations_status ON generations(status);
CREATE INDEX IF NOT EXISTS idx_generations_created ON generations(created_at);

CREATE TABLE IF NOT EXISTS models (
    model_id          TEXT PRIMARY KEY,
    version           TEXT,
    source            TEXT,
    license           TEXT,
    installation_path TEXT,
    installed_files_json TEXT NOT NULL DEFAULT '[]',
    validation_status TEXT NOT NULL DEFAULT 'unknown',
    validation_note   TEXT,
    last_validated_at TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_MIGRATIONS: dict[int, str] = {1: _DDL_V1}


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=10000")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        """Create/upgrade schema. Idempotent and crash-safe."""
        with self._lock, self.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
            )
            row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
            current = int(row["v"] or 0)
            for version in sorted(_MIGRATIONS):
                if version > current:
                    log.info("Applying DB migration -> v%s", version)
                    conn.executescript(_MIGRATIONS[version])
                    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
                    current = version
        self._integrity_check()

    def _integrity_check(self) -> None:
        """Quick integrity probe; a corrupt DB is reported, never silently wiped."""
        try:
            with self.connect() as conn:
                result = conn.execute("PRAGMA integrity_check").fetchone()
                status = result[0] if result else "unknown"
                if status != "ok":
                    log.error("SQLite integrity_check returned: %s", status)
        except sqlite3.DatabaseError as exc:
            log.error(
                "Database appears corrupt (%s). Your data file is %s — it will NOT be "
                "deleted automatically. See TROUBLESHOOTING.md §database.",
                exc, self.db_path,
            )
            raise
