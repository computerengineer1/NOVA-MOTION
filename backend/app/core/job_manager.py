"""Job manager: strictly sequential generation queue.

Policy (per hardware requirements — 4 GB VRAM / 8 GB RAM):
  * ONE generation runs at a time; the queue holds at most
    `max_queue_length` jobs total (default 2 = 1 running + 1 waiting).
    Additional submissions are rejected with a clear message — we never
    silently grow an unbounded queue on a machine this size.
  * Cancellation is cooperative + engine-interrupt backed. The terminal
    state is only reported once actually reached.
  * On backend restart, jobs left in active states are failed cleanly
    (INTERRUPTED_RESTART) — never silently resumed, never left "running".
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from ..config import Settings
from ..core.errors import ErrorCode, NovaError
from ..core.progress_manager import ProgressManager
from ..database.models import JobStatus, GenerationRecord
from ..database.repositories import GenerationRepository, utcnow_iso
from ..logging_config import get_logger
from ..schemas.generation import GenerationRequest
from ..services.generation_service import GenerationService

log = get_logger(__name__)


class JobManager:
    def __init__(
        self,
        settings: Settings,
        generations: GenerationRepository,
        generation_service: GenerationService,
        progress: ProgressManager,
    ) -> None:
        self.settings = settings
        self.generations = generations
        self.service = generation_service
        self.progress = progress
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._current_job_id: str | None = None
        self._records: dict[str, GenerationRecord] = {}

    # ------------------------------------------------------------- lifecycle
    async def startup(self) -> None:
        stale = self.generations.mark_stale_active_as_failed(
            ErrorCode.INTERRUPTED_RESTART,
            "NOVA MOTION was restarted while this generation was still active.",
            "Your prompt and settings were preserved. It is safe to submit the generation again.",
        )
        if stale:
            log.info("Marked %d stale active job(s) as FAILED(INTERRUPTED_RESTART).", stale)
        self._worker = asyncio.create_task(self._worker_loop(), name="job-worker")

    async def shutdown(self) -> None:
        if self._worker and not self._worker.done():
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------- submission
    def queue_state(self) -> dict[str, Any]:
        return {
            "running_job_id": self._current_job_id,
            "queued": self._queue.qsize(),
            "max_queue_length": self.settings.max_queue_length,
        }

    def submit(self, record: GenerationRecord) -> GenerationRecord:
        total_pending = self._queue.qsize() + (1 if self._current_job_id else 0)
        if total_pending >= self.settings.max_queue_length:
            raise NovaError(
                ErrorCode.QUEUE_FULL,
                "The generation queue is full (1 running + 1 waiting).",
                recovery="Wait for the current generation to finish, or cancel it. "
                         "This machine does not have enough RAM for more parallel work.",
                http_status=429,
            )
        self.generations.insert(record)
        self._records[record.id] = record
        self.service.register_cancel_event(record.id)  # single source of truth
        self._queue.put_nowait(record.id)
        log.info("Job %s queued (prompt=%.60s…)", record.id, record.original_prompt)
        self.progress.publish({
            "type": "job_queued", "job_id": record.id, "status": JobStatus.QUEUED,
            "progress": 0.0, "queue": self.queue_state(),
        })
        return record

    def request_cancel(self, job_id: str) -> tuple[bool, str]:
        record = self._records.get(job_id) or self.generations.get(job_id)
        if record is None:
            raise NovaError(ErrorCode.FILE_NOT_FOUND, f"No such job: {job_id}", http_status=404)
        if record.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return False, f"Job is already in terminal state {record.status}."
        # The GenerationService owns the cancel event (single source of truth);
        # its monitor loops observe exactly this object.
        event = self.service.register_cancel_event(job_id)
        event.set()
        # If still purely queued (worker hasn't picked it up), finalize now.
        if record.status == JobStatus.QUEUED and self._current_job_id != job_id:
            self._finalize_cancelled_queued(record)
            return True, "Queued job cancelled."
        return True, ("Cancellation requested — the engine is being interrupted. "
                      "The final state is reported once the engine confirms the stop.")

    def _finalize_cancelled_queued(self, record: GenerationRecord) -> None:
        try:
            self.generations.update(
                record.id, status=JobStatus.CANCELLED, stage_detail=None,
                error_code=ErrorCode.JOB_CANCELLED,
                safe_error_summary="Cancelled while queued (never started).",
                completed_at=utcnow_iso(),
            )
        except Exception:  # noqa: BLE001
            log.exception("Could not persist cancellation of queued job %s", record.id)
        record.status = JobStatus.CANCELLED
        self.progress.publish({"type": "job_cancelled", "job_id": record.id,
                               "status": JobStatus.CANCELLED})

    def current_record(self, job_id: str) -> GenerationRecord | None:
        return self._records.get(job_id) or self.generations.get(job_id)

    # ---------------------------------------------------------------- worker
    async def _worker_loop(self) -> None:
        while True:
            job_id = await self._queue.get()
            record = self._records.get(job_id) or self.generations.get(job_id)
            if record is None:
                self._queue.task_done()
                continue
            if record.status == JobStatus.CANCELLED:
                # cancelled while queued
                self._queue.task_done()
                continue
            self._current_job_id = job_id
            try:
                await self.service.execute(record)
            except asyncio.CancelledError:
                log.warning("Job worker cancelled during %s", job_id)
                raise
            except Exception:  # noqa: BLE001 — execute() contains its own errors
                log.exception("Worker-level failure for job %s", job_id)
            finally:
                cancel_event = self.service._cancel_events.get(job_id)
                if record.status == JobStatus.CANCELLED or (
                    record.status not in (JobStatus.COMPLETED, JobStatus.FAILED)
                    and cancel_event is not None and cancel_event.is_set()
                ):
                    try:
                        self.generations.update(
                            job_id, status=JobStatus.CANCELLED, stage_detail=None,
                            error_code=ErrorCode.JOB_CANCELLED,
                            safe_error_summary="Cancelled by user.",
                        )
                    except Exception:  # noqa: BLE001
                        log.exception("Could not persist CANCELLED for %s", job_id)
                    record.status = JobStatus.CANCELLED
                    self.progress.publish({"type": "job_cancelled", "job_id": job_id,
                                           "status": JobStatus.CANCELLED})
                self._current_job_id = None
                self.service.clear_cancel_event(job_id)
                fresh = self.generations.get(job_id)
                if fresh is not None:
                    self._records[job_id] = fresh
                self.progress.publish({
                    "type": "queue_update", "job_id": job_id,
                    "queue": self.queue_state(),
                })
                self._queue.task_done()
