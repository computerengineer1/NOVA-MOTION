"""Model registry tests: loading, hardening, allowlist, install-state logic."""
from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.core.errors import NovaError
from app.core.model_registry import ModelRegistry


@pytest.fixture()
def registry(settings: Settings) -> ModelRegistry:
    return ModelRegistry(settings)


def test_registry_loads_all_verified_profiles(registry):
    ids = {p.model_id for p in registry.list_all()}
    assert "animatediff-sd15" in ids
    assert "animatediff-sd15-v3mm" in ids
    # incompatible models are present but documented, never hidden
    assert "ltx-2" in ids and "wan-2.2-t2v" in ids and "hunyuan-video" in ids


def test_recommended_profile_is_installable(registry):
    p = registry.get_installable("animatediff-sd15")
    assert p.status == "recommended"
    assert len(p.files) == 2
    assert all(f.sha256 and len(f.sha256) == 64 for f in p.files)
    assert p.total_download_bytes == sum(f.size_bytes for f in p.files)


def test_incompatible_profiles_refuse_install(registry):
    for mid in ("ltx-2", "ltx-video-2b-098", "wan-2.2-t2v", "hunyuan-video"):
        with pytest.raises(NovaError) as exc:
            registry.get_installable(mid)
        assert exc.value.code == "MODEL_NOT_INSTALLED"
        assert exc.value.detail  # honest reason must be present


def test_unknown_model(registry):
    with pytest.raises(NovaError):
        registry.get("no-such-model")


def test_host_allowlist(registry):
    assert registry.is_url_host_allowed("https://huggingface.co/x/resolve/main/f.bin")
    assert registry.is_url_host_allowed("https://cdn-lfs-us-1.hf.co/x")
    assert not registry.is_url_host_allowed("https://evil.example.com/f.bin")
    assert not registry.is_url_host_allowed("https://huggingface.co.evil.com/f.bin")


def test_corrupt_entry_skipped_not_fatal(settings, tmp_path):
    reg_file = settings.models_registry_file
    data = json.loads(reg_file.read_text())
    data["models"].append({"model_id": "broken"})  # missing required keys
    data["models"].append({
        "model_id": "evil-urls", "name": "x", "model_type": "t", "adapter": "a",
        "status": "recommended", "license_id": "mit", "source": "s",
        "files": [{"id": "f", "dest": "../../escape.bin", "size_bytes": 1,
                   "url": "http://insecure.example.com/f"}],
    })
    reg_file.write_text(json.dumps(data))
    reg = ModelRegistry(settings)
    assert "broken" not in reg.profiles
    assert "evil-urls" not in reg.profiles      # http + traversal rejected
    assert "animatediff-sd15" in reg.profiles   # good entries survive


def test_file_state_missing_and_present(registry, settings):
    p = registry.get("animatediff-sd15")
    st = registry.file_state(p.files[0])
    assert st["installed"] is False
    path = registry.file_path(p.files[0])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * 10)  # wrong size
    st = registry.file_state(p.files[0])
    assert st["installed"] is False and st["checksum_ok"] is False
    assert registry.is_installed(p) is False


def test_checksum_verification(registry, settings, tmp_path):
    import hashlib
    p = registry.get("animatediff-sd15")
    f = p.files[1]
    path = registry.file_path(f)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"motion module bytes"
    path.write_bytes(payload)
    # wrong content -> False (registry has a real sha256)
    assert registry.verify_checksum(f) is False
    # now plant a file whose hash matches the registry entry
    class FakeFile:
        id, dest, size_bytes, url = f.id, f.dest, len(payload), f.url
        sha256 = hashlib.sha256(payload).hexdigest()
        required = True
    assert registry.verify_checksum(FakeFile()) is True


def test_missing_registry_file_raises(settings, tmp_path):
    settings.models_registry_file.unlink()
    with pytest.raises(NovaError):
        ModelRegistry(settings)


def test_checkpoint_and_motion_names(registry):
    p = registry.get("animatediff-sd15")
    assert registry.checkpoint_name(p) == "v1-5-pruned-emaonly-fp16.safetensors"
    assert registry.motion_model_name(p) == "mm_sd_v15_v2.ckpt"
    p3 = registry.get("animatediff-sd15-v3mm")
    assert registry.motion_model_name(p3) == "v3_sd15_mm.ckpt"
