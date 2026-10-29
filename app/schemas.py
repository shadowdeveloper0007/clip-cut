"""Pydantic models for API requests and responses."""

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, model_validator


class JobStatus(str, Enum):
    """Processing job states."""

    PENDING = "pending"
    UPLOADING = "uploading"
    VALIDATING = "validating"
    ANALYZING = "analyzing"
    PROCESSING = "processing"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProcessingOptions(BaseModel):
    """Optional processing parameters for Mode B operations.

    All fields are optional. When none are provided the job runs in
    Mode A (basic processing / format normalisation).
    Accepts both flat keys and nested dictionaries (e.g. trim: {start, end}).
    """

    # Keep / extract a specific segment (e.g. 0 to 60s for 1-minute clip)
    clip_start: Optional[str] = None
    clip_end: Optional[str] = None

    # Split video into multiple parts (e.g. 2, 3, 4 parts or 60-second chunks)
    split_parts: Optional[int] = None
    split_duration: Optional[float] = None

    # Trim / remove a section (both required together)
    trim_start: Optional[str] = None  # "HH:MM:SS", "MM:SS", or seconds
    trim_end: Optional[str] = None

    # Replace audio track (filename of separately uploaded audio)
    replacement_audio_filename: Optional[str] = None

    # Mute an audio interval (both required together)
    mute_start: Optional[str] = None
    mute_end: Optional[str] = None

    # Subtitles — raw SRT content
    subtitle_srt: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_options(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Support nested dict formats e.g. {"trim": {"start": "...", "end": "..."}}
            trim = data.get("trim")
            if isinstance(trim, dict):
                data.setdefault("trim_start", trim.get("start"))
                data.setdefault("trim_end", trim.get("end"))

            mute = data.get("mute")
            if isinstance(mute, dict):
                data.setdefault("mute_start", mute.get("start"))
                data.setdefault("mute_end", mute.get("end"))

            if "subtitles" in data and "subtitle_srt" not in data:
                data["subtitle_srt"] = data["subtitles"]

        return data


# ── Response models ──────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str
    ffmpeg_available: bool
    ai_available: bool
    version: str


class JobCreateResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: Optional[float] = None  # 0–100, or null if indeterminate
    status_message: str
    error: Optional[str] = None
    input_filename: Optional[str] = None
    output_filename: Optional[str] = None
    output_duration: Optional[float] = None
    output_size: Optional[int] = None
    output_parts: Optional[list] = None
    is_multi_part: bool = False
    created_at: str


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
