"""Pre-generation resource guard.

Runs immediately before a job starts (and is also exposed as a dry-run
preflight for the UI). Blocks generation when measurements prove it would
fail; warns on pressure. Never fabricates thresholds-passed results: when a
measurement is unavailable, the corresponding check reports `unknown` and
does not block (but is surfaced as a warning).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import psutil

from ..config import Settings
from ..logging_config import get_logger
from .hardware_detection import detect_disks, detect_gpus, detect_memory

log = get_logger(__name__)


@dataclass
class CheckResult:
    name: str
    ok: bool | None          # None = could not measure
    blocking: bool
    message: str
    value: Any = None


@dataclass
class GuardReport:
    level: str = "READY"     # READY | WARNING | BLOCKED
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def warnings(self) -> list[str]:
        return [c.message for c in self.checks if c.ok is False and not c.blocking] + [
            c.message for c in self.checks if c.ok is None
        ]

    @property
    def blockers(self) -> list[str]:
        return [c.message for c in self.checks if c.ok is False and c.blocking]

    def add(self, check: CheckResult) -> None:
        self.checks.append(check)
        if check.ok is False and check.blocking:
            self.level = "BLOCKED"
        elif (check.ok is False or check.ok is None) and self.level != "BLOCKED":
            self.level = "WARNING"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.level != "BLOCKED",
            "level": self.level,
            "checks": [
                {"name": c.name, "ok": c.ok, "blocking": c.blocking,
                 "message": c.message, "value": c.value}
                for c in self.checks
            ],
            "warnings": self.warnings,
            "blockers": self.blockers,
        }


def run_preflight(settings: Settings, *, engine_online: bool,
                  model_files_present: bool, workflow_ok: bool,
                  job_running: bool, gpu_required: bool = True) -> GuardReport:
    """Full preflight. Cheap (no allocation); safe to call repeatedly."""
    report = GuardReport()

    # 1. Backend always runs if we're here. Engine status passed in by caller.
    report.add(CheckResult(
        "engine_online", engine_online, True,
        "ComfyUI inference engine is reachable." if engine_online
        else "ComfyUI inference engine is NOT reachable. Start it from the System page or run Start-Studio again.",
    ))

    # 2. Model weights present on disk
    report.add(CheckResult(
        "model_files", model_files_present, True,
        "Selected model files are present." if model_files_present
        else "Selected model files are missing. Install the model on the Models page.",
    ))

    # 3. Workflow template valid
    report.add(CheckResult(
        "workflow", workflow_ok, True,
        "Workflow template validated." if workflow_ok
        else "Workflow template failed validation. See Help & Diagnostics.",
    ))

    # 4. No concurrent generation (sequential-only policy on 8 GB RAM)
    report.add(CheckResult(
        "no_active_job", not job_running, True,
        "No other generation is active." if not job_running
        else "Another generation is already running. This machine has too little RAM for concurrent jobs — wait for it to finish or cancel it.",
    ))

    # 5. System RAM pressure (real measurement)
    mem = detect_memory()
    if mem.available and mem.available_gb is not None:
        blocking = mem.available_gb < settings.min_free_ram_gb_block
        report.add(CheckResult(
            "free_ram", (not blocking) if mem.available_gb >= settings.min_free_ram_gb_warn else False,
            blocking,
            f"Free system RAM: {mem.available_gb:.1f} GB of {mem.total_gb:.0f} GB.",
            value=mem.available_gb,
        ))
        if blocking:
            report.checks[-1].message += (
                " BLOCKED: below the minimum required for video generation. "
                "Close applications (browser tabs especially) and retry."
            )
        elif mem.available_gb < settings.min_free_ram_gb_warn:
            report.checks[-1].message += (
                " WARNING: memory pressure is high; generation may fail or swap heavily."
            )
    else:
        report.add(CheckResult("free_ram", None, False,
                               "Could not measure free system RAM."))

    # 6. Free disk space for frames + output (temp work happens under project root)
    disks = detect_disks([str(settings.project_root)])
    disk = disks[0] if disks else None
    if disk and disk.available and disk.free_gb is not None:
        blocking = disk.free_gb < settings.min_free_disk_gb_block
        ok = disk.free_gb >= settings.min_free_disk_gb_warn
        report.add(CheckResult(
            "free_disk", ok if not blocking else False, blocking,
            f"Free disk space on output drive: {disk.free_gb:.1f} GB.",
            value=disk.free_gb,
        ))
        if blocking:
            report.checks[-1].message += " BLOCKED: not enough space for frames + video output."
        elif not ok:
            report.checks[-1].message += " WARNING: low headroom for temporary frames and videos."
    else:
        report.add(CheckResult("free_disk", None, False, "Could not measure free disk space."))

    # 7. GPU presence (dedicated VRAM check when measurable)
    if gpu_required:
        gpus = detect_gpus()
        if gpus:
            gpu = gpus[0]
            vram_total = gpu.vram_total_mb or 0
            # SD1.5 + AnimateDiff fp16 with --lowvram needs ~2.5-3.5 GB peak.
            enough = vram_total >= 2500 if vram_total else None
            report.add(CheckResult(
                "gpu", enough if enough is not None else None, bool(enough is False),
                f"GPU: {gpu.name} with {vram_total} MB dedicated VRAM."
                if enough is not False else
                f"GPU {gpu.name} reports only {vram_total} MB dedicated VRAM — below the ~2.5 GB needed.",
                value={"name": gpu.name, "vram_total_mb": vram_total},
            ))
            if gpu.vram_free_mb is not None and enough and gpu.vram_free_mb < 1800:
                report.add(CheckResult(
                    "gpu_free_vram", False, False,
                    f"Only {gpu.vram_free_mb} MB VRAM currently free — other applications may cause an out-of-memory failure.",
                    value=gpu.vram_free_mb,
                ))
        else:
            report.add(CheckResult(
                "gpu", None, False,
                "No NVIDIA GPU measurable from the backend (nvidia-smi/pynvml unavailable). "
                "Generation will only work if the engine itself sees a CUDA device.",
            ))

    return report
