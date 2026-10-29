"""FFprobe wrapper for safe media-file inspection."""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from app.config import settings

logger = logging.getLogger(__name__)


# ── Data classes ─────────────────────────────────────────────────


@dataclass
class StreamInfo:
    """A single audio or video stream inside a media container."""

    index: int
    codec_type: str  # "video" | "audio"
    codec_name: str
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None
    bit_rate: Optional[int] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None


@dataclass
class MediaInfo:
    """Aggregate information returned by :func:`probe_file`."""

    duration: float  # seconds
    format_name: str
    size: int  # bytes
    bit_rate: Optional[int] = None
    streams: List[StreamInfo] = field(default_factory=list)

    # Convenience helpers ──────────────────────────────────────────

    @property
    def has_video(self) -> bool:
        return any(s.codec_type == "video" for s in self.streams)

    @property
    def has_audio(self) -> bool:
        return any(s.codec_type == "audio" for s in self.streams)

    @property
    def video_stream(self) -> Optional[StreamInfo]:
        return next((s for s in self.streams if s.codec_type == "video"), None)

    @property
    def audio_stream(self) -> Optional[StreamInfo]:
        return next((s for s in self.streams if s.codec_type == "audio"), None)

    @property
    def video_codec(self) -> Optional[str]:
        vs = self.video_stream
        return vs.codec_name if vs else None

    @property
    def audio_codec(self) -> Optional[str]:
        a = self.audio_stream
        return a.codec_name if a else None

    @property
    def width(self) -> Optional[int]:
        vs = self.video_stream
        return vs.width if vs else None

    @property
    def height(self) -> Optional[int]:
        vs = self.video_stream
        return vs.height if vs else None

    @property
    def is_h264_aac_mp4(self) -> bool:
        """``True`` when the file is already in the target format."""
        return (
            self.video_codec in ("h264", "H264")
            and self.audio_codec in ("aac", "AAC", None)
            and bool(self.format_name and "mp4" in self.format_name.lower())
        )


# ── FFprobe availability ─────────────────────────────────────────


def check_ffmpeg_available_sync() -> bool:
    """Synchronous check if both ffmpeg and ffprobe binaries exist and run."""
    import shutil
    import subprocess

    for binary in (settings.FFPROBE_PATH, settings.FFMPEG_PATH):
        # First verify binary is resolvable on PATH or absolute path
        resolved = shutil.which(binary)
        if not resolved and not Path(binary).is_file():
            return False
        try:
            target = resolved or binary
            res = subprocess.run(
                [target, "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )
            if res.returncode != 0:
                return False
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return False
    return True


async def check_ffmpeg_available() -> bool:
    """Return ``True`` if both *ffmpeg* and *ffprobe* can be executed."""
    return check_ffmpeg_available_sync()


# ── Probe ─────────────────────────────────────────────────────────


async def probe_file(file_path: Path) -> MediaInfo:
    """Run *ffprobe* on *file_path* and return a :class:`MediaInfo`.

    Raises
    ------
    FileNotFoundError
        The file does not exist.
    ValueError
        The file is empty, corrupt, or not a recognised media file.
    RuntimeError
        FFprobe itself is missing or timed out.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path.name}")
    if file_path.stat().st_size == 0:
        raise ValueError("File is empty")

    cmd = [
        settings.FFPROBE_PATH,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(file_path),
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    except FileNotFoundError:
        raise RuntimeError(
            "FFprobe is not available. Install FFmpeg and make sure "
            "ffprobe is on your system PATH."
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("FFprobe timed out while analysing the file")

    if proc.returncode != 0:
        logger.error("FFprobe error: %s", stderr.decode(errors="replace").strip())
        raise ValueError(
            "Could not analyse the file. It may be corrupt or not a valid media file."
        )

    try:
        data = json.loads(stdout.decode(errors="replace"))
    except json.JSONDecodeError:
        raise ValueError("Failed to parse media-file information")

    # ── Format ────────────────────────────────────────────────────
    fmt = data.get("format", {})
    duration_str = fmt.get("duration")
    if not duration_str:
        raise ValueError(
            "Could not determine file duration. The file may not be a valid media file."
        )

    try:
        duration = float(duration_str)
    except (ValueError, TypeError):
        raise ValueError("Could not determine file duration")

    size = int(fmt.get("size", 0))
    format_name = fmt.get("format_name", "unknown")
    bit_rate_raw = fmt.get("bit_rate")
    bit_rate = int(bit_rate_raw) if bit_rate_raw else None

    # ── Streams ───────────────────────────────────────────────────
    streams: List[StreamInfo] = []
    for s in data.get("streams", []):
        codec_type = s.get("codec_type", "")
        if codec_type not in ("video", "audio"):
            continue
        streams.append(
            StreamInfo(
                index=s.get("index", 0),
                codec_type=codec_type,
                codec_name=s.get("codec_name", "unknown"),
                width=s.get("width"),
                height=s.get("height"),
                duration=float(s["duration"]) if s.get("duration") else None,
                bit_rate=int(s["bit_rate"]) if s.get("bit_rate") else None,
                sample_rate=int(s["sample_rate"]) if s.get("sample_rate") else None,
                channels=s.get("channels"),
            )
        )

    if not streams:
        raise ValueError("No video or audio streams found in the file")

    return MediaInfo(
        duration=duration,
        format_name=format_name,
        size=size,
        bit_rate=bit_rate,
        streams=streams,
    )
