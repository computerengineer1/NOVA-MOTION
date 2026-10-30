"""Prompt tools: deterministic enhancer + presets (no external AI, ever)."""
from __future__ import annotations

import pytest

from app.services import prompt_tools


def test_all_ten_style_presets_present():
    ids = {p.id for p in prompt_tools.STYLE_PRESETS}
    assert {"photoreal_cinematic", "nature_documentary", "horror_suspense",
            "science_fiction", "dreamcore_liminal", "macro_cinematography",
            "anime", "product_cinematography", "historical_atmosphere",
            "aerial_landscapes"} <= ids
    assert len(prompt_tools.STYLE_PRESETS) == 10


def test_enhance_preserves_original_verbatim():
    original = "A massive wave crashing into a rocky coastline at sunset"
    result = prompt_tools.enhance(original)
    assert result["enhanced_prompt"].startswith(original)
    assert result["original_preserved"] is True
    assert result["method"] == "template"


def test_enhance_is_deterministic():
    a = prompt_tools.enhance("a lighthouse in a storm", "horror_suspense")
    b = prompt_tools.enhance("a lighthouse in a storm", "horror_suspense")
    assert a["enhanced_prompt"] == b["enhanced_prompt"]


def test_enhance_no_duplicate_tokens():
    prompt = "cinematic composition, natural lighting, a quiet lake"
    result = prompt_tools.enhance(prompt)
    tokens = [t.strip().lower() for t in result["enhanced_prompt"].split(",")]
    assert len(tokens) == len(set(tokens))


def test_enhance_unknown_preset_raises():
    with pytest.raises(ValueError):
        prompt_tools.enhance("x", "no-such-preset")


def test_negative_preset_merge():
    base = "blurry, watermark"
    out = prompt_tools.apply_preset_to_negative(base, "anime")
    assert out.startswith(base)
    assert "photorealistic" in out
    assert prompt_tools.apply_preset_to_negative(base, None) == base
    assert prompt_tools.apply_preset_to_negative(base, "nope") == base


def test_examples_are_real_prompt_strings():
    examples = prompt_tools.list_examples()
    assert len(examples) >= 5
    assert any("wave" in e for e in examples)  # the spec's example prompt is included
