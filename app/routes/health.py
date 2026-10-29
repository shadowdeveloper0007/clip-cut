"""Health-check endpoint."""

from fastapi import APIRouter

from app.schemas import HealthResponse
from app.services.ai_provider import ai_provider
from app.services.media_probe import check_ffmpeg_available

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Return application health status and engine availability."""
    ffmpeg_ok = await check_ffmpeg_available()
    return HealthResponse(
        status="healthy",
        ffmpeg_available=ffmpeg_ok,
        ai_available=ai_provider.available,
        version="1.0.0",
    )
