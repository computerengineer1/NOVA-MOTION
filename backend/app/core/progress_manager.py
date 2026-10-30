"""Progress pub/sub for job state + fine-grained progress.

Sources: job manager (stage transitions) and the engine WS listener (step
progress). Sinks: per-subscriber asyncio queues drained by the /api/ws
endpoint, plus a ring buffer so a browser that reconnects (or a fresh page
load mid-generation) immediately gets the current state without waiting for
the next event.

ETA policy: an ETA is published ONLY after at least two real progress
observations, computed from the measured rate. Otherwise eta_seconds is None
— the UI must not show invented remaining times.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any

from ..logging_config import get_logger

log = get_logger(__name__)

RING_SIZE = 40


class ProgressManager:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._ring: deque[dict[str, Any]] = deque(maxlen=RING_SIZE)
        self._latest_by_job: dict[str, dict[str, Any]] = {}
        # rate estimation state per (job, segment)
        self._rate_state: dict[str, tuple[float, float, float]] = {}  # key -> (t0, v0, last_rate)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, event: dict[str, Any]) -> None:
        event = dict(event)
        event.setdefault("ts", time.time())
        self._ring.append(event)
        job_id = event.get("job_id")
        if job_id:
            self._latest_by_job[str(job_id)] = event
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                log.debug("Progress subscriber too slow; dropping event.")

    def latest(self, job_id: str) -> dict[str, Any] | None:
        return self._latest_by_job.get(job_id)

    def snapshot(self) -> list[dict[str, Any]]:
        """Recent event history for reconnecting clients."""
        return list(self._ring)

    # -- step-rate based progress helpers ---------------------------------
    def report_steps(self, job_id: str, segment_index: int, segment_count: int,
                     value: int, max_value: int, node_type: str = "") -> None:
        """Translate engine step progress into job progress with honest ETA."""
        if max_value <= 0:
            return
        seg_frac = value / max_value
        overall = (segment_index + seg_frac) / max(segment_count, 1)
        key = f"{job_id}:{segment_index}"
        now = time.monotonic()
        eta_seconds: float | None = None
        prev = self._rate_state.get(key)
        if prev is not None and value > prev[1]:
            dt = now - prev[0]
            dv = value - prev[1]
            if dt > 0.5 and dv > 0:
                steps_per_s = dv / dt
                remaining_steps = (max_value - value) + max_value * (segment_count - segment_index - 1)
                eta_seconds = round(remaining_steps / steps_per_s, 1)
                self._rate_state[key] = (now, value, steps_per_s)
        elif prev is None:
            self._rate_state[key] = (now, value, 0.0)
        self.publish({
            "type": "job_progress",
            "job_id": job_id,
            "status": "GENERATING",
            "progress": round(min(max(overall, 0.0), 1.0), 4),
            "stage_detail": f"Sampling step {value}/{max_value} "
                            f"(segment {segment_index + 1}/{segment_count})"
                            + (f" [{node_type}]" if node_type else ""),
            "eta_seconds": eta_seconds,  # None until measurable — never invented
        })

    def report_stage(self, job_id: str, status: str, detail: str | None = None,
                     progress: float | None = None) -> None:
        event: dict[str, Any] = {"type": "job_stage", "job_id": job_id, "status": status}
        if detail is not None:
            event["stage_detail"] = detail
        if progress is not None:
            event["progress"] = round(progress, 4)
        self.publish(event)

    def clear_job(self, job_id: str) -> None:
        for key in [k for k in self._rate_state if k.startswith(f"{job_id}:")]:
            self._rate_state.pop(key, None)
