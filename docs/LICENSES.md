# Licenses

NOVA MOTION is a local orchestrator. It does not bundle model weights in Git;
weights are downloaded at install time **from their official sources** with the
license shown and explicitly accepted in the UI first.

## Application code (this repository)

| Component | License |
|---|---|
| NOVA MOTION backend, frontend, scripts, workflows (this repo) | MIT (see below) |

MIT License — Copyright (c) 2026 NOVA MOTION contributors. Permission is
hereby granted, free of charge, to any person obtaining a copy of this software
and associated documentation files (the "Software"), to deal in the Software
without restriction, including without limitation the rights to use, copy,
modify, merge, publish, distribute, sublicense, and/or sell copies of the
Software, subject to the standard MIT terms (THE SOFTWARE IS PROVIDED "AS IS",
WITHOUT WARRANTY OF ANY KIND).

## Runtime dependencies — backend (pip, pinned)

| Package | Version | License |
|---|---|---|
| FastAPI | 0.162.0 | MIT |
| Starlette | 1.10.0 | BSD-3-Clause |
| Uvicorn [standard] | 0.54.0 | BSD-3-Clause |
| Pydantic | 2.14.1 | MIT |
| aiohttp | 3.14.5 | Apache-2.0 |
| psutil | 7.2.2 | BSD-3-Clause |
| pytest / pytest-asyncio / httpx (dev only) | 9.2.0 / 1.4.1 / 0.28.1 | MIT / Apache-2.0 / BSD-3-Clause |

## Runtime dependencies — engine venv (pip, pinned)

| Package | Version | License |
|---|---|---|
| PyTorch (CUDA 13.0 wheels) | 2.14.1 | BSD-3-Clause (+ third-party notices) |
| torchvision | 0.29.1 | BSD-3-Clause |
| ComfyUI requirements set | per v0.43.0 | GPL-3.0 (ComfyUI) + per-package licenses |

## Engine & node packs (installed into `engine/` by the scripts)

| Component | Version | License | Notes |
|---|---|---|---|
| ComfyUI | v0.43.0 | **GPL-3.0** | Runs as a separate process; the backend only talks to its HTTP/WS API |
| ComfyUI-AnimateDiff-Evolved (Kosinkadink) | main @ install | Apache-2.0 | Required for generation |
| ComfyUI-Frame-Interpolation (Fannovel16) | main @ install | MIT | **Optional** (`-WithRife`); RIFE weights fetched by the pack are covered by its own docs |

## Tools

| Tool | Build | License |
|---|---|---|
| FFmpeg / ffprobe | gyan.dev `release-essentials` 7.x | **GPL-2.0+** build (includes x264); used as an external executable via argument arrays — no linking, no modification |

## Model weights (downloaded on demand, license accepted in UI)

| File | Source | License | Size (bytes) |
|---|---|---|---|
| `v1-5-pruned-emaonly-fp16.safetensors` | `Comfy-Org/stable-diffusion-v1-5-archive` (HF) | **CreativeML OpenRAIL-M** | 2,132,696,762 |
| `mm_sd_v15_v2.ckpt` (AnimateDiff motion module v2) | `guoyww/animatediff` (HF) | **Apache-2.0** | 1,817,888,431 |
| `v3_sd15_mm.ckpt` + `v3_sd15_adapter.ckpt` (optional, experimental) | `guoyww/animatediff` (HF) | **Apache-2.0** | 3,908,093,442 (profile total) |

OpenRAIL-M in one line: free to use/modify/redistribute with the same
conditions, plus use-based restrictions (no illegal/harmful uses, no medical
diagnosis, etc.). Read the full text before accepting:
https://huggingface.co/Comfy-Org/stable-diffusion-v1-5-archive — the UI links
it on the model card. SHA-256 digests for every file are pinned in
`models/registry.json` and verified after download.

### Rejected models and why (license + hardware)

- **LTX-2 / LTX-2.3 GGUF** — custom (non-OSI) license; Q2_K DiT ≈ 8.28 GB >
  total system RAM. Not installable here (listed with reasons in the UI).
- **LTX-Video 0.9.8** — node pack `ComfyUI-LTXVideo` is `NOASSERTION`
  (unclear redistribution); needs ≥16 GB RAM in practice.
- **Wan 2.2** — Apache-2.0 code but weights' memory requirements far exceed
  4 GB VRAM / 8 GB RAM.
- **HunyuanVideo** — custom community license (not OSI) + 13B params.

## Frontend dependencies (npm, pinned)

React 19.3.1 & ReactDOM (MIT), react-router-dom 7.18.5 (MIT), lucide-react
1.64.0 (ISC), Tailwind CSS 4.3.3 (MIT), Vite 8.3.5 (MIT), TypeScript 5.9.3
(Apache-2.0), Vitest 5.0.5 (MIT), Testing Library packages (MIT), jsdom
30.1.3 (MIT).

---

No component requires payment, an account, or network access at runtime.
If you redistribute NOVA MOTION, keep this file and the pinned versions
intact; ComfyUI (GPL-3.0) and FFmpeg (GPL build) remain separate processes/
executables — this project does not link against them.
