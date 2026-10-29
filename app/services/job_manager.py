"""Job lifecycle manager — create, track, and run processing jobs."""

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional
from uuid import uuid4

from app.config import settings
from app.schemas import JobStatus, ProcessingOptions
from app.services import media_probe, storage
from app.services.video_processor import (
    add_subtitles,
    extract_clip,
    mute_interval,
    process_basic,
    replace_audio,
    split_video_into_parts,
    trim_section,
)

logger = logging.getLogger(__name__)


@dataclass
class Job:
    """Internal representation of a processing job."""

    job_id: str
    status: JobStatus = JobStatus.PENDING
    progress: Optional[float] = None
    status_message: str = "Pending"
    error: Optional[str] = None

    input_filename: str = ""
    input_path: Optional[Path] = None

    output_path: Optional[Path] = None
    output_filename: Optional[str] = None
    output_duration: Optional[float] = None
    output_size: Optional[int] = None
    output_parts: list = field(default_factory=list)
    is_multi_part: bool = False
    zip_output_path: Optional[Path] = None

    options: ProcessingOptions = field(default_factory=ProcessingOptions)
    replacement_audio_path: Optional[Path] = None

    created_at: str = ""

    # internal — not serialised
    _task: Optional[asyncio.Task] = field(default=None, repr=False)


class JobManager:
    """In-memory, thread-safe job store with background processing."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()
        self._semaphore: Optional[asyncio.Semaphore] = None

    # ── helpers ───────────────────────────────────────────────────

    def _sem(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_JOBS)
        return self._semaphore

    def _update(self, job_id: str, **kw) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                for k, v in kw.items():
                    if hasattr(job, k):
                        setattr(job, k, v)

    @staticmethod
    def _cleanup_files(job: Job) -> None:
        if job.input_path:
            storage.cleanup_file(job.input_path)
        if job.output_path:
            storage.cleanup_file(job.output_path)
        if job.zip_output_path and job.zip_output_path != job.output_path:
            storage.cleanup_file(job.zip_output_path)
        for part in getattr(job, "output_parts", []):
            if isinstance(part, dict) and "filename" in part:
                storage.cleanup_file(settings.OUTPUT_DIR / part["filename"])
        if job.replacement_audio_path:
            storage.cleanup_file(job.replacement_audio_path)

    # ── public API ────────────────────────────────────────────────

    def create_job(
        self,
        input_path: Path,
        input_filename: str,
        options: ProcessingOptions,
        replacement_audio_path: Optional[Path] = None,
    ) -> str:
        job_id = uuid4().hex
        job = Job(
            job_id=job_id,
            input_filename=input_filename,
            input_path=input_path,
            options=options,
            replacement_audio_path=replacement_audio_path,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with self._lock:
            self._jobs[job_id] = job
        return job_id

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    async def start_processing(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        if job.status != JobStatus.PENDING:
            raise ValueError(f"Job {job_id} has already been started")
        task = asyncio.create_task(self._process(job_id))
        with self._lock:
            job._task = task

    async def cancel_job(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        if not job:
            return False

        # Kill running task
        if job._task and not job._task.done():
            job._task.cancel()

        terminal = (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
        if job.status not in terminal:
            self._update(
                job_id,
                status=JobStatus.CANCELLED,
                status_message="Cancelled by user",
            )

        self._cleanup_files(job)
        with self._lock:
            self._jobs.pop(job_id, None)
        return True

    # ── background pipeline ───────────────────────────────────────

    async def _progress_cb(
        self, job_id: str, pct: Optional[float], msg: str,
    ) -> None:
        kw: dict = {"status_message": msg}
        if pct is not None:
            kw["progress"] = round(pct, 1)
        self._update(job_id, **kw)

    async def _process(self, job_id: str) -> None:  # noqa: C901 (pipeline)
        job = self.get_job(job_id)
        if not job:
            return

        sem = self._sem()
        await sem.acquire()
        try:
            await self._run_pipeline(job_id, job)
        except asyncio.CancelledError:
            self._update(
                job_id,
                status=JobStatus.CANCELLED,
                status_message="Processing was cancelled",
            )
            cur = self.get_job(job_id)
            if cur and cur.output_path:
                storage.cleanup_file(cur.output_path)
            logger.info("Job %s cancelled", job_id)
        except Exception as exc:
            logger.error("Job %s failed: %s", job_id, exc, exc_info=True)
            self._update(
                job_id,
                status=JobStatus.FAILED,
                status_message="Processing failed",
                error=str(exc),
                progress=None,
            )
            cur = self.get_job(job_id)
            if cur and cur.output_path:
                storage.cleanup_file(cur.output_path)
        finally:
            sem.release()

    async def _run_pipeline(self, job_id: str, job: Job) -> None:
        """Step-by-step processing pipeline."""

        # 1 ── validate ────────────────────────────────────────────
        self._update(
            job_id,
            status=JobStatus.VALIDATING,
            status_message="Validating video file…",
            progress=None,
        )
        if not job.input_path or not job.input_path.exists():
            raise FileNotFoundError("Input file not found")

        # 2 ── analyse ─────────────────────────────────────────────
        self._update(
            job_id,
            status=JobStatus.ANALYZING,
            status_message="Analysing media…",
        )
        try:
            info = await media_probe.probe_file(job.input_path)
        except Exception as exc:
            raise ValueError(f"Media analysis failed: {exc}") from exc

        if not info.has_video:
            raise ValueError(
                "File does not contain a video stream. "
                "Audio-only files are not supported for video processing."
            )
        if info.duration < settings.MIN_DURATION_SECONDS:
            raise ValueError(
                f"Video is too short ({info.duration:.1f}s). "
                f"Minimum duration is {settings.MIN_DURATION_SECONDS}s."
            )
        if info.duration > settings.MAX_DURATION_SECONDS:
            raise ValueError(
                f"Video is too long ({info.duration:.1f}s). "
                f"Maximum duration is {settings.MAX_DURATION_SECONDS}s "
                f"({settings.MAX_DURATION_SECONDS // 60} minutes)."
            )

        # 3 ── process ─────────────────────────────────────────────
        self._update(
            job_id,
            status=JobStatus.PROCESSING,
            status_message="Processing video…",
            progress=0,
        )

        out_name = (
            f"clipclean_{job.job_id[:8]}_"
            f"{storage.sanitize_filename(job.input_filename)}"
        )
        if not out_name.lower().endswith(".mp4"):
            out_name = Path(out_name).stem + ".mp4"
        output_path = settings.OUTPUT_DIR / out_name
        self._update(job_id, output_path=output_path)

        opts = job.options

        async def pcb(pct, msg):
            await self._progress_cb(job_id, pct, msg)

        if opts.split_parts or opts.split_duration:
            base_part_name = f"clipclean_{job.job_id[:8]}"
            parts_info, zip_path = await split_video_into_parts(
                job.input_path,
                settings.OUTPUT_DIR,
                base_part_name,
                info,
                num_parts=opts.split_parts,
                part_duration=opts.split_duration,
                progress_callback=pcb,
            )
            self._update(
                job_id,
                status=JobStatus.COMPLETED,
                status_message=f"Successfully split into {len(parts_info)} parts!",
                progress=100,
                output_path=zip_path,
                output_filename=zip_path.name,
                output_duration=info.duration,
                output_size=zip_path.stat().st_size if zip_path.exists() else 0,
                output_parts=parts_info,
                is_multi_part=True,
                zip_output_path=zip_path,
            )
            logger.info("Job %s completed: %d parts created", job_id, len(parts_info))
            return

        if opts.clip_start and opts.clip_end:
            await extract_clip(
                job.input_path, output_path, info,
                opts.clip_start, opts.clip_end, pcb,
            )
        elif opts.trim_start and opts.trim_end:
            await trim_section(
                job.input_path, output_path, info,
                opts.trim_start, opts.trim_end, pcb,
            )
        elif opts.replacement_audio_filename and job.replacement_audio_path:
            await replace_audio(
                job.input_path, job.replacement_audio_path,
                output_path, info, pcb,
            )
        elif opts.mute_start and opts.mute_end:
            await mute_interval(
                job.input_path, output_path, info,
                opts.mute_start, opts.mute_end, pcb,
            )
        elif opts.subtitle_srt:
            srt_path = settings.TEMP_DIR / f"{job.job_id}_subs.srt"
            srt_path.write_text(opts.subtitle_srt, encoding="utf-8")
            try:
                await add_subtitles(
                    job.input_path, srt_path, output_path, info, pcb,
                )
            finally:
                storage.cleanup_file(srt_path)
        else:
            await process_basic(job.input_path, output_path, info, pcb)

        # 4 ── finalise ────────────────────────────────────────────
        self._update(
            job_id,
            status=JobStatus.FINALIZING,
            status_message="Validating output…",
            progress=None,
        )

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError("Processing produced no output file")

        try:
            out_info = await media_probe.probe_file(output_path)
        except Exception as exc:
            storage.cleanup_file(output_path)
            raise RuntimeError(f"Output validation failed: {exc}") from exc

        if not out_info.has_video:
            storage.cleanup_file(output_path)
            raise RuntimeError(
                "Output file does not contain a valid video stream"
            )

        # 5 ── done ────────────────────────────────────────────────
        self._update(
            job_id,
            status=JobStatus.COMPLETED,
            status_message="Processing complete! Your video is ready.",
            progress=100,
            output_path=output_path,
            output_filename=out_name,
            output_duration=out_info.duration,
            output_size=output_path.stat().st_size,
        )
        logger.info("Job %s completed: %s", job_id, out_name)

    # ── periodic cleanup ──────────────────────────────────────────

    async def cleanup_old_jobs(self) -> None:
        """Remove finished jobs older than ``CLEANUP_AGE_SECONDS``."""
        now = time.time()
        stale: list[str] = []
        terminal = (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
        with self._lock:
            for jid, job in self._jobs.items():
                if job.status in terminal:
                    try:
                        created = datetime.fromisoformat(
                            job.created_at
                        ).timestamp()
                        if now - created > settings.CLEANUP_AGE_SECONDS:
                            stale.append(jid)
                    except (ValueError, TypeError):
                        pass
        for jid in stale:
            await self.cancel_job(jid)
            logger.info("Cleaned up stale job %s", jid)


# Module-level singleton
job_manager = JobManager()
