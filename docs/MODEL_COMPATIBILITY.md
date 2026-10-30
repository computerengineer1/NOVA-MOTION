# Model Compatibility — decisions with measured numbers

Target hardware class (the reference machine this project was built for):

- **RTX 2050 Laptop GPU — 4096 MB dedicated GDDR6** (compute capability 8.9,
  Ada Lovelace; supports FP8/FP16/BF16 in hardware — note: *support* for FP8
  exists, but we do **not** force FP8 checkpoints: the SD1.5 route below simply
  fits in FP16 and is better verified)
- **8 GB system RAM** (no pagefile changes allowed)
- ~477 GB SSD (free space detected at runtime; models need ~4 GB)

Rule applied: *a small model that reliably finishes beats a large model that
crashes*. Every rejection below is based on published model-card sizes and
memory requirements checked against upstream repos/HF on **2026-10-29** — not
on marketing claims.

---

## ✅ CHOSEN: AnimateDiff (motion module v2) + Stable Diffusion 1.5 fp16

| Item | Value (verified) |
|---|---|
| Checkpoint | `v1-5-pruned-emaonly-fp16.safetensors` — **2,132,696,762 bytes** |
| Source | `Comfy-Org/stable-diffusion-v1-5-archive` (Hugging Face) |
| SHA-256 | `e9476a13…db6e3916` (full value in `models/registry.json`) |
| License | CreativeML OpenRAIL-M |
| Motion module | `mm_sd_v15_v2.ckpt` — **1,817,888,431 bytes** |
| Source | `guoyww/animatediff` (Hugging Face) |
| SHA-256 | `69ed0f5f…d1cad1bf0` (full value in `models/registry.json`) |
| License | Apache-2.0 |
| **Total download** | **3,950,585,193 bytes ≈ 3.68 GiB** |
| Node pack | `Kosinkadink/ComfyUI-AnimateDiff-Evolved` (Apache-2.0, actively maintained) |

Why it wins on 4 GB VRAM + 8 GB RAM:

- SD1.5 UNet fp16 ≈ 1.7 GB weights; the motion module adds ≈ 1.7 GB but only
  the motion layers are active per step. With ComfyUI `--lowvram` (text encoder
  kept on CPU, modules streamed) the working set fits in 4 GB at 640×360×16-frame
  context — the exact configuration the workflow builder emits.
- Native 8 fps × 64 frames = **exactly 8.000 s** with a sliding uniform context
  (length 16, stride 1, overlap 4) — no cut points, continuous motion.
- Everything is verified end-to-end in this repo: node names/parameters
  (`ADE_LoadAnimateDiffModel`, `ADE_ApplyAnimateDiffModelSimple`,
  `ADE_UseEvolvedSampling` with `beta_schedule="autoselect"`,
  `ADE_StandardUniformContextOptions`, `ADE_AnimateDiffSamplingSettings` with
  FreeNoise) were checked against the node pack source, and the full pipeline
  (workflow → engine → frames → FFmpeg → 8.000 s validation → DB) is covered by
  integration tests against a fake ComfyUI that replays the real API contract.

Also listed: **v3 motion module** (`v3_sd15_mm.ckpt` + adapter, 3,908,093,442
bytes total, Apache-2.0) as *supported* — better motion quality per its model
card, slightly heavier; keep v2 as the default until you've succeeded once.

## ❌ REJECTED (listed in the Models page with reasons, not hidden)

### LTX-2 / LTX-2.3 (Lightricks, 19B–22B DiT)
- The smallest practical quantization we verified — `unsloth/LTX-2.3-GGUF`
  **Q2_K ≈ 8.28 GB for the DiT alone** — exceeds the machine's *entire* 8 GB
  RAM before activations, text encoder or OS. GGUF CPU-offload workflows need
  host RAM well above the file size.
- Community evidence for "runs on 4 GB VRAM" explicitly excludes the 8 GB-RAM
  constraint. Dead end on this machine; no honest configuration exists.

### LTX-Video 0.9.8 (2B DiT)
- fp8/fp16 weights + T5 text encoder + activations need **≥16 GB system RAM in
  practice** on this GPU class; with 8 GB RAM the OS starts paging and the
  engine dies mid-run. Its ComfyUI node pack also carries a `NOASSERTION`
  license (unclear redistribution terms) — we don't ship unclear licenses.

### Wan 2.2 (1.3B / 14B T2V)
- Even the 1.3B variant's published memory guidance exceeds 4 GB dedicated
  VRAM for video-length generation without aggressive quantization + offload,
  which again collides with the 8 GB RAM ceiling; the 14B model is far out of
  reach. Apache-2.0 code but weights' practical requirements disqualify it.

### HunyuanVideo (13B)
- 13B DiT: published requirements are ~2×–6× this machine's VRAM depending on
  quantization; community GGUF routes need tens of GB of host RAM for offload.
- Custom community license (not OSI) — additional reason not to default to it.

> These four appear in `models/registry.json` with `status: "incompatible"` so
> the Models page shows *why* (measured memory notes) instead of silently
> omitting them. The backend refuses to install them
> (`MODEL_NOT_INSTALLABLE`-style check in `_compatibility`).

## Frame interpolation

| Method | Status | Notes |
|---|---|---|
| **FFmpeg `minterpolate`** | Default, always available | Motion-compensated, *conventional* (not generative). Emits 2n−3 frames for n inputs — the assembler compensates with `tpad` clone padding + exact `-frames:v` trim, then duration is re-validated. `scd=none` + `vsbmc` are required for stable output. |
| **RIFE** (`Fannovel16/ComfyUI-Frame-Interpolation`, MIT, active) | Optional, experimental on 4 GB | Optical-flow AI interpolation. The original Kosinkadink repo is gone (404 — do not use that URL). Install with `Install-Studio.ps1 -WithRife`; the Studio detects availability live via `GET /api/engine/capabilities` and disables the option with an explanation when absent. |

## Upscaling

Only **FFmpeg Lanczos ×2** is offered, and every surface labels it
"conventional resize — NOT AI super-resolution". AI upscalers (ESRGAN etc.)
were rejected: extra VRAM for marginal benefit at 640×360→1280×720 on this GPU.

## Version pins (verified 2026-10-29)

| Component | Pin | Source of truth |
|---|---|---|
| ComfyUI | **v0.43.0** (2026-10-27) | github tag; API routes verified from its `server.py` |
| Python | 3.13 | ComfyUI system requirements ("3.13 recommended") |
| torch / torchvision | **2.14.1 / 0.29.1 + cu130** | latest stable cp313 win_amd64 wheels on download.pytorch.org |
| ComfyUI-AnimateDiff-Evolved | main @ install time | Apache-2.0, active |
| FFmpeg | gyan.dev `release-essentials` (7.x) | GPL build, ~114 MB zip |
| Frontend | React 19.3.1, Vite 8.3.5, TS 5.9.3, Tailwind 4.3.3, vitest 5.0.5 | npm registry, engines-compatible with Node ≥20.19/22.12+ |
| Backend | FastAPI 0.162.0, uvicorn 0.54.0, pydantic 2.14.1, aiohttp 3.14.5, psutil 7.2.2 | PyPI |

Do not upgrade these without re-running both test suites; they are a verified
compatible set, not "latest for fun".
