"""Real media pipeline tests (ffmpeg/ffprobe actually run in this suite).

Frames are synthetic gradients produced by the test PNG writer — these tests
validate the assembly/encoding/validation plumbing, never AI output.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.config import Settings
from app.core.errors import NovaError
from app.services.ffmpeg import FFmpegService
from app.services.thumbnail_service import ThumbnailService
from app.services.video_assembly import VideoAssemblyService
from app.services.video_validation import validate_output
from tests.fake_comfyui import write_png

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not available in this environment"
)


@pytest.fixture()
def ffmpeg(settings: Settings) -> FFmpegService:
    svc = FFmpegService(settings)
    assert svc.discover()["available"], "ffmpeg/ffprobe must be discoverable"
    return svc


def make_frames(dir: Path, stem: str, count: int, w=64, h=64) -> None:
    for i in range(1, count + 1):
        write_png(dir / f"{stem}_{i:05d}_.png", w, h, i)


async def test_encode_frames_exact_duration(ffmpeg, tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    make_frames(frames, "seg0", 16)
    asm = VideoAssemblyService(ffmpeg)
    out = tmp_path / "seg.mp4"
    n = await asm.encode_frames(frames, "seg0", out, fps=8, expected_frames=16)
    assert n == 16
    summary = await validate_output(ffmpeg, out, expected_duration_s=2.0,
                                    expected_width=64, expected_height=64,
                                    expected_fps=8.0)
    assert summary.codec == "h264" and summary.pix_fmt == "yuv420p"


async def test_frame_count_mismatch_rejected(ffmpeg, tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    make_frames(frames, "seg0", 10)
    asm = VideoAssemblyService(ffmpeg)
    with pytest.raises(NovaError) as exc:
        await asm.encode_frames(frames, "seg0", tmp_path / "o.mp4",
                                fps=8, expected_frames=16)
    assert exc.value.code == "OUTPUT_INVALID"


async def test_multishot_concat_exact_8s(ffmpeg, tmp_path):
    """4 segments x 16 frames @ 8 fps -> exactly 8.000 s (multi-shot route)."""
    asm = VideoAssemblyService(ffmpeg)
    segs = []
    for s in range(4):
        d = tmp_path / f"f{s}"
        d.mkdir()
        make_frames(d, f"seg{s}", 16)
        seg = tmp_path / f"seg{s}.mp4"
        await asm.encode_frames(d, f"seg{s}", seg, fps=8, expected_frames=16)
        segs.append(seg)
    concat = tmp_path / "concat.mp4"
    await asm.concat_segments(segs, concat)
    final = tmp_path / "final.mp4"
    await asm.final_encode(concat, final, export_fps=8, exact_frames=64)
    summary = await validate_output(ffmpeg, final, expected_duration_s=8.0,
                                    expected_fps=8.0)
    assert abs(summary.duration_s - 8.0) <= 1 / 8 + 1e-6


async def test_native_long_64_frames_exact_8s(ffmpeg, tmp_path):
    """Single continuous 64-frame sequence @ 8 fps -> exactly 8.000 s."""
    asm = VideoAssemblyService(ffmpeg)
    d = tmp_path / "frames"
    d.mkdir()
    make_frames(d, "seg0", 64)
    seg = tmp_path / "seg.mp4"
    await asm.encode_frames(d, "seg0", seg, fps=8, expected_frames=64)
    final = tmp_path / "final8.mp4"
    await asm.final_encode(seg, final, export_fps=8, exact_frames=64)
    summary = await validate_output(ffmpeg, final, expected_duration_s=8.0,
                                    expected_fps=8.0)
    assert summary.nb_frames in (64, None) or abs(summary.nb_frames - 64) <= 1


async def test_interpolation_to_16fps_keeps_8s(ffmpeg, tmp_path):
    asm = VideoAssemblyService(ffmpeg)
    d = tmp_path / "frames"
    d.mkdir()
    make_frames(d, "seg0", 32)  # 4 s @ 8 fps source
    seg = tmp_path / "seg.mp4"
    await asm.encode_frames(d, "seg0", seg, fps=8, expected_frames=32)
    interp = tmp_path / "interp.mp4"
    await asm.interpolate(seg, interp, export_fps=16, source_fps=8)
    final = tmp_path / "final16.mp4"
    await asm.final_encode(interp, final, export_fps=16, exact_frames=64)
    summary = await validate_output(ffmpeg, final, expected_duration_s=4.0,
                                    expected_fps=16.0)
    assert summary.fps == pytest.approx(16.0, abs=0.11)


async def test_upscale_lanczos_export(ffmpeg, tmp_path):
    asm = VideoAssemblyService(ffmpeg)
    d = tmp_path / "frames"
    d.mkdir()
    make_frames(d, "seg0", 16)
    seg = tmp_path / "seg.mp4"
    await asm.encode_frames(d, "seg0", seg, fps=8, expected_frames=16)
    final = tmp_path / "up.mp4"
    await asm.final_encode(seg, final, export_fps=8, exact_frames=16, upscale_factor=2)
    summary = await validate_output(ffmpeg, final, expected_duration_s=2.0,
                                    expected_width=128, expected_height=128)
    assert (summary.width, summary.height) == (128, 128)


async def test_validation_rejects_wrong_duration(ffmpeg, tmp_path):
    asm = VideoAssemblyService(ffmpeg)
    d = tmp_path / "frames"
    d.mkdir()
    make_frames(d, "seg0", 16)  # 2.0 s content
    seg = tmp_path / "seg.mp4"
    await asm.encode_frames(d, "seg0", seg, fps=8, expected_frames=16)
    with pytest.raises(NovaError) as exc:
        await validate_output(ffmpeg, seg, expected_duration_s=8.0)  # claims 8 s
    assert exc.value.code == "OUTPUT_INVALID"
    assert "duration" in (exc.value.detail or "").lower()


async def test_validation_rejects_non_video(tmp_path, ffmpeg):
    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"this is not a video at all")
    with pytest.raises(NovaError):
        await validate_output(ffmpeg, fake, expected_duration_s=8.0)


async def test_validation_rejects_empty_file(tmp_path, ffmpeg):
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    with pytest.raises(NovaError) as exc:
        await validate_output(ffmpeg, empty, expected_duration_s=8.0)
    assert "empty" in exc.value.summary.lower()


async def test_thumbnail_created(ffmpeg, tmp_path):
    asm = VideoAssemblyService(ffmpeg)
    d = tmp_path / "frames"
    d.mkdir()
    make_frames(d, "seg0", 16)
    seg = tmp_path / "seg.mp4"
    await asm.encode_frames(d, "seg0", seg, fps=8, expected_frames=16)
    svc = ThumbnailService(ffmpeg)
    thumb = tmp_path / "t.jpg"
    ok = await svc.create(seg, thumb, 2.0)
    assert ok and thumb.stat().st_size > 500


async def test_thumbnail_failure_does_not_raise(ffmpeg, tmp_path):
    svc = ThumbnailService(ffmpeg)
    ok = await svc.create(tmp_path / "missing.mp4", tmp_path / "t.jpg")
    assert ok is False


def test_ffmpeg_missing_raises_helpful_error(settings, monkeypatch):
    svc = FFmpegService(settings)
    monkeypatch.setattr(svc, "_candidate_dirs", lambda: [settings.data_dir / "nowhere"])
    monkeypatch.setattr(shutil, "which", lambda _: None)
    settings.ffmpeg_path_override = ""
    info = svc.discover()
    assert info["available"] is False
    assert "winget" in (info["hint"] or "")
    with pytest.raises(NovaError) as exc:
        svc.require()
    assert exc.value.code == "FFMPEG_MISSING"
