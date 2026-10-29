"""Audio helpers: extraction and validation via FFmpeg."""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from app.config import settings
from app.services.media_probe import probe_file

logger = logging.getLogger(__name__)


async def extract_audio(
    input_path: Path,
    output_path: Path,
    max_duration: Optional[float] = None,
) -> Path:
    """Extract audio from a video file to 16 kHz mono WAV.

    Suitable for speech-recognition input.
    """
    args = [
        settings.FFMPEG_PATH,
        "-y",
        "-i", str(input_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
    ]
    if max_duration:
        args.extend(["-t", str(max_duration)])
    args.append(str(output_path))

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except FileNotFoundError:
        raise RuntimeError("FFmpeg is not available")
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("Audio extraction timed out")

    if proc.returncode != 0:
        tail = stderr.decode(errors="replace")[-300:]
        raise RuntimeError(f"Audio extraction failed: {tail}")

    return output_path


async def validate_audio_file(file_path: Path) -> dict:
    """Probe an audio file and return basic metadata.

    Raises ``ValueError`` if the file is not valid audio.
    """
    try:
        info = await probe_file(file_path)
    except Exception as exc:
        raise ValueError(f"Invalid audio file: {exc}") from exc

    if not info.has_audio:
        raise ValueError("File does not contain an audio stream")

    stream = info.audio_stream
    return {
        "duration": info.duration,
        "codec": info.audio_codec,
        "sample_rate": stream.sample_rate if stream else None,
    }
