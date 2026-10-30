"""Path security + identifier validation tests (security-critical)."""
from __future__ import annotations

import pytest
from pathlib import Path

from app.core.errors import NovaError
from app.core.path_security import (
    assert_within, atomic_write_bytes, is_safe_identifier,
    require_safe_identifier, safe_subpath,
)


def test_safe_subpath_normal(tmp_path):
    p = safe_subpath(tmp_path, "models", "checkpoints", "x.safetensors")
    assert p == (tmp_path / "models" / "checkpoints" / "x.safetensors").resolve()


def test_safe_subpath_rejects_traversal(tmp_path):
    with pytest.raises(NovaError) as exc:
        safe_subpath(tmp_path, "..", "..", "etc", "passwd")
    assert exc.value.code == "PATH_SECURITY"


def test_safe_subpath_rejects_absolute(tmp_path):
    with pytest.raises(NovaError):
        safe_subpath(tmp_path, "/etc/passwd")
    with pytest.raises(NovaError):
        safe_subpath(tmp_path, "C:\\Windows\\system32")


def test_safe_subpath_rejects_nul(tmp_path):
    with pytest.raises(NovaError):
        safe_subpath(tmp_path, "evil\x00.png")


def test_safe_subpath_rejects_encoded_traversal_after_normalize(tmp_path):
    with pytest.raises(NovaError):
        safe_subpath(tmp_path, "a/../../..")


def test_assert_within_allows_inside(tmp_path):
    inner = tmp_path / "outputs" / "v.mp4"
    inner.parent.mkdir()
    inner.write_bytes(b"x")
    assert assert_within(tmp_path / "outputs", inner) == inner.resolve()


def test_assert_within_blocks_outside(tmp_path):
    outside = tmp_path.parent / "not-mine.mp4"
    with pytest.raises(NovaError):
        assert_within(tmp_path / "outputs", outside)


def test_symlink_escape_blocked(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("s3cret")
    link = root / "escape"
    link.symlink_to(secret)
    with pytest.raises(NovaError):
        assert_within(root, link)


@pytest.mark.parametrize("value,expected", [
    ("20261029-120000-ab12cd34", True),
    ("animatediff-sd15", True),
    ("model_v1.2-3", True),
    ("", False),
    ("../evil", False),
    ("has space", False),
    ("a" * 200, False),
    ("-leading-dash", False),
    ("slash/inside", False),
    ("back\\slash", False),
])
def test_identifier_rules(value, expected):
    assert is_safe_identifier(value) is expected


def test_require_safe_identifier_raises():
    with pytest.raises(NovaError) as exc:
        require_safe_identifier("../x", "job id")
    assert exc.value.http_status == 422


def test_atomic_write_bytes(tmp_path):
    target = tmp_path / "a" / "b.bin"
    atomic_write_bytes(target, b"hello")
    assert target.read_bytes() == b"hello"
    assert not list(tmp_path.rglob("*.tmp"))
