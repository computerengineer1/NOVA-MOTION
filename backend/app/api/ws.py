"""WebSocket progress endpoint with reconnect-safe snapshot delivery.

On connect the client immediately receives:
  * {"type":"hello", ...}
  * {"type":"snapshot", "queue":..., "active_jobs":[...], "recent":[...]}
then live events published by the ProgressManager.

If the socket drops, job state is unaffected (it lives in the job manager +
SQLite); the client reconnects and gets a fresh snapshot. The REST endpoint
GET /api/generations/{id} remains the source of truth.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..database.models import ACTIVE_STATUSES

router = APIRouter(tags=["ws"])


@router.websocket("/api/ws")
async def progress_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    container = websocket.app.state.container
    progress = container.progress

    # hello + snapshot
    active = [
        {
            "job_id": rec.id,
            "status": rec.status,
            "progress": rec.progress,
            "stage_detail": rec.stage_detail,
        }
        for rec in container.generations.list_active()
    ]
    try:
        await websocket.send_text(json.dumps({"type": "hello", "service": "nova-motion"}))
        await websocket.send_text(json.dumps({
            "type": "snapshot",
            "queue": container.jobs.queue_state(),
            "active_jobs": active,
            "recent": progress.snapshot(),
        }))
    except (WebSocketDisconnect, RuntimeError):
        return

    queue = progress.subscribe()
    try:
        while True:
            event = await queue.get()
            try:
                await websocket.send_text(json.dumps(event, default=str))
            except (WebSocketDisconnect, RuntimeError):
                break
    except asyncio.CancelledError:
        pass
    finally:
        progress.unsubscribe(queue)
        try:
            await websocket.close()
        except RuntimeError:
            pass
