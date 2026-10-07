"""
app/main.py

FastAPI application factory.
Use create_app() to build the app — this pattern makes the app
easy to test (each test can get a fresh instance).
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import (
    auth,
    audit,
    health,
    research,
    users,
    settings as settings_router,
    telemetry,
    recipe,
)
from app.core.config import settings
from app.core.logging import setup_logging
from app.utils.exceptions import register_exception_handlers

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""

    # ── Logging must be first ─────────────────────────────────────────────────
    setup_logging()
    
    import time
    from fastapi import Request
    from starlette.middleware.base import BaseHTTPMiddleware

    class LoggingMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            # Suppress noisy GET/OPTIONS logs for dashboard polling and CORS preflight
            silent_paths = ["/research-runs", "/research", "/admin/usage"]
            is_silent = (
                request.method == "OPTIONS" or
                (request.method == "GET" and any(p in request.url.path for p in silent_paths))
            )
            
            if not is_silent:
                logger.info("HTTP REQUEST\n------------\nMETHOD: %s\nPATH: %s\nORIGIN: %s\nCONTENT_TYPE: %s", 
                            request.method, request.url.path, request.client.host, request.headers.get("content-type"))
            
            start_time = time.time()
            response = await call_next(request)
            process_time = time.time() - start_time
            
            if not is_silent:
                logger.info("HTTP RESPONSE\n-------------\nMETHOD: %s\nPATH: %s\nSTATUS: %s\nLATENCY: %s",
                            request.method, request.url.path, response.status_code, process_time)
            return response

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Production-grade API for the Apcotex R&D "
            "Patent Research & Polymer Recipe Simulation platform."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    import os
    # Default to specific local origins if not set, instead of "*" which breaks with credentials
    origins_env = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174")
    allowed_origins = [origin.strip() for origin in origins_env.split(",")]
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    app.add_middleware(LoggingMiddleware)

    # ── Exception Handlers ────────────────────────────────────────────────────
    register_exception_handlers(app)

    # ── Routers ───────────────────────────────────────────────────────────────
    from app.api.v1 import admin_usage
    app.include_router(admin_usage.router, prefix="/api/v1")
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(research.router)
    app.include_router(audit.router)
    app.include_router(settings_router.router, prefix="/api/v1/settings", tags=["Settings"])
    app.include_router(telemetry.router, prefix="/api/v1/research", tags=["Telemetry"])
    app.include_router(recipe.router, prefix="/api/v1")

    @app.on_event("startup")
    async def startup_event():
        if settings.SEED_DEFAULT_USERS:
            try:
                from app.db.session import AsyncSessionLocal
                from app.db.seed import ensure_default_users

                async with AsyncSessionLocal() as session:
                    await ensure_default_users(session)
                logger.info("Default user seeding completed")
            except Exception as e:
                logger.error("Failed to seed default users: %s", type(e).__name__)
        else:
            logger.info("Default user seeding is disabled")

        # Six-month saved-recipe retention cleanup (startup + hourly)
        try:
            import asyncio
            from app.services.saved_recipe_service import run_saved_recipe_cleanup_once

            async def _retention_loop():
                while True:
                    try:
                        deleted = await run_saved_recipe_cleanup_once()
                        if deleted:
                            logger.info("Saved-recipe retention cleanup removed %d record(s)", deleted)
                    except Exception as cleanup_err:
                        logger.error("Saved-recipe retention cleanup failed: %s", cleanup_err)
                    await asyncio.sleep(3600)

            asyncio.create_task(_retention_loop())
        except Exception as e:
            logger.error("Failed to start saved-recipe retention loop: %s", e)

    logger.info("Application startup complete — %s v%s", settings.APP_NAME, settings.APP_VERSION)
    return app


# Module-level app instance used by uvicorn
app: FastAPI = create_app()
