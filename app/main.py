"""ClipClean — FastAPI application entry point."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routes.health import router as health_router
from app.routes.jobs import router as jobs_router
from app.services import storage
from app.services.job_manager import job_manager

# ── Logging ───────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ── Periodic cleanup ─────────────────────────────────────────────


async def _periodic_cleanup() -> None:
    """Sweep old jobs and temp files every five minutes."""
    while True:
        try:
            await asyncio.sleep(300)
            await job_manager.cleanup_old_jobs()
            for d in (settings.UPLOAD_DIR, settings.OUTPUT_DIR, settings.TEMP_DIR):
                storage.cleanup_old_files(d, settings.CLEANUP_AGE_SECONDS)
        except asyncio.CancelledError:
            break
        except Exception as exc:  # pragma: no cover
            logger.error("Cleanup error: %s", exc)


# ── Lifespan ──────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting ClipClean…")
    settings.ensure_directories()
    cleanup_task = asyncio.create_task(_periodic_cleanup())
    logger.info("Ready → http://%s:%s", settings.HOST, settings.PORT)
    yield
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    logger.info("ClipClean stopped.")


# ── App ───────────────────────────────────────────────────────────

app = FastAPI(
    title="ClipClean",
    description="Automatic Video Processing Tool",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api", tags=["health"])
app.include_router(jobs_router, prefix="/api", tags=["jobs"])


@app.exception_handler(Exception)
async def _global_handler(request: Request, exc: Exception):
    """Return a generic message; log the real traceback."""
    logger.error("Unhandled error on %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "An internal error occurred. Please try again."},
    )


# Static files — mount at /static and at / for root index
_static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static_assets")
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static_root")
