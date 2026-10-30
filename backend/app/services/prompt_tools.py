"""Prompt tools: deterministic local enhancement + curated style presets.

NO external AI API is called — ever. The enhancer is a transparent template
system: it appends/reorders descriptive tokens and always shows exactly what
it added. The user's original prompt is preserved verbatim and the enhanced
version is only used if the user explicitly applies it.

Why no local LLM: with 8 GB system RAM shared with Windows, a browser, and
the video model, there is no safe headroom to co-host a language model during
a generation. This is stated honestly in the UI.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_NEGATIVE_PROMPT = (
    "worst quality, low quality, blurry, out of focus, distorted anatomy, deformed, "
    "watermark, text, logo, signature, static image, frozen frame, flickering, "
    "jpeg artifacts, oversaturated, cartoonish artifacts"
)

# Quality boosters appended by the enhancer (deterministic, no randomness).
_CINEMATIC_BOOST = (
    "cinematic composition, natural lighting, detailed textures, realistic motion, "
    "smooth camera movement, atmospheric depth, high quality, physically plausible motion"
)

_TOKEN_SPLIT = re.compile(r",\s*")


@dataclass(frozen=True)
class StylePreset:
    id: str
    name: str
    description: str
    positive_suffix: str
    negative_extra: str = ""


STYLE_PRESETS: list[StylePreset] = [
    StylePreset(
        "photoreal_cinematic", "Photorealistic Cinematic",
        "Live-action film look: real lens behavior, natural color, believable physics.",
        "photorealistic, shot on professional cinema camera, 35mm film look, natural color grading, "
        "shallow depth of field, realistic water and fabric physics, natural atmospheric haze",
        "cartoon, illustration, painting, cgi look",
    ),
    StylePreset(
        "nature_documentary", "Nature Documentary",
        "Broadcast wildlife/nature footage: patient framing, golden light, true-to-life color.",
        "nature documentary footage, telephoto lens, golden hour light, natural environment, "
        "wildlife behavior, crisp detail, broadcast color science",
        "people, text overlay, artificial lighting",
    ),
    StylePreset(
        "horror_suspense", "Horror & Suspense",
        "Low-key lighting, slow creeping motion, heavy shadow, uneasy atmosphere.",
        "horror atmosphere, low-key lighting, deep shadows, fog, slow creeping camera movement, "
        "desaturated palette, ominous mood, film grain",
        "bright colors, cheerful, cartoon",
    ),
    StylePreset(
        "science_fiction", "Science Fiction",
        "Futuristic environments, volumetric light, cold technological color palette.",
        "science fiction scene, futuristic technology, volumetric lighting, neon accents, "
        "vast scale, sleek surfaces, cold blue and teal color palette",
        "rustic, vintage, handwritten",
    ),
    StylePreset(
        "dreamcore_liminal", "Dreamcore / Liminal",
        "Empty transitional spaces, uncanny calm, soft washed-out light.",
        "liminal space, dreamcore, empty corridor, uncanny calm, washed-out pastel light, "
        "soft haze, nostalgia, surreal emptiness, vhs softness",
        "crowds, busy scene, harsh contrast",
    ),
    StylePreset(
        "macro_cinematography", "Macro Cinematography",
        "Extreme close-up nature/texture work with tiny depth of field.",
        "macro cinematography, extreme close-up, tiny depth of field, water droplets, "
        "intricate surface detail, soft diffused light, slow deliberate motion",
        "wide shot, landscape, crowds",
    ),
    StylePreset(
        "anime", "Anime",
        "Hand-drawn animation look: bold linework, cel shading, expressive motion.",
        "anime style, hand-drawn 2D animation, cel shading, bold clean lines, "
        "vibrant colors, expressive character acting, sakuga motion",
        "photorealistic, live action, 3d render",
    ),
    StylePreset(
        "product_cinematography", "Product Cinematography",
        "Studio product hero shots: controlled light, slow orbit, pristine surfaces.",
        "product cinematography, studio lighting, slow orbiting camera, pristine reflective surfaces, "
        "clean background, commercial color grading, soft highlights",
        "clutter, dust, scratches, people",
    ),
    StylePreset(
        "historical_atmosphere", "Historical Atmosphere",
        "Period mood: muted palette, period-accurate light sources, filmic grain.",
        "historical atmosphere, period setting, muted earthy palette, candlelight and overcast sky, "
        "aged film grain, archival footage feel, authentic costumes and architecture",
        "modern objects, neon, plastic look",
    ),
    StylePreset(
        "aerial_landscapes", "Aerial Landscapes",
        "Drone-style sweeping geography: vast scale, smooth glide, clear air.",
        "aerial drone shot, sweeping landscape, vast scale, smooth gliding camera, "
        "clear atmospheric perspective, mountains and coastline, epic wide framing",
        "close-up, indoor, portrait",
    ),
]

_PRESETS_BY_ID = {p.id: p for p in STYLE_PRESETS}

EXAMPLE_PROMPTS = [
    "A photorealistic cinematic shot of a massive wave crashing into a rocky coastline at sunset, "
    "captured with a professional cinema camera, realistic water physics, natural atmospheric haze, "
    "detailed textures, smooth camera movement, physically plausible lighting, and authentic cinematic motion.",
    "Slow aerial glide over misty pine forest at dawn, volumetric god rays through the fog, "
    "calm birds drifting below, documentary color grading.",
    "Macro shot of morning dew sliding down a spider web, extremely shallow depth of field, "
    "soft golden backlight, gentle breeze.",
    "A lone lighthouse on a cliff during a thunderstorm, lightning flashes illuminating heavy rain, "
    "dark churning sea, dramatic clouds, cinematic color grade.",
    "Neon-lit rainy alley at night, reflections on wet asphalt, steam rising from a vent, "
    "slow dolly forward, science fiction mood.",
    "Time-lapse feeling of clouds flowing over alpine peaks at sunset, warm to cool color shift, "
    "epic scale, smooth aerial perspective.",
    "Close-up of coffee being poured into a ceramic cup on a wooden table, warm window light, "
    "gentle swirl and steam, product cinematography.",
    "An old steam train crossing a stone viaduct through autumn forest, drifting smoke, "
    "historical atmosphere, filmic grain.",
]


def list_presets() -> list[dict]:
    return [
        {"id": p.id, "name": p.name, "description": p.description,
         "positive_suffix": p.positive_suffix, "negative_extra": p.negative_extra}
        for p in STYLE_PRESETS
    ]


def list_examples() -> list[str]:
    return list(EXAMPLE_PROMPTS)


def enhance(prompt: str, style_preset: str | None = None) -> dict:
    """Deterministic template enhancement. Returns new prompt + explanation.

    Guarantees:
      * the original text appears verbatim at the start of the result;
      * no tokens are removed from the user's prompt;
      * duplicates (case-insensitive) are not appended twice.
    """
    base = prompt.strip().rstrip(",")
    additions: list[str] = []
    if style_preset:
        preset = _PRESETS_BY_ID.get(style_preset)
        if preset is None:
            raise ValueError(f"Unknown style preset: {style_preset}")
        additions.extend(_TOKEN_SPLIT.split(preset.positive_suffix))
    additions.extend(_TOKEN_SPLIT.split(_CINEMATIC_BOOST))

    existing = {t.strip().lower() for t in _TOKEN_SPLIT.split(base)}
    unique_new: list[str] = []
    for token in additions:
        t = token.strip()
        if t and t.lower() not in existing and t.lower() not in {u.lower() for u in unique_new}:
            unique_new.append(t)

    enhanced = base + (", " + ", ".join(unique_new) if unique_new else "")
    preset_note = ""
    if style_preset:
        preset = _PRESETS_BY_ID[style_preset]
        preset_note = f" Applied the '{preset.name}' style preset and"
    explanation = (
        f"{preset_note} appended {len(unique_new)} descriptive quality tokens "
        "(deterministic local template — no external AI service was called). "
        "Your original wording is kept verbatim at the start; nothing was removed. "
        "Apply the result only if you like it."
    )
    return {"enhanced_prompt": enhanced, "method": "template",
            "explanation": explanation, "original_preserved": True,
            "added_tokens": unique_new}


def apply_preset_to_negative(negative: str, style_preset: str | None) -> str:
    if not style_preset:
        return negative
    preset = _PRESETS_BY_ID.get(style_preset)
    if preset is None or not preset.negative_extra:
        return negative
    base = negative.strip().rstrip(",")
    existing = {t.strip().lower() for t in _TOKEN_SPLIT.split(base)}
    extra = [t.strip() for t in _TOKEN_SPLIT.split(preset.negative_extra)
             if t.strip() and t.strip().lower() not in existing]
    return base + (", " + ", ".join(extra) if extra else "")
