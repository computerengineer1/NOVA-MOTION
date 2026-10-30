"""Builds ComfyUI API-format workflows for the registered model adapters.

The workflow is assembled programmatically from parameters that were already
validated by the API schema layer, then re-validated (statically here, and
live against the engine's /object_info before submission). Node IDs and input
names were verified against:
  * ComfyUI v0.43.0 core nodes.py (CheckpointLoaderSimple, CLIPTextEncode,
    EmptyLatentImage, KSampler, VAEDecodeTiled, SaveImage)
  * ComfyUI-AnimateDiff-Evolved main@2026-07 (V3 io.ComfyNode schemas:
    ADE_LoadAnimateDiffModel, ADE_ApplyAnimateDiffModelSimple,
    ADE_StandardUniformContextOptions, ADE_AnimateDiffSamplingSettings,
    ADE_UseEvolvedSampling)
"""
from __future__ import annotations

from typing import Any

from .errors import ErrorCode, NovaError

WORKFLOW_ID_ANIMATEDIFF_T2V = "animatediff_t2v"

# Nodes required by each workflow (used for live validation against /object_info)
REQUIRED_NODES: dict[str, list[str]] = {
    WORKFLOW_ID_ANIMATEDIFF_T2V: [
        "CheckpointLoaderSimple",
        "CLIPTextEncode",
        "EmptyLatentImage",
        "KSampler",
        "VAEDecodeTiled",
        "SaveImage",
        "ADE_LoadAnimateDiffModel",
        "ADE_ApplyAnimateDiffModelSimple",
        "ADE_StandardUniformContextOptions",
        "ADE_AnimateDiffSamplingSettings",
        "ADE_UseEvolvedSampling",
    ],
}


def build_animatediff_t2v(
    *,
    checkpoint_name: str,
    motion_model_name: str,
    positive_prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    frames: int,
    steps: int,
    cfg: float,
    sampler_name: str,
    scheduler: str,
    seed: int,
    filename_prefix: str,
    context_length: int = 16,
    context_overlap: int = 4,
    context_stride: int = 1,
    vae_tile_size: int = 512,
    vae_overlap: int = 64,
    noise_type: str = "FreeNoise",
    seed_gen: str = "comfy",
    beta_schedule: str = "autoselect",
) -> dict[str, Any]:
    """Return the workflow as a ComfyUI /prompt-compatible dict.

    Constraint checks mirror the workflow's real limits — they are enforced
    here as well so a programming error cannot produce an invalid submission.
    """
    if width % 8 or height % 8:
        raise NovaError(ErrorCode.WORKFLOW_INVALID,
                        "Width/height must be multiples of 8 (SD1.5 latent constraint).")
    if frames < 1 or frames > 128:
        raise NovaError(ErrorCode.WORKFLOW_INVALID,
                        "Frame count must be between 1 and 128 for this model.")
    if context_length < 2 or context_length > min(frames, 16):
        raise NovaError(ErrorCode.WORKFLOW_INVALID,
                        "Context length must be between 2 and min(frames, 16).")
    if not (0 <= context_overlap < context_length):
        raise NovaError(ErrorCode.WORKFLOW_INVALID,
                        "Context overlap must satisfy 0 <= overlap < context_length.")

    wf: dict[str, Any] = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint_name},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive_prompt, "clip": ["1", 1]},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["1", 1]},
        },
        "4": {
            "class_type": "ADE_LoadAnimateDiffModel",
            "inputs": {"model_name": motion_model_name},
        },
        "5": {
            "class_type": "ADE_ApplyAnimateDiffModelSimple",
            "inputs": {"motion_model": ["4", 0]},
        },
        "6": {
            "class_type": "ADE_StandardUniformContextOptions",
            "inputs": {
                "context_length": context_length,
                "context_stride": context_stride,
                "context_overlap": context_overlap,
                "fuse_method": "pyramid",
                "use_on_equal_length": False,
                "start_percent": 0.0,
                "guarantee_steps": 1,
            },
        },
        "7": {
            "class_type": "ADE_AnimateDiffSamplingSettings",
            "inputs": {
                "batch_offset": 0,
                "noise_type": noise_type,
                "seed_gen": seed_gen,
                "seed_offset": 0,
                "seed_override": seed,
                "adapt_denoise_steps": False,
            },
        },
        "8": {
            "class_type": "ADE_UseEvolvedSampling",
            "inputs": {
                "model": ["1", 0],
                "beta_schedule": beta_schedule,
                "m_models": ["5", 0],
                "context_options": ["6", 0],
                "sample_settings": ["7", 0],
            },
        },
        "9": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": frames},
        },
        "10": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["8", 0],
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler_name,
                "scheduler": scheduler,
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["9", 0],
                "denoise": 1.0,
            },
        },
        "11": {
            "class_type": "VAEDecodeTiled",
            "inputs": {
                "samples": ["10", 0],
                "vae": ["1", 2],
                "tile_size": vae_tile_size,
                "overlap": vae_overlap,
                "temporal_size": 64,
                "temporal_overlap": 8,
            },
        },
        "12": {
            "class_type": "SaveImage",
            "inputs": {"images": ["11", 0], "filename_prefix": filename_prefix},
        },
    }
    return wf


def build_workflow(workflow_id: str, params: dict[str, Any]) -> dict[str, Any]:
    """Adapter dispatch — extend here when new model adapters are added."""
    if workflow_id == WORKFLOW_ID_ANIMATEDIFF_T2V:
        return build_animatediff_t2v(**params)
    raise NovaError(
        ErrorCode.WORKFLOW_INVALID,
        f"No workflow builder registered for '{workflow_id}'.",
        recovery="Select a model whose adapter is supported by this build.",
        http_status=422,
    )
