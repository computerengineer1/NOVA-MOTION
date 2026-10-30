"""NOVA MOTION backend entry point (FastAPI).

Run (from the project root venv):
    python -m app.main          # or: uvicorn app.main:app
Bind address defaults to 127.0.0.1 — the app is local-only by design.
"""
from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import engine as engine_api
from .api import generation as generation_api
from .api import health as health_api
from .api import logs as logs_api
from .api import models as models_api
from .api import settings as settings_api
from .api import videos as videos_api
from .api import ws as ws_api
from .config import Settings, get_settings
from .core.errors import NovaError
from .deps import Container, build_container
from .logging_config import get_logger, setup_logging

log = get_logger(__name__)


def _error_response(status: int, code: str, summary: str,
                    recovery: str | None, retryable: bool) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "summary": summary,
                           "recovery": recovery, "retryable": retryable}},
    )


def create_app(container: Container | None = None,
               settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.logs_dir, settings.log_level)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        cont: Container = app.state.container
        log.info("NOVA MOTION backend starting (project root: %s)", settings.project_root)
        cont.ffmpeg.discover()
        await cont.engines.startup()
        await cont.jobs.startup()
        status = await cont.engines.status()
        log.info("Engine status at startup: online=%s version=%s",
                 status.online, status.comfyui_version)
        yield
        log.info("NOVA MOTION backend shutting down…")
        await cont.jobs.shutdown()
        await cont.engines.shutdown()

    app = FastAPI(
        title="NOVA MOTION — Private Local AI Video Studio",
        version="1.0.0",
        description="Local-only text-to-video generation studio. No cloud inference, "
                    "no telemetry, no accounts.",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        # Hard-disable FastAPI's built-in OpenTelemetry instrumentation.
        # NOVA MOTION never exports traces/metrics/logs anywhere (auto_configure
        # is False by default, but we make the zero-telemetry guarantee explicit).
        telemetry={
            "tracing": False, "metrics": False, "logs": False,
            "operation_spans": False, "auto_configure": False,
        },
    )
    app.state.container = container or build_container(settings)

    # --- CORS: localhost origins only -------------------------------------
    allowed_origins = [
        f"http://127.0.0.1:{settings.backend_port}",
        f"http://localhost:{settings.backend_port}",
        "http://127.0.0.1:5173",   # vite dev server
        "http://localhost:5173",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Range"],
        allow_credentials=False,
        max_age=600,
    )

    # --- request body size limit -------------------------------------------
    limit = settings.request_body_limit_bytes

    @app.middleware("http")
    async def body_limit(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > limit:
            return _error_response(413, "REQUEST_TOO_LARGE",
                                   f"Request body exceeds the {limit} byte limit.",
                                   None, False)
        return await call_next(request)

    # --- error handlers ------------------------------------------------------
    @app.exception_handler(NovaError)
    async def nova_error_handler(request: Request, exc: NovaError) -> JSONResponse:
        if exc.detail:
            log.warning("API error [%s] %s | detail: %s", exc.code, exc.summary, exc.detail[:800])
        return _error_response(exc.http_status, exc.code, exc.summary,
                               exc.recovery, exc.retryable)

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return _error_response(
            500, "INTERNAL",
            "An unexpected internal error occurred. Details were written to the local log.",
            "Open Help & Diagnostics → application log tail, then retry the action.",
            False,
        )

    # --- API routers ----------------------------------------------------------
    app.include_router(health_api.router)
    app.include_router(engine_api.router)
    app.include_router(generation_api.router)
    app.include_router(videos_api.router)
    app.include_router(models_api.router)
    app.include_router(settings_api.router)
    app.include_router(logs_api.router)
    app.include_router(ws_api.router)

    # --- static frontend (built SPA) -------------------------------------------
    dist = settings.frontend_dist
    if dist.is_dir() and (dist / "index.html").is_file():
        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            # never serve API paths through the SPA fallback
            if full_path.startswith("api/"):
                return _error_response(404, "NOT_FOUND", f"Unknown API route /{full_path}", None, False)
            candidate = (dist / full_path).resolve() if full_path else None
            index = dist / "index.html"
            if candidate and candidate.is_file() and str(candidate).startswith(str(dist.resolve())):
                return FileResponse(candidate)
            return FileResponse(index)

        log.info("Serving built frontend from %s", dist)
    else:
        log.warning("Frontend build not found at %s — API-only mode. "
                    "Run the frontend build (see README).", dist)

        @app.get("/", include_in_schema=False)
        async def root_hint() -> JSONResponse:
            return JSONResponse({
                "service": "NOVA MOTION backend (API-only mode)",
                "hint": "Frontend build missing. Run: cd frontend && npm ci && npm run build",
                "docs": "/api/docs",
            })

    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    settings.ensure_directories()
    uvicorn.run(
        "app.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        log_level=settings.log_level.lower(),
        access_log=False,
    )


if __name__ == "__main__":
    main()
