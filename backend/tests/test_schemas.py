"""Schema validation tests — the API must never trust frontend values."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.generation import EnhanceRequest, GenerationRequest

BASE = dict(prompt="a cat walking", model_id="animatediff-sd15")


def test_minimal_valid_request():
    req = GenerationRequest(**BASE)
    assert req.duration_seconds == 8.0
    assert req.aspect_ratio == "16:9"
    assert req.steps == 16
    assert req.random_seed is True


@pytest.mark.parametrize("prompt", ["", "   ", "\n\t "])
def test_blank_prompt_rejected(prompt):
    with pytest.raises(ValidationError):
        GenerationRequest(**{**BASE, "prompt": prompt})


def test_prompt_too_long_rejected():
    with pytest.raises(ValidationError):
        GenerationRequest(**{**BASE, "prompt": "x" * 2001})


def test_control_characters_stripped():
    req = GenerationRequest(**{**BASE, "prompt": "a\x00b\x07 cat"})
    assert "\x00" not in req.prompt and "\x07" not in req.prompt


@pytest.mark.parametrize("duration", [8.0, 4.0, 2.0, 6.0])
def test_supported_durations(duration):
    assert GenerationRequest(**{**BASE, "duration_seconds": duration}).duration_seconds == duration


@pytest.mark.parametrize("duration", [7.5, 8.1, 0, 16, 3])
def test_unsupported_durations_rejected(duration):
    with pytest.raises(ValidationError):
        GenerationRequest(**{**BASE, "duration_seconds": duration})


def test_bad_model_id_rejected():
    with pytest.raises(ValidationError):
        GenerationRequest(**{**BASE, "model_id": "../etc/passwd"})
    with pytest.raises(ValidationError):
        GenerationRequest(**{**BASE, "model_id": "UPPER-CASE"})


@pytest.mark.parametrize("steps", [0, 3, 41, 1000])
def test_steps_bounds(steps):
    with pytest.raises(ValidationError):
        GenerationRequest(**{**BASE, "steps": steps})


@pytest.mark.parametrize("cfg", [0.5, 15.1, -1])
def test_cfg_bounds(cfg):
    with pytest.raises(ValidationError):
        GenerationRequest(**{**BASE, "cfg": cfg})


def test_interpolation_requires_higher_fps():
    with pytest.raises(ValidationError):
        GenerationRequest(**{**BASE, "interpolation": "minterpolate", "export_fps": 8})
    req = GenerationRequest(**{**BASE, "interpolation": "minterpolate", "export_fps": 16})
    assert req.export_fps == 16


def test_seed_required_when_not_random():
    with pytest.raises(ValidationError):
        GenerationRequest(**{**BASE, "random_seed": False, "seed": None})
    req = GenerationRequest(**{**BASE, "random_seed": False, "seed": 42})
    assert req.seed == 42


def test_bad_aspect_and_mode_and_fps():
    with pytest.raises(ValidationError):
        GenerationRequest(**{**BASE, "aspect_ratio": "4:3"})
    with pytest.raises(ValidationError):
        GenerationRequest(**{**BASE, "generation_mode": "turbo"})
    with pytest.raises(ValidationError):
        GenerationRequest(**{**BASE, "export_fps": 30})


def test_enhance_request_bounds():
    with pytest.raises(ValidationError):
        EnhanceRequest(prompt="")
    EnhanceRequest(prompt="ok", style_preset="anime")
