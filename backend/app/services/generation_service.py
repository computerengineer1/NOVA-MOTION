"""Generation orchestration.

Pipeline (state machine stages map 1:1 to real work):
  PREFLIGHT      resource guard + live workflow validation
  INITIALIZING   engine warmup check, free stale engine memory
  GENERATING     submit segment(s) to ComfyUI, monitor real execution
                 (WS progress events + history polling fallback)
  ASSEMBLING     collect PNG frames, encode segments, concat (multi-shot)
  INTERPOLATING  only when interpolation selected (real minterpolate pass)
  ENCODING       final H.264/yuv420p encode with exact fps/frame count
  VALIDATING     ffprobe acceptance + thumbnail + DB completion

Honesty rules:
  * progress comes only from real engine events,
  * ETA only after two measured step observations (see ProgressManager),
  * failures classify into safe summaries; full detail goes to the log,
  * exactly ONE automatic lower-memory retry after GPU OOM (if enabled),
    never a loop, and the downgrade is recorded in the job's metrics and
    surfaced in the UI.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

from ..config import Settings
from ..core.errors import ErrorCode, NovaError, classify_engine_error
from ..core.model_registry import ModelProfile, ModelRegistry
from ..core.progress_manager import ProgressManager
from ..core.resource_guard import run_preflight
from ..core.workflow_builder import WORKFLOW_ID_ANIMATEDIFF_T2V, build_animatediff_t2v
from ..core.workflow_validation import validate_live, validate_static
from ..database.models import JobStatus, GenerationRecord, can_transition
from ..database.repositories import GenerationRepository, ModelRepository, SettingsRepository, utcnow_iso
from ..engines.engine_manager import EngineManager
from ..logging_config import get_logger
from ..schemas.generation import GenerationRequest
from .ffmpeg import FFmpegService
from .thumbnail_service import ThumbnailService
from .video_assembly import VideoAssemblyService
from .video_validation import validate_output

log = get_logger(__name__)

ROUTE_LABELS = {
    "native_long": (
        "Native long generation — one continuous 8 s diffusion run using a "
        "16-frame sliding context window (AnimateDiff-Evolved 'Standard Uniform' "
        "context, overlap 4, pyramid fusion). Composition may drift over the clip; "
        "this is a model property, honestly disclosed."
    ),
    "multi_shot": (
        "Multi-shot composition — {segments} independently generated ~2 s shots "
        "concatenated into one 8 s export. The shots are NOT one continuous camera "
        "take and will differ in composition."
    ),
}

# Lower-memory fallback ladder per aspect (all multiples of 8, SD1.5-safe)
_FALLBACK_LADDER: dict[str, list[tuple[int, int]]] = {
    "16:9": [(768, 432), (640, 360), (512, 288)],
    "1:1": [(512, 512), (448, 448), (384, 384)],
    "9:16": [(360, 640), (288, 512)],
}


def pick_resolution(profile: ModelProfile, aspect: str,
                    resolution_id: str | None) -> tuple[int, int, str]:
    caps = profile.capabilities or {}
    resolutions = [r for r in caps.get("resolutions", []) if r.get("aspect") == aspect]
    if resolution_id:
        match = next((r for r in resolutions if r.get("id") == resolution_id), None)
        if match is None:
            raise NovaError(
                ErrorCode.VALIDATION_ERROR,
                f"Resolution '{resolution_id}' is not supported for aspect {aspect} by this model.",
                http_status=422,
            )
        return int(match["width"]), int(match["height"]), str(match["id"])
    default = next((r for r in resolutions if r.get("default")), None) or \
        next((r for r in resolutions if not r.get("high_vram_risk")), None)
    if default is None:
        raise NovaError(ErrorCode.VALIDATION_ERROR,
                        f"This model has no resolution preset for aspect {aspect}.",
                        http_status=422)
    return int(default["width"]), int(default["height"]), str(default["id"])


class GenerationService:
    def __init__(
        self,
        settings: Settings,
        engine_manager: EngineManager,
        registry: ModelRegistry,
        generations: GenerationRepository,
        models_repo: ModelRepository,
        settings_repo: SettingsRepository,
        ffmpeg: FFmpegService,
        assembly: VideoAssemblyService,
        thumbnails: ThumbnailService,
        progress: ProgressManager,
    ) -> None:
        self.settings = settings
        self.engines = engine_manager
        self.registry = registry
        self.generations = generations
        self.models_repo = models_repo
        self.settings_repo = settings_repo
        self.ffmpeg = ffmpeg
        self.assembly = assembly
        self.thumbnails = thumbnails
        self.progress = progress
        self._cancel_events: dict[str, asyncio.Event] = {}

    # --------------------------------------------------------------- public
    def register_cancel_event(self, job_id: str) -> asyncio.Event:
        ev = self._cancel_events.setdefault(job_id, asyncio.Event())
        return ev

    def clear_cancel_event(self, job_id: str) -> None:
        self._cancel_events.pop(job_id, None)

    def compute_effective(self, req: GenerationRequest, profile: ModelProfile) -> dict[str, Any]:
        """Server-side resolution of everything the UI only requests loosely."""
        caps = profile.capabilities or {}
        source_fps = int(caps.get("source_fps", 8))
        max_frames = int(caps.get("max_total_frames", 128))
        width, height, res_id = pick_resolution(profile, req.aspect_ratio, req.resolution_id)
        total_frames = int(round(req.duration_seconds * source_fps))
        if total_frames > max_frames:
            raise NovaError(ErrorCode.VALIDATION_ERROR,
                            f"{req.duration_seconds}s needs {total_frames} frames; the model supports at most {max_frames}.",
                            http_status=422)
        modes = caps.get("modes", [])
        mode = req.generation_mode
        if mode == "auto":
            mode = "native_long" if ("native_long" in modes and total_frames <= max_frames) else "multi_shot"
        if mode not in modes:
            raise NovaError(ErrorCode.VALIDATION_ERROR,
                            f"Generation mode '{mode}' is not supported by this model.",
                            http_status=422)
        context_length = int(caps.get("context_length", 16))
        if mode == "multi_shot":
            segment_seconds = 2.0
            segments = int(round(req.duration_seconds / segment_seconds))
            frames_per_segment = int(round(segment_seconds * source_fps))
        else:
            segments = 1
            frames_per_segment = total_frames
        # estimates (labeled as estimates in the UI; derived from a measured
        # heuristic table for RTX 2050 class hardware, NOT a promise)
        windows_per_segment = 1 if frames_per_segment <= context_length else (
            -(-frames_per_segment // (context_length - 4))
        )
        per_window_s = (width * height) / (640 * 360) * 7.0  # ~7s/window at 640x360, 16 frames
        est_low_min = round(req.steps * windows_per_segment * segments * per_window_s * 0.6 / 60, 1)
        est_high_min = round(req.steps * windows_per_segment * segments * per_window_s * 1.5 / 60, 1)
        bitrate_mb_s = {8: 0.15, 16: 0.25, 24: 0.35}.get(req.export_fps, 0.15)
        pixel_factor = (width * height) / (640 * 360)
        est_size_mb = round(bitrate_mb_s * pixel_factor * req.duration_seconds *
                            (4 if req.upscale_export else 1) * 0.6, 2)
        upscale_factor = 2 if req.upscale_export else 1
        route_label = ROUTE_LABELS[mode].format(segments=segments)
        if req.interpolation != "none":
            route_label += (
                f" Output uses {req.interpolation} frame interpolation to "
                f"{req.export_fps} fps — conventional/motion-estimated in-between frames, "
                "not newly generated content."
            )
        if req.upscale_export:
            route_label += (
                f" Export upscaled ×{upscale_factor} with ffmpeg lanczos — a conventional "
                "resize, not AI super-resolution; no new detail is created."
            )
        return {
            "width": width, "height": height, "resolution_id": res_id,
            "source_fps": source_fps, "total_frames": total_frames,
            "segments": segments, "frames_per_segment": frames_per_segment,
            "context_length": context_length,
            "route": mode, "route_label": route_label,
            "export_fps": req.export_fps,
            "interpolation": req.interpolation,
            "upscale_export": req.upscale_export,
            "upscale_factor": upscale_factor,
            "final_width": width * upscale_factor,
            "final_height": height * upscale_factor,
            "estimated_output_size_mb": est_size_mb,
            "estimated_minutes_low": est_low_min,
            "estimated_minutes_high": est_high_min,
        }

    def create_record(self, req: GenerationRequest, effective: dict[str, Any],
                      seed: int) -> GenerationRecord:
        job_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
        return GenerationRecord(
            id=job_id,
            status=JobStatus.QUEUED,
            original_prompt=req.prompt,
            negative_prompt=req.negative_prompt,
            seed=seed,
            model_id=req.model_id,
            workflow_id=WORKFLOW_ID_ANIMATEDIFF_T2V,
            generation_mode=effective["route"],
            configuration={
                "request": req.model_dump(),
                "effective": effective,
            },
        )

    async def preflight(self, record: GenerationRecord) -> dict[str, Any]:
        profile = self.registry.get_installable(record.model_id)
        eff = record.configuration["effective"]
        engine_status = await self.engines.status()
        installed = self.registry.is_installed(profile)
        guard = run_preflight(
            self.settings,
            engine_online=engine_status.online,
            model_files_present=installed,
            workflow_ok=True,   # statically validated at build time; live check follows
            job_running=False,  # job manager enforces sequencing separately
        )
        if engine_status.online:
            try:
                await validate_live(self.engines.adapter, record.workflow_id)
            except NovaError as exc:
                from ..core.resource_guard import CheckResult
                guard.add(CheckResult("workflow_live", False, True, exc.summary))
        return guard.to_dict()

    # -------------------------------------------------------------- execute
    async def execute(self, record: GenerationRecord) -> None:
        """Run the full pipeline for one job. Called by the job worker."""
        job_id = record.id
        cancel = self.register_cancel_event(job_id)
        started = time.monotonic()
        tmp_root = self.settings.data_dir / "tmp" / job_id
        tmp_root.mkdir(parents=True, exist_ok=True)
        metrics: dict[str, Any] = {"engine_seconds": 0.0, "post_seconds": 0.0,
                                   "oom_downgrade_applied": False,
                                   "peak_backend_rss_mb": None,
                                   "peak_engine_rss_mb": None}
        try:
            profile = self.registry.get_installable(record.model_id)
            if not self.registry.is_installed(profile):
                raise NovaError(
                    ErrorCode.MODEL_FILE_MISSING,
                    f"Model '{profile.name}' is not fully installed.",
                    recovery="Open the Models page and install/validate this model first.",
                    http_status=409,
                )
            self._set_status(record, JobStatus.PREFLIGHT, "Running pre-flight checks")
            pre = await self.preflight(record)
            if not pre["ok"]:
                raise NovaError(
                    ErrorCode.INSUFFICIENT_RAM if any("RAM" in b for b in pre["blockers"])
                    else ErrorCode.ENGINE_UNREACHABLE,
                    "Pre-flight checks blocked generation.",
                    detail="; ".join(pre["blockers"]),
                    recovery="; ".join(pre["blockers"]),
                    http_status=409,
                )
            if pre["warnings"]:
                self.progress.report_stage(job_id, JobStatus.PREFLIGHT,
                                           "Warnings: " + " | ".join(pre["warnings"][:3]), 0.02)
            self._check_cancel(cancel)

            # INITIALIZING — engine present, memory freed before load
            self._set_status(record, JobStatus.INITIALIZING, "Preparing engine")
            engine_status = await self.engines.status(force=True)
            if not engine_status.online:
                raise NovaError(ErrorCode.ENGINE_UNREACHABLE,
                                "The inference engine went offline during initialization.",
                                retryable=True, http_status=503)
            await self.engines.adapter.free_memory()

            eff = dict(record.configuration["effective"])
            gen_started = time.monotonic()
            segment_files = await self._generate_segments(
                record, profile, eff, tmp_root, cancel, metrics
            )
            metrics["engine_seconds"] = round(time.monotonic() - gen_started, 1)
            self._check_cancel(cancel)

            # ASSEMBLING
            post_started = time.monotonic()
            self._set_status(record, JobStatus.ASSEMBLING,
                             "Assembling frames into video", 0.90)
            concat_path = tmp_root / "concat.mp4"
            await self.assembly.concat_segments(segment_files, concat_path)

            # INTERPOLATING (real stage only when selected)
            current = concat_path
            if eff["interpolation"] != "none" and eff["export_fps"] > eff["source_fps"]:
                self._check_cancel(cancel)
                self._set_status(record, JobStatus.INTERPOLATING,
                                 f"Interpolating frames {eff['source_fps']}→{eff['export_fps']} fps "
                                 f"(ffmpeg minterpolate — motion-estimated, not generative)", 0.93)
                interp_path = tmp_root / "interp.mp4"
                await self.assembly.interpolate(
                    current, interp_path,
                    export_fps=eff["export_fps"], source_fps=eff["source_fps"],
                )
                current = interp_path
                record.interpolated = True

            # ENCODING
            self._check_cancel(cancel)
            self._set_status(record, JobStatus.ENCODING,
                             "Encoding final H.264 MP4 (exact 8.000 s target)", 0.96)
            final_path = self.settings.outputs_dir / f"{job_id}.mp4"
            exact_frames = int(round(record.configuration["request"]["duration_seconds"] * eff["export_fps"]))
            await self.assembly.final_encode(
                current, final_path,
                export_fps=eff["export_fps"], exact_frames=exact_frames,
                upscale_factor=eff.get("upscale_factor", 1),
            )
            record.upscaled = bool(eff.get("upscale_export"))

            # VALIDATING
            self._check_cancel(cancel)
            self._set_status(record, JobStatus.VALIDATING,
                             "Validating media with ffprobe", 0.98)
            summary = await validate_output(
                self.ffmpeg, final_path,
                expected_duration_s=record.configuration["request"]["duration_seconds"],
                expected_width=eff["final_width"], expected_height=eff["final_height"],
                expected_fps=float(eff["export_fps"]),
            )
            thumb_path = self.settings.thumbnails_dir / f"{job_id}.jpg"
            thumb_ok = await self.thumbnails.create(final_path, thumb_path, summary.duration_s)

            metrics["post_seconds"] = round(time.monotonic() - post_started, 1)
            metrics["wall_seconds"] = round(time.monotonic() - started, 1)
            metrics["peak_backend_rss_mb"] = self._rss_mb()
            metrics["peak_engine_rss_mb"] = self._engine_rss_mb()
            record.metrics = metrics
            record.output_path = str(final_path)
            record.thumbnail_path = str(thumb_path) if thumb_ok else None
            record.actual_duration_seconds = round(summary.duration_s, 4)
            record.actual_width = summary.width
            record.actual_height = summary.height
            record.actual_fps = round(summary.fps, 4)
            record.output_size_bytes = summary.size_bytes
            record.output_codec = f"{summary.codec}/{summary.pix_fmt}"
            self._set_status(record, JobStatus.COMPLETED,
                             "Completed and validated", 1.0, persist_metrics=metrics)
            log.info("Generation %s completed: %.3fs %dx%d @%.2ffps %.2fMB (wall %.1fs)",
                     job_id, summary.duration_s, summary.width, summary.height,
                     summary.fps, summary.size_bytes / 1e6, metrics["wall_seconds"])
        except asyncio.CancelledError:
            raise
        except NovaError as exc:
            if exc.code == ErrorCode.JOB_CANCELLED:
                self._cancelled(record, metrics, started, exc.summary)
            else:
                self._fail(record, exc.code, exc.summary, exc.recovery,
                           exc.detail, metrics, started)
        except Exception as exc:  # noqa: BLE001 — containment by design
            log.exception("Unhandled failure in generation %s", job_id)
            self._fail(record, ErrorCode.INTERNAL,
                       "An unexpected internal error stopped the generation.",
                       "Your prompt and settings were preserved — retry, and if it repeats, "
                       "export a diagnostic report from Help & Diagnostics.",
                       f"{type(exc).__name__}: {exc}", metrics, started)
        finally:
            # release engine memory + clean temp frames (idempotent)
            try:
                if self.settings.free_engine_memory_after_job:
                    await self.engines.adapter.free_memory()
            except Exception:  # noqa: BLE001
                log.debug("Post-job engine free failed (ignored)", exc_info=True)
            shutil.rmtree(tmp_root, ignore_errors=True)
            self.clear_cancel_event(job_id)
            self.progress.clear_job(job_id)

    # ------------------------------------------------------------ segments
    async def _generate_segments(
        self, record: GenerationRecord, profile: ModelProfile, eff: dict[str, Any],
        tmp_root: Path, cancel: asyncio.Event, metrics: dict[str, Any],
    ) -> list[Path]:
        self._set_status(record, JobStatus.GENERATING, "Submitting to inference engine", 0.05)
        checkpoint = self.registry.checkpoint_name(profile)
        motion = self.registry.motion_model_name(profile)
        if not checkpoint or not motion:
            raise NovaError(ErrorCode.MODEL_FILE_MISSING,
                            "The model profile does not define a checkpoint/motion module pair.",
                            http_status=500)
        segments = eff["segments"]
        frames_per_segment = eff["frames_per_segment"]
        seed_base = int(record.seed or 0)
        req = record.configuration["request"]
        downgrade_applied = False
        width, height = eff["width"], eff["height"]
        context_overlap = 4

        segment_files: list[Path] = []
        for seg_index in range(segments):
            self._check_cancel(cancel)
            seg_seed = (seed_base + seg_index * 1000003) % (2**63)
            prefix = f"nova/{record.id}/seg{seg_index}"
            attempt = 0
            while True:
                attempt += 1
                workflow = build_animatediff_t2v(
                    checkpoint_name=checkpoint, motion_model_name=motion,
                    positive_prompt=req["prompt"], negative_prompt=req["negative_prompt"],
                    width=width, height=height, frames=frames_per_segment,
                    steps=req["steps"], cfg=req["cfg"],
                    sampler_name=req["sampler"], scheduler=req["scheduler"],
                    seed=seg_seed, filename_prefix=prefix,
                    context_length=eff["context_length"], context_overlap=context_overlap,
                )
                validate_static(workflow)
                try:
                    await self._run_engine_prompt(
                        record, workflow, seg_index, segments, tmp_root, cancel
                    )
                    break
                except NovaError as exc:
                    oom = exc.code in (ErrorCode.GPU_OUT_OF_MEMORY, ErrorCode.CPU_OUT_OF_MEMORY)
                    auto_ok = bool(self.settings_repo.get_all().get("oom_auto_downgrade_once", True))
                    if oom and auto_ok and not downgrade_applied and attempt == 1:
                        downgrade_applied = True
                        metrics["oom_downgrade_applied"] = True
                        new_wh = self._next_lower_resolution(eff, width, height)
                        if new_wh:
                            width, height = new_wh
                            eff["width"], eff["height"] = width, height
                        context_overlap = max(2, context_overlap - 2)
                        record.configuration.setdefault("downgrades", []).append(
                            {"reason": exc.code, "width": width, "height": height,
                             "context_overlap": context_overlap}
                        )
                        self.generations.update(
                            record.id, configuration_json=json.dumps(record.configuration)
                        )
                        self.progress.report_stage(
                            record.id, JobStatus.GENERATING,
                            f"GPU/CPU out of memory — automatically retrying ONCE with lower "
                            f"memory settings ({width}x{height}, overlap {context_overlap}). "
                            "No further automatic retries will be attempted.",
                        )
                        await self.engines.adapter.free_memory()
                        continue
                    raise
            frames_dir = self._collect_frames(record.id, seg_index, frames_per_segment)
            seg_path = tmp_root / f"seg{seg_index}.mp4"
            await self.assembly.encode_frames(
                frames_dir, f"seg{seg_index}", seg_path,
                fps=eff["source_fps"], expected_frames=frames_per_segment,
            )
            segment_files.append(seg_path)
            if downgrade_applied:
                eff["final_width"] = width * eff.get("upscale_factor", 1)
                eff["final_height"] = height * eff.get("upscale_factor", 1)
        return segment_files

    @staticmethod
    def _next_lower_resolution(eff: dict[str, Any], width: int, height: int) -> tuple[int, int] | None:
        req = eff  # resolution ladder keyed by aspect of current size
        aspect = "16:9" if width > height else ("9:16" if height > width else "1:1")
        ladder = _FALLBACK_LADDER.get(aspect, [])
        current = (width, height)
        if current in ladder:
            idx = ladder.index(current)
            if idx + 1 < len(ladder):
                return ladder[idx + 1]
            return None
        # unknown size -> first strictly smaller rung
        for wh in ladder:
            if wh[0] * wh[1] < width * height:
                return wh
        return None

    async def _run_engine_prompt(
        self, record: GenerationRecord, workflow: dict[str, Any],
        seg_index: int, segments: int, tmp_root: Path, cancel: asyncio.Event,
    ) -> str:
        """Submit one prompt to ComfyUI and monitor it to a terminal state."""
        engine = self.engines.adapter
        result = await engine.submit(workflow, client_id=engine.client_id)  # type: ignore[attr-defined]
        prompt_id = result.prompt_id
        ids = list(record.engine_job_ids) + [prompt_id]
        record.engine_job_ids = ids
        self.generations.update(record.id, engine_job_ids_json=json.dumps(ids))
        self.progress.report_stage(record.id, JobStatus.GENERATING,
                                   f"Segment {seg_index + 1}/{segments} queued in engine "
                                   f"(prompt {prompt_id[:8]}…)")

        ws_queue = engine.add_ws_listener()  # type: ignore[attr-defined]
        last_heartbeat = time.monotonic()
        poll_due = time.monotonic() + 3.0
        try:
            while True:
                if cancel.is_set():
                    await self._cancel_engine_run(engine, prompt_id, result.queue_number)
                    raise NovaError(ErrorCode.JOB_CANCELLED, "Generation cancelled by user.",
                                    http_status=409)
                if time.monotonic() - last_heartbeat > self.settings.job_heartbeat_timeout_s:
                    raise NovaError(
                        ErrorCode.ENGINE_TIMEOUT,
                        "The engine reported no progress for "
                        f"{self.settings.job_heartbeat_timeout_s // 60} minutes.",
                        recovery="The engine may have crashed (check logs/engine_comfyui.log). "
                                 "Restart the engine from the System page and retry.",
                    )
                try:
                    event = await asyncio.wait_for(ws_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    event = None
                if event is not None:
                    last_heartbeat = time.monotonic()
                    etype = event.get("type")
                    data = event.get("data") or {}
                    if data.get("prompt_id") not in (None, prompt_id):
                        continue
                    if etype == "progress":
                        node_type = str(data.get("node_type") or "")
                        if node_type in ("KSampler", "") or str(data.get("node")) == "10":
                            self.progress.report_steps(
                                record.id, seg_index, segments,
                                int(data.get("value", 0)), int(data.get("max", 1) or 1),
                                node_type,
                            )
                    elif etype == "executing":
                        node = data.get("node")
                        if node is None:
                            pass  # prompt finished; confirmed below via history
                    elif etype == "execution_error":
                        raw = str(data.get("exception_message") or data.get("exception_type") or "engine error")
                        code, summary, recovery = classify_engine_error(raw)
                        log.error("Engine execution error for %s: %s", prompt_id, raw[:1000])
                        raise NovaError(code, summary, detail=raw[:2000], recovery=recovery)
                    elif etype == "execution_interrupted":
                        raise NovaError(ErrorCode.JOB_CANCELLED,
                                        "Generation was interrupted (cancellation confirmed by engine).",
                                        http_status=409)
                if time.monotonic() >= poll_due:
                    poll_due = time.monotonic() + 3.0
                    state = await engine.fetch_result(prompt_id)
                    if state is not None:
                        last_heartbeat = time.monotonic()
                        if state.status == "success":
                            self.progress.report_stage(
                                record.id, JobStatus.GENERATING,
                                f"Segment {seg_index + 1}/{segments} finished by engine.",
                                (seg_index + 1) / segments * 0.88 + 0.05,
                            )
                            return prompt_id
                        if state.status == "error":
                            code, summary, recovery = classify_engine_error(
                                state.error_message or "engine error")
                            raise NovaError(code, summary,
                                            detail=state.error_message, recovery=recovery)
                        if state.status == "interrupted":
                            raise NovaError(ErrorCode.JOB_CANCELLED,
                                            "Generation interrupted (confirmed via engine history).",
                                            http_status=409)
        finally:
            engine.remove_ws_listener(ws_queue)  # type: ignore[attr-defined]

    async def _cancel_engine_run(self, engine: Any, prompt_id: str,
                                 queue_number: int | None) -> None:
        """Interrupt + wait (bounded) for the engine to confirm the stop."""
        if queue_number is not None:
            await engine.delete_queued(queue_number)
        await engine.interrupt()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            state = await engine.fetch_result(prompt_id)
            if state is not None and state.status in ("error", "interrupted", "success"):
                log.info("Engine confirmed terminal state %s after cancellation of %s",
                         state.status, prompt_id)
                return
            await asyncio.sleep(1.0)
        log.warning("Engine did not confirm cancellation of %s within 30s; "
                    "job marked cancelled, engine output discarded.", prompt_id)

    def _collect_frames(self, job_id: str, seg_index: int, expected: int) -> Path:
        """Resolve the engine's on-disk output frames for a segment."""
        out_root = self.settings.comfyui_root / "output" / "nova" / job_id
        if not out_root.is_dir():
            raise NovaError(
                ErrorCode.OUTPUT_INVALID,
                "The engine reported success but its frame output folder is missing.",
                detail=str(out_root),
                recovery="Ensure the engine is the managed local installation "
                         "(engine/ComfyUI). Remote engines are not supported for frame pickup.",
            )
        frames = sorted(out_root.glob(f"seg{seg_index}_*_.png"))
        if len(frames) != expected:
            raise NovaError(
                ErrorCode.OUTPUT_INVALID,
                f"Engine produced {len(frames)} frames for segment {seg_index + 1}, expected {expected}.",
                recovery="A partial run was likely interrupted. Retry the generation.",
            )
        return out_root

    # ------------------------------------------------------------- helpers
    def _check_cancel(self, cancel: asyncio.Event) -> None:
        if cancel.is_set():
            raise NovaError(ErrorCode.JOB_CANCELLED, "Generation cancelled by user.",
                            http_status=409)

    def _set_status(self, record: GenerationRecord, status: JobStatus,
                    detail: str | None = None, progress: float | None = None,
                    persist_metrics: dict | None = None) -> None:
        old = record.status
        if not can_transition(old, status):
            log.warning("Illegal transition %s -> %s for job %s (ignored)", old, status, record.id)
            return
        record.status = status
        if detail is not None:
            record.stage_detail = detail
        if progress is not None:
            record.progress = progress
        fields: dict[str, Any] = {"status": str(status)}
        if detail is not None:
            fields["stage_detail"] = detail
        if progress is not None:
            fields["progress"] = progress
        if status == JobStatus.GENERATING and not record.started_at:
            record.started_at = utcnow_iso()
            fields["started_at"] = record.started_at
        if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            record.completed_at = utcnow_iso()
            fields["completed_at"] = record.completed_at
            fields["output_path"] = record.output_path
            fields["thumbnail_path"] = record.thumbnail_path
            fields["actual_duration_seconds"] = record.actual_duration_seconds
            fields["actual_width"] = record.actual_width
            fields["actual_height"] = record.actual_height
            fields["actual_fps"] = record.actual_fps
            fields["output_size_bytes"] = record.output_size_bytes
            fields["output_codec"] = record.output_codec
            fields["interpolated"] = int(record.interpolated)
            fields["upscaled"] = int(record.upscaled)
        if persist_metrics is not None:
            fields["metrics_json"] = json.dumps(persist_metrics)
            fields["configuration_json"] = json.dumps(record.configuration)
        try:
            self.generations.update(record.id, **fields)
        except Exception:  # noqa: BLE001
            log.exception("DB write failed while persisting status for %s", record.id)
            self.progress.publish({"type": "job_db_warning", "job_id": record.id,
                                   "message": "A database write failed; the job continues "
                                              "but history may be incomplete."})
        self.progress.report_stage(record.id, status, detail, progress)

    def _cancelled(self, record: GenerationRecord, metrics: dict[str, Any],
                   started: float, summary: str) -> None:
        metrics["wall_seconds"] = round(time.monotonic() - started, 1)
        record.metrics = metrics
        record.error_code = ErrorCode.JOB_CANCELLED
        record.safe_error_summary = summary
        try:
            self.generations.update(
                record.id,
                status=JobStatus.CANCELLED,
                stage_detail=None,
                error_code=ErrorCode.JOB_CANCELLED,
                safe_error_summary=summary,
                error_recovery="Your prompt and settings were preserved — you can "
                               "submit the same generation again at any time.",
                metrics_json=json.dumps(metrics),
                completed_at=utcnow_iso(),
            )
        except Exception:  # noqa: BLE001
            log.exception("Could not persist CANCELLED status for %s", record.id)
        record.status = JobStatus.CANCELLED
        log.info("Job %s cancelled (%s)", record.id, summary)
        self.progress.publish({
            "type": "job_cancelled", "job_id": record.id, "status": "CANCELLED",
            "error": {"code": ErrorCode.JOB_CANCELLED, "summary": summary},
        })

    def _fail(self, record: GenerationRecord, code: str, summary: str,
              recovery: str | None, detail: str | None,
              metrics: dict[str, Any], started: float) -> None:
        log_ref = f"logs/nova-backend.log @ {utcnow_iso()} job={record.id}"
        if detail:
            log.error("Job %s failed [%s]: %s | detail: %s", record.id, code, summary, detail[:1500])
        metrics["wall_seconds"] = round(time.monotonic() - started, 1)
        record.metrics = metrics
        record.error_code = code
        record.safe_error_summary = summary
        try:
            self.generations.update(
                record.id,
                status=JobStatus.FAILED,
                stage_detail=None,
                error_code=code,
                safe_error_summary=summary,
                error_recovery=recovery,
                error_detail_log_ref=log_ref,
                metrics_json=json.dumps(metrics),
                configuration_json=json.dumps(record.configuration),
                completed_at=utcnow_iso(),
            )
        except Exception:  # noqa: BLE001
            log.exception("Could not persist FAILED status for %s", record.id)
        record.status = JobStatus.FAILED
        self.progress.publish({
            "type": "job_failed", "job_id": record.id, "status": "FAILED",
            "error": {"code": code, "summary": summary, "recovery": recovery},
        })

    def _rss_mb(self) -> float | None:
        try:
            return round(psutil.Process().memory_info().rss / 1024**2, 1)
        except psutil.Error:
            return None

    def _engine_rss_mb(self) -> float | None:
        try:
            from ..engines.comfyui_engine import ComfyUIEngine
            engine = self.engines.adapter
            if isinstance(engine, ComfyUIEngine) and engine.is_process_alive():
                proc = psutil.Process(engine._process.pid)  # type: ignore[union-attr]
                return round(proc.memory_info().rss / 1024**2, 1)
        except (psutil.Error, AttributeError):
            pass
        return None
