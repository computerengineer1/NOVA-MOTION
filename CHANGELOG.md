# Changelog

All notable changes to NOVA MOTION. Format loosely follows Keep a Changelog.

## [1.0.0] — 2026-10-29

First complete release.

### Added
- **Backend** (FastAPI, Python 3.13, SQLite metadata):
  - Job state machine QUEUED → PREFLIGHT → INITIALIZING → GENERATING →
    ASSEMBLING → INTERPOLATING → ENCODING → VALIDATING →
    COMPLETED/FAILED/CANCELLED with legal-transition enforcement and
    crash-recovery of stale rows at startup.
  - ComfyUI engine adapter over the **official API only** (POST /prompt,
    GET /history/{id}, POST /queue, POST /interrupt, POST /free,
    GET /object_info, GET /system_stats, WS /ws), managed subprocess
    auto-start with low-VRAM flags, watchdog with exactly one bounded restart.
  - 12-node AnimateDiff workflow builder (signatures verified against
    ComfyUI-AnimateDiff-Evolved) + static & live workflow validation.
  - FFmpeg pipeline: PNG sequence → h264/yuv420p MP4, multi-shot concat,
    minterpolate with tpad/-frames:v exact-trim compensation, Lanczos ×2
    upscale, thumbnail extraction; **duration validated to 8.000 s ± 1 frame
    via ffprobe** before COMPLETED; honest labeled provenance.
  - Resource guard: free RAM/disk gates (block < 1.2 GB RAM / < 1.5 GB disk,
    warn < 2.2 GB / < 4 GB), dedicated-VRAM detection via nvidia-smi
    (shared memory never counted), sequential-only queue (1 running + 1
    queued, 429 beyond).
  - Single automatic lower-memory retry on CUDA OOM (multi-shot downgrade),
    recorded in job metrics; never an infinite retry loop.
  - Model manager: registry with pinned URLs/sizes/SHA-256/licenses,
    host allowlist, resumable downloads, per-file checksum verification,
    license acceptance required, path-traversal-proof destinations,
    validation & removal endpoints; incompatible profiles listed with
    measured reasons.
  - Deterministic local prompt enhancer (template-based; original text always
    preserved verbatim; apply/discard is explicit in the UI) + curated style
    presets and example prompts.
  - WebSocket progress with reconnect-safe snapshots; REST remains the source
    of truth. Cancellation is cooperative and reported truthfully
    (`cancel_requested` until the real terminal state).
  - Security: loopback-only binding, telemetry explicitly disabled
    (FastAPI OTel instrumentation off), path-traversal protection on every
    file route, subprocess argument arrays (no shell), no eval of user text,
    HTTP Range video streaming confined to `outputs/`.
- **Frontend** (React 19 + TypeScript + Vite 8 + Tailwind 4):
  - Six pages: Studio, My Videos, Models, System, Settings, Help/Diagnostics.
  - Studio: prompt editor (enhance with explicit apply/discard, presets,
    seed control), full generation/export settings with capability-driven
    disabling, server-computed effective-settings summary + live preflight
    (debounced), honest progress panel (stages from real status, measured
    ETA, live sampler detail), output panel with validated metadata and
    provenance labels, recent-jobs list, full "reuse settings" round-trip.
  - My Videos: searchable/filterable library, in-app player (custom controls),
    download, delete with confirmation, reveal in Explorer, provenance badges.
  - Models: license display + acceptance gate, per-file install state with
    sizes/checksums, live install progress, disk headroom check against real
    free space, validate/remove, incompatible models listed with reasons.
  - System: readiness banner (health ≠ readiness), hardware tiles, RAM /
    dedicated-VRAM / disk bars, engine start/restart/free controls, app &
    engine log viewers, diagnostic bundle download.
  - Settings: persisted generation defaults + safety toggles (random seed,
    one-shot OOM downgrade); security posture displayed as read-only facts.
  - Help: beginner quick-start, honesty policy, script reference, FAQ.
- **Scripts** (PowerShell 5.1-compatible, no admin rights):
  Install-Studio, Start-Studio, Stop-Studio, Diagnose-Studio (-HashModels),
  Repair-Studio — each with a .bat wrapper. Stop only kills processes it can
  attribute to this project; Repair never deletes videos and only deletes
  corrupt weights with explicit confirmation.
- **Docs**: README, MODEL_COMPATIBILITY (verified rejections with numbers),
  TROUBLESHOOTING (mapped to the real error-code catalogue), LICENSES.
- **Tests (actually executed)**:
  - Backend: **152 pytest tests passing** — path security, schemas, DB,
    workflow build/validation, registry arithmetic, prompt tools, real-FFmpeg
    8.000 s pipeline (native + multi-shot + 16 fps interpolation), 18
    full-stack integration tests against a fake ComfyUI replaying the real
    API contract (queue limits, cancellation, OOM downgrade, persistence
    across restart, stale-job recovery, WS events, Range 206, reveal
    traversal block), resumable downloads with checksum/truncation handling.
  - Frontend: **37 vitest tests passing** — API client error mapping, WS
    reconnect/backoff/dedup, formatter purity, honest provenance labels,
    stage derivation, enhance apply/discard flow, UI primitive a11y.
  - Production build verified (`tsc -b` clean, `vite build` 381 KB JS /
    117 KB gzip) and served by the backend; full HTTP smoke test of the
    SPA + API passed.

### Known limitations (honest)
- Real GPU inference could not be executed in the development sandbox (no
  NVIDIA GPU present) — the pipeline is integration-tested against a fake
  engine that replays the verified ComfyUI API contract; first run on the
  target machine may need driver-level adjustments documented in
  TROUBLESHOOTING.md.
- 8 s @ 8 fps native is the guaranteed exact-duration route; 16/24 fps
  exports rely on interpolation (labeled), and RIFE on 4 GB VRAM is
  experimental.
- Generation speed on RTX 2050 is minutes per video (est. 7–17 min for the
  default 16-step 64-frame route) — the UI shows measured ETAs, not promises.
