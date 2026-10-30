"""ComfyUI engine adapter — talks to the documented ComfyUI HTTP + WS API.

Verified against ComfyUI v0.43.0 server.py:
  GET  /system_stats, GET /object_info, GET /history/{prompt_id}, GET /queue
  POST /prompt {"prompt": <api-format graph>, "client_id": <uuid>}
  POST /interrupt, POST /queue {"delete": [number]}, POST /free
  WS   /ws?clientId=<uuid>  -> status / execution_start / executing /
                               progress / executed / execution_error /
                               execution_interrupted / execution_success

Also manages the *local process* of a managed ComfyUI installation
(engine/ComfyUI + engine/.venv) when autostart is enabled. Only processes
started by this adapter are ever terminated.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp

from ..config import Settings
from ..core.errors import ErrorCode, NovaError, classify_engine_error
from ..logging_config import get_logger
from .base import EngineAdapter, EngineJobResult, EngineStatus, SubmitResult

log = get_logger(__name__)

STATUS_CACHE_TTL_S = 5.0


class ComfyUIEngine(EngineAdapter):
    name = "comfyui"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client_id = uuid.uuid4().hex
        self.base_url = settings.engine_base_url
        self._session: aiohttp.ClientSession | None = None
        self._status_cache: tuple[float, EngineStatus] | None = None
        self._object_info_cache: tuple[float, dict[str, Any]] | None = None
        self._process: subprocess.Popen | None = None
        self._ws_task: asyncio.Task | None = None
        self._ws_listeners: set[asyncio.Queue] = set()
        self._ws_connected = False
        self._last_ws_error: str | None = None

    # ------------------------------------------------------------------ http
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30, connect=5)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _get_json(self, path: str) -> Any:
        session = await self._get_session()
        async with session.get(f"{self.base_url}{path}") as resp:
            if resp.status != 200:
                raise NovaError(
                    ErrorCode.ENGINE_UNREACHABLE,
                    f"ComfyUI returned HTTP {resp.status} for {path}.",
                    retryable=True, http_status=502,
                )
            return await resp.json(content_type=None)

    async def _post_json(self, path: str, payload: dict | None = None) -> Any:
        session = await self._get_session()
        async with session.post(f"{self.base_url}{path}", json=payload or {}) as resp:
            body = await resp.text()
            if resp.status >= 400:
                raise NovaError(
                    ErrorCode.ENGINE_EXECUTION_ERROR,
                    f"ComfyUI POST {path} failed (HTTP {resp.status}).",
                    detail=body[:2000], retryable=False, http_status=502,
                )
            try:
                return json.loads(body) if body else {}
            except ValueError:
                return {}

    # -------------------------------------------------------------- status
    async def get_status(self, *, force: bool = False) -> EngineStatus:
        now = time.monotonic()
        if not force and self._status_cache and now - self._status_cache[0] < STATUS_CACHE_TTL_S:
            return self._status_cache[1]
        status = EngineStatus(base_url=self.base_url,
                              managed_process_running=self.is_process_alive(),
                              checked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        try:
            data = await self._get_json("/system_stats")
            system = data.get("system", {}) if isinstance(data, dict) else {}
            status.online = True
            status.comfyui_version = str(system.get("comfyui_version") or "") or None
            status.python_version = str(system.get("python_version") or "") or None
            devices = data.get("devices", []) if isinstance(data, dict) else []
            status.devices = [d for d in devices if isinstance(d, dict)]
            for d in status.devices:
                if d.get("torch_version"):
                    status.torch_version = str(d["torch_version"])
                    break
            # cuda availability: engine reports devices of type cuda
            if any(d.get("type") == "cuda" for d in status.devices):
                for d in status.devices:
                    d["cuda_available"] = True
        except NovaError as exc:
            status.last_error = exc.summary
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            status.last_error = f"Engine unreachable: {type(exc).__name__}"
        except Exception as exc:  # noqa: BLE001
            status.last_error = f"Unexpected status error: {type(exc).__name__}"
            log.exception("Engine status probe failed")
        try:
            queue = await self._get_json("/queue")
            if isinstance(queue, dict):
                running = queue.get("queue_running") or []
                pending = queue.get("queue_pending") or []
                status.queue_remaining = len(running) + len(pending)
        except Exception:  # noqa: BLE001
            pass
        self._status_cache = (time.monotonic(), status)
        return status

    async def fetch_object_info(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._object_info_cache and now - self._object_info_cache[0] < 60.0:
            return self._object_info_cache[1]
        data = await self._get_json("/object_info")
        info = data if isinstance(data, dict) else {}
        self._object_info_cache = (now, info)
        return info

    # ---------------------------------------------------------------- jobs
    async def submit(self, workflow: dict[str, Any], client_id: str | None = None) -> SubmitResult:
        session = await self._get_session()
        payload = {"prompt": workflow, "client_id": client_id or self.client_id}
        async with session.post(f"{self.base_url}/prompt", json=payload) as resp:
            body = await resp.text()
            if resp.status == 400:
                detail = body[:4000]
                node_errors = ""
                try:
                    parsed = json.loads(body)
                    node_errors = json.dumps(parsed.get("node_errors", {}))[:800]
                except ValueError:
                    pass
                raise NovaError(
                    ErrorCode.WORKFLOW_INVALID,
                    "ComfyUI rejected the workflow before execution.",
                    detail=f"{detail} node_errors={node_errors}",
                    recovery="Run Repair-Environment and validate the model; the engine may be missing a node or model file.",
                    http_status=422,
                )
            if resp.status >= 400:
                raise NovaError(
                    ErrorCode.ENGINE_EXECUTION_ERROR,
                    f"ComfyUI queue submission failed (HTTP {resp.status}).",
                    detail=body[:2000], retryable=True, http_status=502,
                )
            try:
                data = json.loads(body)
            except ValueError as exc:
                raise NovaError(ErrorCode.ENGINE_EXECUTION_ERROR,
                                "ComfyUI returned a malformed queue response.",
                                detail=body[:500], http_status=502) from exc
            prompt_id = data.get("prompt_id")
            if not prompt_id:
                raise NovaError(ErrorCode.ENGINE_EXECUTION_ERROR,
                                "ComfyUI response contained no prompt_id.",
                                detail=body[:500], http_status=502)
            return SubmitResult(prompt_id=str(prompt_id), queue_number=data.get("number"))

    async def fetch_result(self, prompt_id: str) -> EngineJobResult | None:
        try:
            data = await self._get_json(f"/history/{prompt_id}")
        except NovaError:
            return None
        entry = data.get(prompt_id) if isinstance(data, dict) else None
        if not isinstance(entry, dict):
            return None
        status_block = entry.get("status") or {}
        status_str = str(status_block.get("status_str") or "unknown")
        completed = bool(status_block.get("completed"))
        outputs = entry.get("outputs") or {}
        error_message = None
        error_node = None
        for msg in status_block.get("messages", []):
            if isinstance(msg, list) and msg and msg[0] == "execution_error":
                payload = msg[1] if len(msg) > 1 and isinstance(msg[1], dict) else {}
                error_message = str(payload.get("exception_message") or "")
                error_node = str(payload.get("node_id") or "") or None
        if status_str == "success" and completed:
            return EngineJobResult(prompt_id, "success", outputs=outputs)
        if status_str == "error":
            return EngineJobResult(prompt_id, "error",
                                   error_message=error_message or "unknown engine error",
                                   error_node_id=error_node, outputs=outputs)
        return EngineJobResult(prompt_id, status_str or "unknown", outputs=outputs)

    async def interrupt(self) -> bool:
        try:
            await self._post_json("/interrupt")
            return True
        except NovaError:
            return False

    async def delete_queued(self, queue_number: int) -> bool:
        try:
            await self._post_json("/queue", {"delete": [queue_number]})
            return True
        except NovaError:
            return False

    async def free_memory(self) -> bool:
        try:
            await self._post_json("/free", {"unload_models": True, "free_memory": True})
            return True
        except NovaError:
            return False

    # ------------------------------------------------------------ websocket
    def add_ws_listener(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._ws_listeners.add(q)
        return q

    def remove_ws_listener(self, q: asyncio.Queue) -> None:
        self._ws_listeners.discard(q)

    @property
    def ws_connected(self) -> bool:
        return self._ws_connected

    async def run_ws_loop(self) -> None:
        """Persistent WS connection with reconnect + resync. Runs for app lifetime."""
        url = self.base_url.replace("http://", "ws://") + f"/ws?clientId={self.client_id}"
        backoff = 2.0
        while True:
            try:
                session = await self._get_session()
                async with session.ws_connect(url, heartbeat=30, autoping=True) as ws:
                    self._ws_connected = True
                    self._last_ws_error = None
                    backoff = 2.0
                    log.info("ComfyUI websocket connected (%s)", url)
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            self._dispatch_ws(msg.data)
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
            except asyncio.CancelledError:
                self._ws_connected = False
                raise
            except (aiohttp.ClientError, OSError, asyncio.TimeoutError) as exc:
                self._last_ws_error = f"{type(exc).__name__}: {exc}"
            except Exception as exc:  # noqa: BLE001
                self._last_ws_error = f"{type(exc).__name__}"
                log.exception("Unexpected WS loop error")
            self._ws_connected = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.7, 30.0)

    def _dispatch_ws(self, raw: str) -> None:
        try:
            event = json.loads(raw)
        except ValueError:
            return
        if not isinstance(event, dict) or "type" not in event:
            return
        for q in list(self._ws_listeners):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("WS listener queue full; dropping event %s", event.get("type"))

    # ------------------------------------------------- managed subprocess
    def is_process_alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def can_manage_process(self) -> bool:
        return (self.settings.comfyui_root / "main.py").is_file() and \
            self.settings.comfyui_venv_python.is_file()

    def start_process(self) -> bool:
        """Start the managed ComfyUI process. Never kills anything else."""
        if self.is_process_alive():
            return True
        if not self.can_manage_process():
            log.warning("Managed ComfyUI installation not found at %s — cannot autostart.",
                        self.settings.comfyui_root)
            return False
        args = [
            str(self.settings.comfyui_venv_python), "-s",
            str(self.settings.comfyui_root / "main.py"),
            "--listen", self.settings.engine_host,
            "--port", str(self.settings.engine_port),
            *self.settings.engine_extra_args,
        ]
        log_path = self.settings.logs_dir / "engine_comfyui.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fh = open(log_path, "ab", buffering=0)
            kwargs: dict[str, Any] = {"cwd": str(self.settings.comfyui_root),
                                      "stdout": fh, "stderr": fh, "stdin": subprocess.DEVNULL}
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            self._process = subprocess.Popen(args, **kwargs)
            log.info("Started managed ComfyUI (pid=%s): %s", self._process.pid, " ".join(args))
            return True
        except OSError as exc:
            log.error("Failed to start ComfyUI process: %s", exc)
            return False

    def stop_process(self, timeout: float = 15.0) -> bool:
        """Terminate ONLY the process this adapter started."""
        proc = self._process
        if proc is None:
            return True
        if proc.poll() is not None:
            self._process = None
            return True
        log.info("Stopping managed ComfyUI (pid=%s)", proc.pid)
        try:
            if os.name == "nt":
                proc.terminate()
            else:
                proc.terminate()
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                log.warning("ComfyUI did not exit gracefully; killing pid=%s", proc.pid)
                proc.kill()
                proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            log.exception("Error stopping ComfyUI process")
            return False
        self._process = None
        return True

    async def wait_online(self, timeout_s: float) -> EngineStatus:
        deadline = time.monotonic() + timeout_s
        last: EngineStatus = EngineStatus(base_url=self.base_url)
        while time.monotonic() < deadline:
            last = await self.get_status(force=True)
            if last.online:
                return last
            if self._process is not None and self._process.poll() is not None:
                last.last_error = (
                    f"ComfyUI process exited during startup with code {self._process.returncode}. "
                    "See logs/engine_comfyui.log."
                )
                return last
            await asyncio.sleep(2.0)
        return last

    # ------------------------------------------------------------ lifecycle
    async def shutdown(self) -> None:
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
        if self._session and not self._session.closed:
            await self._session.close()
        self.stop_process()

    def classify_error(self, raw_message: str) -> tuple[str, str, str | None]:
        return classify_engine_error(raw_message)
