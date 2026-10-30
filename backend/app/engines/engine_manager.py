"""Engine manager: owns the adapter lifecycle and the WS listener task.

Also implements bounded auto-recovery for the managed engine process:
if the managed process dies while the app runs, we try to restart it ONCE
(no infinite restart loops).
"""
from __future__ import annotations

import asyncio
import time

from ..config import Settings
from ..logging_config import get_logger
from .base import EngineAdapter, EngineStatus
from .comfyui_engine import ComfyUIEngine

log = get_logger(__name__)


class EngineManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.adapter: EngineAdapter = ComfyUIEngine(settings)
        self._ws_task: asyncio.Task | None = None
        self._watchdog_task: asyncio.Task | None = None
        self._restart_attempts = 0
        self._last_restart_ts = 0.0
        self.last_status: EngineStatus = EngineStatus(base_url=settings.engine_base_url)

    async def startup(self) -> None:
        comfy = self.adapter
        assert isinstance(comfy, ComfyUIEngine)
        status = await comfy.get_status(force=True)
        if not status.online and self.settings.autostart_engine:
            if comfy.can_manage_process():
                log.info("Engine offline — attempting managed autostart.")
                comfy.start_process()
                status = await comfy.wait_online(self.settings.engine_startup_timeout_s)
            else:
                log.warning(
                    "Engine offline and no managed installation found under %s. "
                    "Run scripts/Install-Studio.ps1 first.", comfy.settings.engine_dir,
                )
        self.last_status = status
        # WS loop lives for the app lifetime; harmless while engine is offline
        # (it keeps retrying with backoff and delivers events once connected).
        self._ws_task = asyncio.create_task(comfy.run_ws_loop(), name="comfy-ws")
        self._watchdog_task = asyncio.create_task(self._watchdog(), name="engine-watchdog")

    async def _watchdog(self) -> None:
        """Periodic status refresh + ONE bounded restart of a dead managed process."""
        comfy = self.adapter
        assert isinstance(comfy, ComfyUIEngine)
        while True:
            try:
                await asyncio.sleep(10)
                self.last_status = await comfy.get_status(force=True)
                if (
                    not self.last_status.online
                    and comfy._process is not None
                    and comfy._process.poll() is not None
                ):
                    now = time.monotonic()
                    if self._restart_attempts < 1 and now - self._last_restart_ts > 120:
                        self._restart_attempts += 1
                        self._last_restart_ts = now
                        log.warning("Managed ComfyUI died (rc=%s); attempting ONE restart.",
                                    comfy._process.returncode)
                        if comfy.start_process():
                            await comfy.wait_online(self.settings.engine_startup_timeout_s)
                    elif self._restart_attempts >= 1:
                        log.error(
                            "Managed ComfyUI died again after the single allowed restart. "
                            "Not restarting again (no infinite retry loops). "
                            "Check logs/engine_comfyui.log."
                        )
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("Engine watchdog iteration failed")

    async def status(self, *, force: bool = False) -> EngineStatus:
        if force:
            self.last_status = await self.adapter.get_status(force=True)
        return self.last_status

    async def restart_managed_engine(self) -> EngineStatus:
        """User-initiated engine restart (System page action)."""
        comfy = self.adapter
        assert isinstance(comfy, ComfyUIEngine)
        comfy.stop_process()
        await asyncio.sleep(1)
        started = comfy.start_process()
        if not started:
            self.last_status = EngineStatus(
                online=False, base_url=comfy.base_url,
                last_error="Managed ComfyUI installation not found; cannot start.",
            )
            return self.last_status
        self._restart_attempts = 0
        self.last_status = await comfy.wait_online(self.settings.engine_startup_timeout_s)
        return self.last_status

    async def shutdown(self) -> None:
        for task in (self._watchdog_task, self._ws_task):
            if task and not task.done():
                task.cancel()
        await self.adapter.shutdown()
