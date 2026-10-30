"""Engine control endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..schemas.common import OkResponse
from ..schemas.hardware import EngineStatus
from .health import _engine_to_schema

router = APIRouter(prefix="/api/engine", tags=["engine"])


def _get_container(request: Request):
    return request.app.state.container


@router.get("/status", response_model=EngineStatus)
async def engine_status(request: Request, force: bool = False) -> EngineStatus:
    container = _get_container(request)
    status = await container.engines.status(force=force)
    return _engine_to_schema(status)


@router.post("/restart", response_model=EngineStatus)
async def engine_restart(request: Request) -> EngineStatus:
    container = _get_container(request)
    status = await container.engines.restart_managed_engine()
    return _engine_to_schema(status)


@router.post("/free", response_model=OkResponse)
async def engine_free(request: Request) -> OkResponse:
    container = _get_container(request)
    ok = await container.engines.adapter.free_memory()
    return OkResponse(ok=ok, detail="Engine memory freed." if ok else
                      "Engine did not accept the free request (offline?).")


@router.get("/capabilities")
async def engine_capabilities(request: Request) -> dict:
    """What optional node packs are actually present in the live engine.
    Used by the UI to disable unsupported options *before* submission —
    never guessed client-side."""
    from ..core.errors import NovaError

    container = _get_container(request)
    online = (await container.engines.status()).online
    rife_available = False
    if online:
        try:
            info = await container.engines.adapter.fetch_object_info()
            rife_available = any(k.startswith("RIFE") or "VHS_RIFE" in k
                                 for k in info.keys())
        except NovaError:
            rife_available = False
    return {"engine_online": online, "rife_available": rife_available}
