"""Job endpoints: create, poll, download, and delete."""

import json
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.config import settings
from app.schemas import (
    JobCreateResponse,
    JobStatus,
    JobStatusResponse,
    ProcessingOptions,
)
from app.services.job_manager import job_manager
from app.services.media_probe import check_ffmpeg_available
from app.services.storage import (
    cleanup_file,
    generate_safe_path,
    is_valid_audio_extension,
    is_valid_video_extension,
    save_upload_chunked,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/jobs", response_model=JobCreateResponse, status_code=201)
async def create_job(
    file: UploadFile = File(...),
    options: str = Form("{}"),
    replacement_audio: UploadFile | None = File(None),
):
    """Upload a video file and start a processing job."""

    # ── file validation ───────────────────────────────────────────
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    if not is_valid_video_extension(file.filename):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Accepted formats: MP4, MOV, MKV, WebM",
        )

    # ── parse options ─────────────────────────────────────────────
    try:
        opts_dict = json.loads(options)
        processing_options = ProcessingOptions(**opts_dict)
    except (json.JSONDecodeError, Exception) as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid processing options: {exc}"
        )

    # ── replacement audio validation ──────────────────────────────
    if replacement_audio and replacement_audio.filename:
        if not is_valid_audio_extension(replacement_audio.filename):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Unsupported audio file type. "
                    "Accepted: MP3, WAV, AAC, OGG, FLAC, M4A"
                ),
            )

    # ── engine check ──────────────────────────────────────────────
    if not await check_ffmpeg_available():
        raise HTTPException(
            status_code=503,
            detail=(
                "Processing engine (FFmpeg) is not available. "
                "Please install FFmpeg."
            ),
        )

    # ── save upload ───────────────────────────────────────────────
    upload_path = generate_safe_path(settings.UPLOAD_DIR, file.filename)
    try:
        file_size = await save_upload_chunked(file, upload_path)
    except Exception as exc:
        cleanup_file(upload_path)
        logger.error("Upload save failed: %s", exc)
        raise HTTPException(
            status_code=500, detail="Failed to save uploaded file"
        )

    if file_size == 0:
        cleanup_file(upload_path)
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    if file_size > settings.MAX_UPLOAD_SIZE_BYTES:
        cleanup_file(upload_path)
        size_mb = file_size / 1024 / 1024
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large ({size_mb:.0f} MB). "
                f"Maximum allowed: {settings.MAX_UPLOAD_SIZE_MB} MB"
            ),
        )

    # ── optional replacement audio ────────────────────────────────
    replacement_audio_path = None
    if replacement_audio and replacement_audio.filename:
        if not is_valid_audio_extension(replacement_audio.filename):
            cleanup_file(upload_path)
            raise HTTPException(
                status_code=400,
                detail=(
                    "Unsupported audio file type. "
                    "Accepted: MP3, WAV, AAC, OGG, FLAC, M4A"
                ),
            )
        replacement_audio_path = generate_safe_path(
            settings.UPLOAD_DIR, replacement_audio.filename, prefix="audio_",
        )
        try:
            await save_upload_chunked(replacement_audio, replacement_audio_path)
        except Exception:
            cleanup_file(upload_path)
            cleanup_file(replacement_audio_path)
            raise HTTPException(
                status_code=500, detail="Failed to save replacement audio"
            )

    # ── create & launch job ───────────────────────────────────────
    job_id = job_manager.create_job(
        input_path=upload_path,
        input_filename=file.filename,
        options=processing_options,
        replacement_audio_path=replacement_audio_path,
    )
    await job_manager.start_processing(job_id)

    return JobCreateResponse(
        job_id=job_id,
        status=JobStatus.PENDING,
        message="Job created. Processing will begin shortly.",
    )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """Poll the status of a processing job."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        progress=job.progress,
        status_message=job.status_message,
        error=job.error,
        input_filename=job.input_filename,
        output_filename=job.output_filename,
        output_duration=job.output_duration,
        output_size=job.output_size,
        output_parts=getattr(job, "output_parts", None),
        is_multi_part=getattr(job, "is_multi_part", False),
        created_at=job.created_at,
    )


@router.get("/jobs/{job_id}/download")
async def download_result(job_id: str, part: int | None = None):
    """Stream the processed MP4 or ZIP archive to the client."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail=f"Job is not complete (current status: {job.status.value})",
        )

    # Allow downloading a specific part (e.g. Part 1, Part 2)
    if part is not None and getattr(job, "output_parts", None):
        target_part = next((p for p in job.output_parts if p.get("part") == part), None)
        if target_part:
            part_path = settings.OUTPUT_DIR / target_part["filename"]
            if part_path.exists():
                return FileResponse(
                    path=str(part_path),
                    filename=target_part["filename"],
                    media_type="video/mp4",
                )

    if not job.output_path or not job.output_path.exists():
        raise HTTPException(status_code=404, detail="Output file not found")

    media_type = (
        "application/zip"
        if str(job.output_path).lower().endswith(".zip")
        else "video/mp4"
    )

    return FileResponse(
        path=str(job.output_path),
        filename=job.output_filename or "processed_video.mp4",
        media_type=media_type,
    )


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    """Cancel a running job or remove a finished one."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    ok = await job_manager.cancel_job(job_id)
    if ok:
        return {"message": "Job cancelled and cleaned up", "job_id": job_id}
    raise HTTPException(status_code=500, detail="Failed to cancel job")
