"""Settings endpoints (whitelisted keys, validated values)."""
from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Request

from ..core.errors import ErrorCode, NovaError
from ..schemas.models import SettingsPatch

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _bad(message: str) -> Any:
    raise ValueError(message)


def _int_in(lo: int, hi: int) -> Callable[[Any], int]:
    def _v(x: Any) -> int:
        n = int(x)
        return n if lo <= n <= hi else _bad(f"must be {lo}..{hi}")
    return _v


def _float_in(lo: float, hi: float) -> Callable[[Any], float]:
    def _v(x: Any) -> float:
        n = float(x)
        return n if lo <= n <= hi else _bad(f"must be {lo}..{hi}")
    return _v


def _one_of(*allowed: Any) -> Callable[[Any], Any]:
    def _v(x: Any) -> Any:
        return x if x in allowed else _bad(f"must be one of {allowed}")
    return _v


_VALIDATORS: dict[str, Callable[[Any], Any]] = {
    "default_model_id": lambda v: str(v)[:128],
    "default_steps": _int_in(4, 40),
    "default_cfg": _float_in(1.0, 15.0),
    "default_sampler": _one_of("euler", "euler_ancestral", "dpmpp_2m", "dpmpp_sde", "uni_pc"),
    "default_scheduler": _one_of("normal", "karras", "exponential", "sgm_uniform"),
    "default_aspect_ratio": _one_of("16:9", "9:16", "1:1"),
    "default_duration_seconds": _one_of(2.0, 4.0, 6.0, 8.0),
    "default_generation_mode": _one_of("auto", "native_long", "multi_shot"),
    "default_export_fps": _one_of(8, 16, 24),
    "default_interpolation": _one_of("none", "minterpolate", "rife"),
    "default_upscale_export": bool,
    "random_seed_default": bool,
    "oom_auto_downgrade_once": bool,
}


def _get_container(request: Request):
    return request.app.state.container


@router.get("")
async def get_settings(request: Request) -> dict:
    container = _get_container(request)
    return container.settings_repo.get_all()


@router.patch("")
async def patch_settings(patch: SettingsPatch, request: Request) -> dict:
    container = _get_container(request)
    if not patch.values:
        raise NovaError(ErrorCode.VALIDATION_ERROR, "No settings provided.", http_status=422)
    cleaned: dict[str, Any] = {}
    for key, value in patch.values.items():
        validator = _VALIDATORS.get(key)
        if validator is None:
            raise NovaError(ErrorCode.VALIDATION_ERROR,
                            f"Setting '{key}' is not a known key.",
                            recovery=f"Allowed keys: {', '.join(sorted(_VALIDATORS))}",
                            http_status=422)
        try:
            cleaned[key] = validator(value)
        except (ValueError, TypeError) as exc:
            raise NovaError(ErrorCode.VALIDATION_ERROR,
                            f"Invalid value for '{key}': {exc}", http_status=422)
    try:
        container.settings_repo.update_many(cleaned)
    except Exception as exc:  # noqa: BLE001
        raise NovaError(ErrorCode.DATABASE_WRITE_FAILED,
                        "Settings could not be saved to the local database.",
                        detail=str(exc), retryable=True, http_status=500)
    return container.settings_repo.get_all()
