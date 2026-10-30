# NOVA MOTION — Private Local AI Video Studio

Generate **exactly 8-second videos from text**, entirely on your own Windows 11
machine. No accounts, no subscriptions, no cloud, no telemetry. After a one-time
download of dependencies and model weights, the studio works **fully offline**.

Built and tuned for modest hardware — reference target:

| Component | Reference machine |
|---|---|
| CPU | AMD Ryzen 5 7535HS |
| GPU | NVIDIA RTX 2050 Laptop — **4 GB dedicated GDDR6** |
| RAM | 8 GB |
| Disk | ~477 GB SSD (free space is detected, never assumed) |
| OS | Windows 11 Home, no admin rights required |

> The app **detects your real hardware** at runtime (dedicated VRAM via
> `nvidia-smi`, never the inflated "shared GPU memory" number) and refuses to
> start work that cannot fit. It never fabricates progress, never pads videos to
> fake a duration, and labels every post-processing step (interpolation,
> upscale, multi-shot) everywhere it appears.

---

## What it does

- **Text → 8.000 s MP4** (±1 frame, verified with `ffprobe` before a job may
  complete — a file that doesn't measure up is FAILED, not shipped).
- **Local video library** ("My Videos") with in-app playback, download,
  thumbnails, search, and honest provenance badges
  (`8fps native` / `interpolated` / `upscaled ×2 lanczos` / `multi-shot`).
- **Model manager** with license display + explicit acceptance, exact sizes,
  SHA-256 verification, resumable downloads, disk-space checks, validation and
  removal. Incompatible models are *listed with the measured reason*, not hidden.
- **Real progress**: stage pipeline (QUEUED → PREFLIGHT → INITIALIZING →
  GENERATING → ASSEMBLING → INTERPOLATING → ENCODING → VALIDATING →
  COMPLETED/FAILED/CANCELLED), step-level detail from the engine's WebSocket,
  and an ETA that only appears **after** the backend measures your machine's
  real sampler step rate.
- **Low-VRAM safeguards**: sequential jobs only, `--lowvram --cache-none`
  engine flags, VRAM released after every job, RAM/VRAM/disk preflight gates,
  and exactly **one** automatic lower-memory retry on CUDA OOM (then a clean
  failure with recovery advice — never an infinite retry loop).
- **Diagnostics**: hardware report, readiness verdict (HTTP 200 ≠ ready —
  readiness additionally checks engine, FFmpeg, model files and free
  resources), log viewers, and a one-click diagnostic bundle (saved locally,
  never uploaded).

## What it is not

- Not a demo: there is **no demo mode**, no stock footage, no simulated
  generation. If the engine or models are missing, the UI says so and blocks.
- Not a cloud wrapper: the only network use is the one-time installation and
  model download. There is no telemetry of any kind (FastAPI instrumentation is
  explicitly disabled at startup).
- Not a LAN service: backend (`127.0.0.1:8317`) and ComfyUI
  (`127.0.0.1:8188`) bind to loopback only.

---

## Architecture

```
 Browser UI (React 19 + TS + Vite, Tailwind 4)
        │ same-origin HTTP + WS
 FastAPI backend (Python 3.13, uvicorn)  ── SQLite metadata (data/nova.db)
        │ official HTTP/WS API            ── FFmpeg assembly/interpolation/encode/validate
 ComfyUI v0.43.0 engine (own venv, torch 2.14.1+cu130)
        │ custom node
 ComfyUI-AnimateDiff-Evolved  →  SD 1.5 (fp16) + AnimateDiff motion module
```

- **Backend** owns the job state machine, preflight gates, workflow building
  (12-node AnimateDiff graph, all node signatures verified against
  AnimateDiff-Evolved), engine supervision (auto-start, watchdog, one bounded
  restart), post-processing and validation.
- **Engine adapter** is modular (`engines/base.py`): the ComfyUI adapter talks
  only to the official API (`POST /prompt`, `GET /history/{id}`, `POST
  /interrupt`, `POST /free`, `GET /object_info`, `GET /ws`). Another engine can
  be added behind the same interface.
- **Frontend** is a static build served by the backend itself (dev mode uses a
  Vite proxy). REST polling is the source of truth; the WebSocket only
  accelerates updates.

## Requirements (one-time, ~8 GB disk + ~4 GB models)

- Windows 10/11, **no admin rights**, no Docker/WSL, no system changes.
- **Python 3.13** (python.org installer; check "py launcher" or "Add to PATH").
- **NVIDIA GPU + recent driver** (CUDA 13.0 wheels need driver ≥ 580.x;
  GeForce Experience or nvidia.com updates it without admin hassle). The RTX
  2050 Laptop (compute capability 8.9) is fully supported. AMD/Intel GPUs and
  CPU-only machines are **not** supported (honest blocker, shown in UI).
- **Node.js ≥ 20.19 LTS** — only to build the UI once (or build it on another
  machine and copy `frontend/dist`).
- ~15 GB free disk to be comfortable.

## Install & run (beginner guide)

1. Put the `NOVA-MOTION` folder somewhere with space (e.g. `C:\NOVA-MOTION`).
2. Double-click **`scripts\Install-Studio.bat`** (or right-click
   `Install-Studio.ps1` → *Run with PowerShell*). It installs everything
   *inside the folder*: backend venv, ComfyUI v0.43.0, engine venv with
   torch 2.14.1 (cu130), the AnimateDiff node pack, and FFmpeg. The torch
   download is ~3 GB — the slowest step. Nothing else on your PC is touched.
3. Double-click **`scripts\Start-Studio.bat`**. A console window opens (backend;
   it auto-starts ComfyUI with low-VRAM flags) and your browser opens
   `http://127.0.0.1:8317`.
4. Open **Models** → the recommended *AnimateDiff v2 Motion + SD 1.5 (fp16)*
   card → read the licenses (Apache-2.0 motion module, CreativeML OpenRAIL-M
   checkpoint) → tick *I accept* → **Install (~3.7 GB)**. Downloads resume if
   interrupted; every file is SHA-256 verified.
5. Open **Studio**, type a prompt (or click *Examples* / *Enhance prompt* —
   a deterministic local template, never a hidden rewrite), pick 8 s / 16:9 /
   8 fps native, press **Generate 8-second video**.
   First run: expect roughly **10–25 minutes** on an RTX 2050 (model load +
   64 frames). The panel shows real sampler steps and a measured ETA.
6. When the pipeline reaches COMPLETED, the video plays right there, with its
   validated duration, exact seed, and provenance. Download it or find it in
   **My Videos** and `outputs\`.
7. Done for the day? Run **`scripts\Stop-Studio.bat`** (frees VRAM first,
   stops only NOVA's own processes).

Other scripts: `Diagnose-Studio.bat` (full hardware/artifact/port report,
add `-HashModels` for SHA-256), `Repair-Studio.bat` (fix venvs, verify model
checksums, restore FFmpeg).

## Honest expectations (RTX 2050 4 GB / 8 GB RAM)

- Default route: **640×360, 64 frames @ 8 fps native**, 16 steps,
  `dpmpp_2m`/`karras`, sliding-window context 16 — this fits 4 GB with
  `--lowvram`. 512×512 and 360×640 also fit; **768×432 is flagged high-risk**
  and will likely OOM (one auto-retry at lower memory, then FAILED).
- 16/24 fps exports use **FFmpeg minterpolate** (motion-compensated,
  conventional) or optional **RIFE** (AI, experimental on 4 GB, install with
  `Install-Studio.ps1 -WithRife`). Both are labeled *interpolated* everywhere:
  in-between frames are estimates, not newly generated content.
- **Upscale ×2** is Lanczos resizing — explicitly *not* AI super-resolution.
- **multi-shot** mode (4 × 2 s segments) is labeled as such; motion continuity
  across segment cuts is not guaranteed.
- Generation is **sequential** — one job at a time (queue max: 1 running + 1
  queued). This is deliberate on 8 GB RAM.
- Close browsers/games while generating: they eat VRAM and RAM, and the
  preflight will warn or block below ~1.2 GB free RAM.

## Development

```
backend/    FastAPI app (tests: backend\.venv\Scripts\python -m pytest tests -q)
frontend/   React 19 + Vite 8 + Tailwind 4 (npm install; npm test; npm run build)
engine/     ComfyUI installation (created by Install-Studio)
models/     registry.json (URLs, sizes, SHA-256, licenses, capabilities)
workflows/  ComfyUI workflow templates (12-node AnimateDiff graph)
scripts/    Install / Start / Stop / Diagnose / Repair (.ps1 + .bat)
docs/       MODEL_COMPATIBILITY.md, TROUBLESHOOTING.md, LICENSES.md
```

- Dev mode: start backend (`uvicorn app.main:app --port 8317` from `backend/`),
  then `npm run dev` in `frontend/` (Vite proxies `/api` incl. WS to 8317).
- Tests that actually run: **152 backend pytest tests** (incl. real-FFmpeg
  8.000 s duration validation, full HTTP→engine→encode→DB integration against a
  fake ComfyUI, cancellation, OOM single-downgrade, resumable downloads with
  checksums, path-traversal defense) and **37 frontend vitest tests** (API
  client error mapping, WS reconnect/backoff, honest-label rendering, stage
  derivation, enhance apply/discard flow).

## Docs

- [`docs/MODEL_COMPATIBILITY.md`](docs/MODEL_COMPATIBILITY.md) — why
  AnimateDiff+SD1.5 won, and why LTX-2/Wan/Hunyuan/LTX-Video were **rejected
  with measured numbers** for this hardware class.
- [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) — every failure mode we
  could anticipate, with the exact error code the backend emits.
- [`docs/LICENSES.md`](docs/LICENSES.md) — all third-party components and model
  licenses.
- [`CHANGELOG.md`](CHANGELOG.md) — version history.

## Security & privacy

- Loopback-only binding; no analytics/telemetry/tracking; no eval of user text;
  subprocesses use argument arrays (no shell); file access is path-traversal
  protected (IDs are validated, paths resolved and prefix-checked); video
  streaming supports HTTP Range but never escapes `outputs/`.
- Your weights and videos are never auto-deleted — not even for disk space.
