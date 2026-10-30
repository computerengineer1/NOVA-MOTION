"""Workflow builder + static validation + template parity tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.errors import NovaError
from app.core.workflow_builder import (
    REQUIRED_NODES, WORKFLOW_ID_ANIMATEDIFF_T2V, build_animatediff_t2v, build_workflow,
)
from app.core.workflow_validation import validate_required_nodes, validate_static

BACKEND = Path(__file__).resolve().parents[1]
TEMPLATE = BACKEND.parent / "workflows" / "animatediff_t2v.template.json"


def make_wf(**overrides):
    params = dict(
        checkpoint_name="v1-5-pruned-emaonly-fp16.safetensors",
        motion_model_name="mm_sd_v15_v2.ckpt",
        positive_prompt="a wave crashing", negative_prompt="blurry",
        width=640, height=360, frames=64, steps=16, cfg=7.5,
        sampler_name="dpmpp_2m", scheduler="karras", seed=12345,
        filename_prefix="nova/test-job/seg0",
    )
    params.update(overrides)
    return build_animatediff_t2v(**params)


def test_builds_valid_graph():
    wf = make_wf()
    validate_static(wf)  # must not raise
    classes = {n["class_type"] for n in wf.values()}
    assert classes == set(REQUIRED_NODES[WORKFLOW_ID_ANIMATEDIFF_T2V])


def test_8s_64_frames_defaults():
    wf = make_wf(frames=64)
    assert wf["9"]["inputs"]["batch_size"] == 64
    assert wf["6"]["inputs"]["context_length"] == 16
    assert wf["6"]["inputs"]["context_overlap"] == 4


def test_frame_constraints():
    with pytest.raises(NovaError):
        make_wf(frames=129)
    with pytest.raises(NovaError):
        make_wf(frames=0)


def test_dimensions_must_be_multiple_of_8():
    with pytest.raises(NovaError):
        make_wf(width=641)


def test_context_constraints():
    with pytest.raises(NovaError):
        make_wf(frames=16, context_overlap=16)
    with pytest.raises(NovaError):
        make_wf(frames=8, context_length=16)  # context > frames


def test_static_validation_catches_broken_link():
    wf = make_wf()
    wf["10"]["inputs"]["model"] = ["999", 0]
    with pytest.raises(NovaError) as exc:
        validate_static(wf)
    assert "missing node" in exc.value.summary.lower() or "links" in exc.value.summary.lower()


def test_static_validation_catches_cycle():
    wf = {"a": {"class_type": "X", "inputs": {"i": ["b", 0]}},
          "b": {"class_type": "Y", "inputs": {"i": ["a", 0]}}}
    with pytest.raises(NovaError):
        validate_static(wf)


def test_missing_required_nodes_detected():
    missing = validate_required_nodes(WORKFLOW_ID_ANIMATEDIFF_T2V,
                                      {"CheckpointLoaderSimple", "KSampler"})
    assert "ADE_UseEvolvedSampling" in missing
    assert "CheckpointLoaderSimple" not in missing


def test_unknown_workflow_id():
    with pytest.raises(NovaError):
        build_workflow("does_not_exist", {})


def test_template_parity():
    """The documented template must match the builder's structure exactly
    (class types, links, and all non-placeholder widget values)."""
    template = json.loads(TEMPLATE.read_text())
    built = make_wf()
    assert set(template.keys()) == set(built.keys())
    for nid, tnode in template.items():
        bnode = built[nid]
        assert tnode["class_type"] == bnode["class_type"], nid
        for key, tval in tnode["inputs"].items():
            bval = bnode["inputs"][key]
            if isinstance(tval, str) and tval.startswith("{{"):
                continue  # placeholder
            assert tval == bval, f"node {nid} input {key}: template={tval} built={bval}"


def test_seed_determinism():
    a, b = make_wf(seed=777), make_wf(seed=777)
    assert a == b
    assert a["10"]["inputs"]["seed"] == 777
    assert a["7"]["inputs"]["seed_override"] == 777
