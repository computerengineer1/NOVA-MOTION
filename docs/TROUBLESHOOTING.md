# Troubleshooting

Every failure in NOVA MOTION carries a stable **error code** (shown in the UI
toast/progress panel, in `logs/app.log`, and in the diagnostic bundle). Find
yours below. If nothing matches, run `scripts\Diagnose-Studio.bat` and read the
report top-to-bottom — it measures everything the backend measures.

General rule: the backend **never leaves you guessing** — a failed job always
states what blocked it and how to recover, and a partially written file is
never presented as a finished video.

---

## Startup & installation

### `Install-Studio.bat` says "Python 3.13 was not found"
Install Python 3.13 from python.org (per-user install needs no admin; tick
*py launcher*). Verify with `py -3.13 --version`, then re-run the installer.

### Torch download stalls or fails
It's ~3 GB from `download.pytorch.org`. The installer uses pip's normal
retry; if your network drops often, re-run `Install-Studio.bat` — completed
steps are skipped, pip resumes its cache. Proxy users: set `HTTPS_PROXY` in
the *same console* before running (the scripts never change system settings).

### Backend window opens then closes immediately
Run it manually to see the error:
`cd backend` → `.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8317`.
Most common cause: another program already owns port 8317/8188
(`Diagnose-Studio.bat` §7 shows who). Change ports only via
`NOVA_BACKEND_PORT` / `NOVA_ENGINE_PORT` env vars in your console session.

### UI shows "backend offline" banner
1. Is the backend console window open? If not, `Start-Studio.bat`.
2. `Diagnose-Studio.bat` → §7: does `GET /api/health` answer?
3. Browser cached an old UI? Hard-refresh (Ctrl+F5).

### `frontend\dist missing` warning
The UI needs a one-time build: install Node.js LTS (≥20.19), then
`cd frontend && npm install && npm run build`. Everything else works
regardless (the API is independent).

---

## Engine (ComfyUI)

### `ENGINE_UNREACHABLE` / "Engine offline" on System page
- Press **Start engine** (or restart the backend — it auto-starts the engine).
- First start after install can take 30–90 s (torch import). Watch
  *Logs → ComfyUI engine log* live.
- If the engine log shows CUDA errors at startup: update your NVIDIA driver
  (cu130 wheels need a recent driver; GeForce Experience or nvidia.com — no
  CUDA toolkit installation needed).
- The watchdog restarts a dead managed engine **once**; a second death stays
  dead by design (no infinite restart loops) — read the engine log, fix the
  cause, restart manually.

### `ENGINE_TIMEOUT`
The engine accepted the job but produced no progress for 30 minutes
(heartbeat). On 4 GB VRAM with heavy settings this can be swap-thrashing:
close other apps, reduce to 640×360, 16 steps, 8 fps, and retry.

### `CUSTOM_NODE_MISSING` (RIFE)
You selected RIFE interpolation but the optional node pack isn't installed.
Either pick **minterpolate** (built into FFmpeg, always available) or run
`Install-Studio.ps1 -WithRife`. The Studio disables the RIFE option
automatically when `GET /api/engine/capabilities` reports it absent.

### `WORKFLOW_INVALID`
Should not happen with the shipped template (it is statically validated at
build time and live-checked via `/object_info` during preflight). If a ComfyUI
update broke node signatures, re-run `Repair-Studio.bat` and confirm
ComfyUI is still the pinned **v0.43.0**.

---

## Models & downloads

### `MODEL_NOT_INSTALLED` / `MODEL_FILE_MISSING`
Open **Models** → install the recommended profile. The Studio blocks
generation (preflight `BLOCKED`) until required files exist with correct sizes.

### `MODEL_FILE_CORRUPT` / "SHA-256 mismatch"
Run `Repair-Studio.bat` — it re-hashes every installed file against
`models/registry.json`, and (only with your explicit confirmation) deletes
corrupt ones so the installer re-downloads them. Downloads **resume** from
`.part` files; a truncated file is detected by size before hashing.

### `MODEL_LICENSE_NOT_ACCEPTED`
The install API requires `accept_license: true`; the UI only enables the
Install button after you tick the license checkbox. Read the license (links on
the card), then tick it.

### `DOWNLOAD_FAILED` / `DOWNLOAD_INTERRUPTED`
Check free disk (Models page header shows real free space) and network. The
backend only downloads from the allowlisted hosts in `registry.json`
(huggingface.co + its CDN mirrors) — a corporate proxy blocking those will
show up here. Re-run the install; it resumes.

### Install button disabled with "Not enough free disk space"
Real measured free space < required bytes + 10% headroom. Free space yourself
— NOVA never deletes your files to make room.

---

## Generation

### `GPU_OUT_OF_MEMORY` (CUDA OOM)
What happens automatically: the job retries **once** with the lower-memory
route (multi-shot 4×16 frames + smaller context) and the metrics record
`oom_downgrade_applied: true`. If it fails again:
1. Close browsers/games/Discord — on a laptop GPU they hold real VRAM.
2. Use 640×360 (never 768×432 on 4 GB), 16 steps, 8 fps.
3. Reboot if VRAM stays occupied (Windows desktop manager can hold ~1 GB).
There is deliberately **no infinite OOM retry loop**.

### `INSUFFICIENT_RAM` (preflight blocked)
Free RAM below 1.2 GB blocks generation (2.2 GB warns). Close apps; 8 GB
machines are tight — that's why jobs are sequential and `--cache-none` is set.

### `INSUFFICIENT_DISK`
Below 1.5 GB free blocks (4 GB warns). Videos are small (~1–3 MB each) but
intermediate PNG frames for a job use a few hundred MB temporarily.

### `QUEUE_FULL` (HTTP 429)
One job runs + one may queue. This is a hardware-protection policy on 8 GB
RAM, not a bug. Wait for the running job (or cancel it) and resubmit.

### `JOB_CANCELLED` / "Cancel requested" lingering
Cancellation is **cooperative**: ComfyUI stops between sampling steps
(`POST /interrupt`), so a long step can delay it by seconds. The UI shows
*Cancel requested* until the true terminal state (`CANCELLED`) is confirmed —
it never pretends the job stopped before it did. Temp frames are cleaned up;
no partial file enters the library.

### `OUTPUT_INVALID` — "duration … outside tolerance"
The final MP4 measured outside 8.000 s ± 1 frame, so the job FAILED instead of
shipping a wrong-length video (the measured duration is in the error detail).
This is the honesty gate working as designed; simply re-run — if it repeats,
run `Diagnose-Studio.bat` (FFmpeg version section) and check
`logs/app.log` for the ffprobe JSON.

### `FFMPEG_MISSING` / `ENCODE_FAILED`
FFmpeg must be at `tools\ffmpeg\bin\` or on PATH. `Repair-Studio.bat`
re-downloads it. `ENCODE_FAILED` includes the exact ffmpeg stderr tail in the
job error detail — disk full is the usual culprit.

### Video looks static / barely moves
AnimateDiff at 8 fps over 8 s produces gentle motion by nature. Help it:
describe the motion explicitly ("crashing", "drifting", "walking toward"),
keep 1 subject, avoid "timelapse"-style prompts for big scene changes, and
try the v3 motion module (Models page, *supported*). Multi-shot mode changes
scenes every ~2 s if you want visible variety (labeled as such).

### First generation is much slower than later ones
Expected: first run loads the checkpoint + motion module from disk (cold
cache). Later runs reuse the warm engine — but the backend still calls
`POST /free` between jobs, so a small reload cost remains by design (8 GB RAM
protection).

---

## UI oddities

- **"polling…" next to the status badge** — the WebSocket is reconnecting;
  REST polling (≤2 s) keeps state correct meanwhile. Nothing to fix unless it
  never reconnects (then check the browser console for WS blocks by extensions).
- **ETA missing at job start** — honest by design: ETA appears only after the
  backend measures real step rate (~2 sampler steps in).
- **Thumbnail missing but video plays** — thumbnail generation failed
  (`THUMBNAIL_FAILED` is non-fatal); the MP4 itself passed validation.

## Still stuck?

1. `scripts\Diagnose-Studio.bat -HashModels`
2. Copy `logs\diagnostic-<timestamp>.json/txt` + the last 50 lines of
   `logs\app.log` and `logs\engine_comfyui.log`.
3. The diagnostic bundle from Help/System pages contains all of it as JSON.

None of these leave your machine automatically — there is no telemetry.
