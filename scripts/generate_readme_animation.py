#!/usr/bin/env python3
"""Generate the original looping NOVA MOTION banner used by the GitHub README.

The animation is abstract project branding, not a screenshot or a sample AI render.
Run from the repository root:
    python scripts/generate_readme_animation.py
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "assets" / "nova-motion-loop.gif"
WIDTH, HEIGHT = 960, 280
FRAME_COUNT = 48
FRAME_DURATION_MS = 75


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"]
        if bold else
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


TITLE_FONT = load_font(48, bold=True)
SUBTITLE_FONT = load_font(17, bold=True)
BODY_FONT = load_font(14)
MICRO_FONT = load_font(11, bold=True)


def lerp(a: int, b: int, t: float) -> int:
    return round(a + (b - a) * t)


def background() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT))
    pixels = image.load()
    for y in range(HEIGHT):
        vertical = y / max(1, HEIGHT - 1)
        for x in range(WIDTH):
            horizontal = x / max(1, WIDTH - 1)
            glow = max(0.0, 1.0 - math.sqrt(((x - 730) / 650) ** 2 + ((y - 120) / 360) ** 2))
            pixels[x, y] = (
                lerp(7, 17, vertical) + round(8 * glow),
                lerp(10, 17, horizontal) + round(10 * glow),
                lerp(27, 55, horizontal) + round(35 * glow),
            )
    return image


BASE = background()
FONT_COLOR = (241, 244, 255, 255)
MUTED_COLOR = (151, 164, 194, 255)


def render_frame(frame_index: int) -> Image.Image:
    phase = frame_index / FRAME_COUNT * math.tau
    frame = BASE.copy().convert("RGBA")

    # Fine technical grid and corner marks.
    grid = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    grid_draw = ImageDraw.Draw(grid)
    for x in range(28, WIDTH, 42):
        grid_draw.line((x, 18, x, HEIGHT - 18), fill=(111, 129, 192, 22), width=1)
    for y in range(20, HEIGHT, 42):
        grid_draw.line((22, y, WIDTH - 22, y), fill=(111, 129, 192, 22), width=1)
    grid_draw.rounded_rectangle((20, 18, WIDTH - 20, HEIGHT - 18), radius=22,
                                outline=(136, 151, 211, 75), width=1)
    frame.alpha_composite(grid)

    # Animated orbital engine mark with a soft neon halo.
    halo = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    halo_draw = ImageDraw.Draw(halo)
    cx, cy = 758, 132
    halo_draw.ellipse((cx - 102, cy - 102, cx + 102, cy + 102),
                      outline=(104, 92, 255, 95), width=5)
    halo_draw.ellipse((cx - 72, cy - 72, cx + 72, cy + 72),
                      outline=(0, 212, 255, 105), width=3)
    halo = halo.filter(ImageFilter.GaussianBlur(12))
    frame.alpha_composite(halo)

    mark = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    d = ImageDraw.Draw(mark)
    d.ellipse((cx - 85, cy - 85, cx + 85, cy + 85),
              outline=(119, 112, 255, 210), width=2)
    d.ellipse((cx - 54, cy - 54, cx + 54, cy + 54),
              outline=(36, 213, 240, 190), width=2)
    d.arc((cx - 70, cy - 70, cx + 70, cy + 70),
          start=math.degrees(phase) % 360,
          end=(math.degrees(phase) + 220) % 360,
          fill=(205, 193, 255, 245), width=5)

    for index, radius in enumerate((85, 54, 118)):
        angle = phase * (1.0 if index != 1 else -1.4) + index * 2.1
        px = cx + math.cos(angle) * radius
        py = cy + math.sin(angle) * radius * 0.72
        color = ((117, 102, 255, 255), (22, 218, 239, 255), (255, 255, 255, 230))[index]
        d.ellipse((px - 6, py - 6, px + 6, py + 6), fill=color)
        d.ellipse((px - 12, py - 12, px + 12, py + 12),
                  outline=(*color[:3], 80), width=2)

    # A luminous central "N" built from simple geometric strokes.
    d.rounded_rectangle((cx - 28, cy - 27, cx + 28, cy + 27),
                        radius=13, fill=(14, 20, 52, 230),
                        outline=(113, 203, 255, 220), width=2)
    d.line((cx - 15, cy + 16, cx - 15, cy - 16, cx + 15, cy + 16, cx + 15, cy - 16),
           fill=(230, 242, 255, 255), width=6, joint="curve")
    frame.alpha_composite(mark)

    # Moving scan line sweeping through the system.
    scan_x = 58 + ((frame_index / FRAME_COUNT) * 840)
    scan = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scan)
    sd.line((scan_x, 34, scan_x, HEIGHT - 34), fill=(64, 225, 255, 160), width=2)
    sd.ellipse((scan_x - 4, 128, scan_x + 4, 136), fill=(190, 250, 255, 255))
    scan = scan.filter(ImageFilter.GaussianBlur(5))
    frame.alpha_composite(scan)

    # Text panel.
    panel = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    p = ImageDraw.Draw(panel)
    p.rounded_rectangle((52, 48, 578, 228), radius=18,
                        fill=(8, 13, 35, 118), outline=(133, 146, 213, 54), width=1)
    p.rounded_rectangle((72, 64, 250, 88), radius=12,
                        fill=(40, 47, 105, 160), outline=(105, 122, 245, 140), width=1)
    p.ellipse((84, 72, 92, 80), fill=(50, 231, 178, 255))
    p.text((101, 68), "LOCAL-FIRST  /  AI VIDEO", font=MICRO_FONT, fill=(191, 206, 255, 255))
    p.text((70, 103), "NOVA MOTION", font=TITLE_FONT, fill=FONT_COLOR,
           stroke_width=1, stroke_fill=(52, 64, 130, 180))
    p.text((74, 163), "YOUR PROMPT. YOUR GPU. YOUR VIDEO.", font=SUBTITLE_FONT,
           fill=(95, 218, 245, 255))
    p.text((74, 196), "PROMPT   →   FRAMES   →   CINEMATIC MP4", font=BODY_FONT,
           fill=MUTED_COLOR)

    # Small heartbeat indicator and animated progress trace.
    pulse = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(phase * 2))
    alpha = round(100 + pulse * 155)
    p.ellipse((866, 48, 875, 57), fill=(52, alpha, 171, 255))
    p.text((884, 46), "READY", font=MICRO_FONT, fill=(182, 230, 218, 255))
    bar_x0, bar_y = 650, 238
    p.rounded_rectangle((bar_x0, bar_y, 866, bar_y + 4), radius=2,
                        fill=(80, 103, 165, 110))
    progress = (frame_index % FRAME_COUNT) / FRAME_COUNT
    p.rounded_rectangle((bar_x0, bar_y, bar_x0 + round(216 * progress), bar_y + 4),
                        radius=2, fill=(71, 211, 245, 230))
    frame.alpha_composite(panel)
    return frame.convert("RGB")


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frames = [render_frame(index) for index in range(FRAME_COUNT)]
    # Convert each full frame to an adaptive palette to keep the repository asset small.
    paletted = [frame.quantize(colors=128, method=Image.Quantize.FASTOCTREE) for frame in frames]
    paletted[0].save(
        OUTPUT,
        save_all=True,
        append_images=paletted[1:],
        duration=FRAME_DURATION_MS,
        loop=0,
        optimize=True,
        disposal=2,
    )
    print(f"Generated {OUTPUT} ({OUTPUT.stat().st_size:,} bytes, {FRAME_COUNT} frames)")


if __name__ == "__main__":
    main()
