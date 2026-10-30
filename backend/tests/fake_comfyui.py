"""Fake ComfyUI server for integration tests.

IMPORTANT — test fixture only. This is NOT part of the application and is
never used in production code paths. It implements the subset of the real
ComfyUI v0.43 HTTP/WS API that NOVA MOTION consumes:

  GET  /system_stats, /object_info, /queue, /history/{id}
  POST /prompt, /interrupt, /free, /queue(delete)
  WS   /ws?clientId=...

It "executes" a prompt by writing a deterministic PNG gradient sequence
(pure-python PNG writer, no Pillow dependency) to the same output layout
SaveImage uses, emitting real progress events over the websocket, and then
recording history — so the whole NOVA MOTION pipeline (submit -> monitor ->
collect frames -> ffmpeg assembly -> ffprobe validation -> DB -> HTTP Range
serving) is exercised for real. Diffusion inference itself is obviously NOT
performed; tests using this fixture validate plumbing, never AI quality.

Supports fault injection:
  fail_with="oom"       -> execution_error with CUDA OOM message
  fail_with="crash"     -> generic execution_error
  interruptible=True    -> POST /interrupt stops the running prompt
"""
from __future__ import annotations

import asyncio
import json
import struct
import threading
import time
import uuid
import zlib
from pathlib import Path
from typing import Any

from aiohttp import web


def write_png(path: Path, width: int, height: int, frame_index: int) -> None:
    """Minimal RGB PNG writer producing a moving gradient (real frame motion
    so interpolation/encoding pipelines behave meaningfully)."""
    raw = bytearray()
    shift = (frame_index * 7) % 256
    for y in range(height):
        raw.append(0)  # filter: none
        for x in range(width):
            raw.append((x * 3 + shift) % 256)
            raw.append((y * 3 + shift // 2) % 256)
            raw.append((x + y + shift) % 256)
    compressed = zlib.compress(bytes(raw), 6)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


NODE_CLASSES = [
    "CheckpointLoaderSimple", "CLIPTextEncode", "EmptyLatentImage", "KSampler",
    "VAEDecodeTiled", "SaveImage",
    "ADE_LoadAnimateDiffModel", "ADE_ApplyAnimateDiffModelSimple",
    "ADE_StandardUniformContextOptions", "ADE_AnimateDiffSamplingSettings",
    "ADE_UseEvolvedSampling",
]


class FakeComfyUI:
    def __init__(self, output_root: Path, *, step_delay: float = 0.01,
                 fail_with: str | None = None, fail_first_only: bool = False,
                 frame_width: int = 64, frame_height: int = 64) -> None:
        self.output_root = Path(output_root)
        self.step_delay = step_delay
        self.fail_with = fail_with
        self.fail_first_only = fail_first_only
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.prompts_received: list[dict[str, Any]] = []
        self.history: dict[str, dict[str, Any]] = {}
        self.queue_running: list[str] = []
        self.queue_pending: list[str] = []
        self.interrupt_requested = False
        self.free_calls = 0
        self._sockets: set[web.WebSocketResponse] = set()
        self._runner: web.AppRunner | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self.port: int | None = None
        self.version = "0.43.0-fake"

    # ------------------------------------------------------------- lifecycle
    def start(self) -> int:
        ready = threading.Event()

        def _run() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            app = web.Application()
            app.router.add_get("/system_stats", self._system_stats)
            app.router.add_get("/object_info", self._object_info)
            app.router.add_get("/queue", self._queue)
            app.router.add_post("/queue", self._queue_post)
            app.router.add_post("/prompt", self._prompt)
            app.router.add_get("/history/{prompt_id}", self._history_get)
            app.router.add_post("/interrupt", self._interrupt)
            app.router.add_post("/free", self._free)
            app.router.add_get("/ws", self._ws)
            self._runner = web.AppRunner(app)
            self._loop.run_until_complete(self._runner.setup())
            site = web.TCPSite(self._runner, "127.0.0.1", 0)
            self._loop.run_until_complete(site.start())
            self.port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
            ready.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=_run, daemon=True, name="fake-comfyui")
        self._thread.start()
        if not ready.wait(timeout=15):
            raise RuntimeError("fake ComfyUI failed to start")
        return self.port or 0

    def stop(self) -> None:
        if self._loop and self._runner:
            asyncio.run_coroutine_threadsafe(self._runner.cleanup(), self._loop).result(timeout=10)
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=10)

    # --------------------------------------------------------------- handlers
    async def _system_stats(self, request: web.Request) -> web.Response:
        return web.json_response({
            "system": {
                "os": "posix", "python_version": "3.13.0 (fake)",
                "comfyui_version": self.version, "argv": ["main.py"],
            },
            "devices": [{
                "name": "NVIDIA GeForce RTX 2050 Laptop GPU (FAKE-TEST)",
                "type": "cuda", "index": 0,
                "vram_total": 4096 * 1024 * 1024,
                "vram_free": 3200 * 1024 * 1024,
                "torch_version": "2.14.1+cu130",
            }],
        })

    async def _object_info(self, request: web.Request) -> web.Response:
        return web.json_response({cls: {"input": {"required": {}}, "output": []}
                                  for cls in NODE_CLASSES})

    async def _queue(self, request: web.Request) -> web.Response:
        return web.json_response({
            "queue_running": [[i, p, {}] for i, p in enumerate(self.queue_running)],
            "queue_pending": [[i, p, {}] for i, p in enumerate(self.queue_pending)],
        })

    async def _queue_post(self, request: web.Request) -> web.Response:
        payload = await request.json()
        for number in payload.get("delete", []):
            if str(number) in self.queue_pending:
                self.queue_pending.remove(str(number))
        return web.json_response({})

    async def _interrupt(self, request: web.Request) -> web.Response:
        self.interrupt_requested = True
        return web.json_response({})

    async def _free(self, request: web.Request) -> web.Response:
        self.free_calls += 1
        return web.json_response({})

    async def _history_get(self, request: web.Request) -> web.Response:
        pid = request.match_info["prompt_id"]
        return web.json_response({pid: self.history[pid]} if pid in self.history else {})

    async def _ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._sockets.add(ws)
        await ws.send_str(json.dumps(
            {"type": "status", "data": {"status": {"exec_info": {"queue_remaining": 0}}}}
        ))
        try:
            async for _ in ws:
                pass
        finally:
            self._sockets.discard(ws)
        return ws

    async def _broadcast(self, message: dict[str, Any]) -> None:
        text = json.dumps(message)
        for ws in list(self._sockets):
            try:
                await ws.send_str(text)
            except Exception:  # noqa: BLE001
                self._sockets.discard(ws)

    async def _prompt(self, request: web.Request) -> web.Response:
        payload = await request.json()
        workflow = payload.get("prompt")
        if not isinstance(workflow, dict) or not workflow:
            return web.json_response({"error": "empty prompt", "node_errors": {}}, status=400)
        # minimal validation like the real server: unknown class -> 400
        for node in workflow.values():
            if node.get("class_type") not in NODE_CLASSES:
                return web.json_response(
                    {"error": {"type": "unknown_node",
                               "message": f"unknown class {node.get('class_type')}"},
                     "node_errors": {}}, status=400)
        prompt_id = str(uuid.uuid4())
        self.prompts_received.append({"prompt_id": prompt_id, "workflow": workflow})
        number = len(self.prompts_received)
        self.queue_running.append(prompt_id)
        await self._broadcast({"type": "execution_start", "data": {"prompt_id": prompt_id}})
        asyncio.get_running_loop().create_task(self._execute(prompt_id, workflow))
        return web.json_response({"prompt_id": prompt_id, "number": number,
                                  "node_errors": {}})

    # -------------------------------------------------------------- execution
    async def _execute(self, prompt_id: str, workflow: dict[str, Any]) -> None:
        self.interrupt_requested = False
        try:
            save_node_id, prefix = None, "ComfyUI"
            width, height, frames, steps = self.frame_width, self.frame_height, 16, 8
            for nid, node in workflow.items():
                cls = node.get("class_type")
                inputs = node.get("inputs", {})
                if cls == "SaveImage":
                    save_node_id = nid
                    prefix = str(inputs.get("filename_prefix", prefix))
                elif cls == "EmptyLatentImage":
                    width = int(inputs.get("width", width))
                    height = int(inputs.get("height", height))
                    frames = int(inputs.get("batch_size", frames))
                elif cls == "KSampler":
                    steps = int(inputs.get("steps", steps))

            # fault injection
            attempt = len(self.prompts_received)
            should_fail = self.fail_with and not (self.fail_first_only and attempt > 1)
            fail_at_step = max(1, steps // 2) if should_fail else None

            await self._broadcast({"type": "executing",
                                   "data": {"node": "10", "prompt_id": prompt_id}})
            for step in range(1, steps + 1):
                if self.interrupt_requested:
                    await self._broadcast({"type": "execution_interrupted",
                                           "data": {"prompt_id": prompt_id}})
                    self.history[prompt_id] = {
                        "outputs": {},
                        "status": {"status_str": "error", "completed": False,
                                   "messages": [["execution_interrupted",
                                                 {"prompt_id": prompt_id}]]},
                    }
                    return
                if fail_at_step == step:
                    msg = ("CUDA out of memory. Tried to allocate 2.00 GiB"
                           if self.fail_with == "oom"
                           else "RuntimeError: something exploded inside the model")
                    await self._broadcast({"type": "execution_error", "data": {
                        "prompt_id": prompt_id, "node_id": "10",
                        "exception_type": "RuntimeError", "exception_message": msg,
                    }})
                    self.history[prompt_id] = {
                        "outputs": {},
                        "status": {"status_str": "error", "completed": False,
                                   "messages": [["execution_error", {
                                       "prompt_id": prompt_id, "node_id": "10",
                                       "exception_message": msg}]]},
                    }
                    return
                await self._broadcast({"type": "progress", "data": {
                    "value": step, "max": steps, "prompt_id": prompt_id,
                    "node": "10", "node_type": "KSampler"}})
                await asyncio.sleep(self.step_delay)

            # write frames exactly like SaveImage does
            subfolder = str(Path(prefix).parent) if str(Path(prefix).parent) != "." else ""
            stem = Path(prefix).name
            images_meta = []
            out_base = self.output_root / subfolder if subfolder else self.output_root
            await self._broadcast({"type": "executing",
                                   "data": {"node": save_node_id, "prompt_id": prompt_id}})
            for i in range(1, frames + 1):
                fname = f"{stem}_{i:05d}_.png"
                await asyncio.get_running_loop().run_in_executor(
                    None, write_png, out_base / fname, width, height, i)
                images_meta.append({"filename": fname, "subfolder": subfolder,
                                    "type": "output"})
            self.history[prompt_id] = {
                "outputs": {save_node_id or "12": {"images": images_meta}},
                "status": {"status_str": "success", "completed": True,
                           "messages": [["execution_success", {"prompt_id": prompt_id}]]},
            }
            await self._broadcast({"type": "executed", "data": {
                "node": save_node_id, "prompt_id": prompt_id,
                "output": {"images": images_meta}}})
            await self._broadcast({"type": "execution_success",
                                   "data": {"prompt_id": prompt_id}})
        except Exception as exc:  # noqa: BLE001
            self.history[prompt_id] = {
                "outputs": {},
                "status": {"status_str": "error", "completed": False,
                           "messages": [["execution_error", {
                               "prompt_id": prompt_id,
                               "exception_message": f"fake engine crash: {exc}"}]]},
            }
        finally:
            if prompt_id in self.queue_running:
                self.queue_running.remove(prompt_id)
            await self._broadcast({"type": "executing",
                                   "data": {"node": None, "prompt_id": prompt_id}})
