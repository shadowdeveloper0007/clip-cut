"""FFmpeg-based video-processing operations.

Every function in this module accepts explicit file paths and a
:pydata:`ProgressCallback`.  None of them use ``shell=True``; all
FFmpeg arguments are passed as lists.
"""

import asyncio
import logging
import math
import re
import zipfile
from pathlib import Path
from typing import Awaitable, Callable, List, Optional, Tuple

from app.config import settings
from app.services.media_probe import MediaInfo

logger = logging.getLogger(__name__)

# callback(progress_pct | None, status_message)
ProgressCallback = Callable[[Optional[float], str], Awaitable[None]]


# ── Time parsing ──────────────────────────────────────────────────


def parse_time_to_seconds(time_str: str) -> float:
    """Convert ``HH:MM:SS``, ``MM:SS``, or bare seconds to a float.

    Raises :class:`ValueError` for invalid or negative values.
    """
    if not time_str or not time_str.strip():
        raise ValueError("Time value cannot be empty")
    time_str = time_str.strip()

    # Bare number (int or float)?
    val = None
    try:
        val = float(time_str)
    except ValueError:
        pass

    if val is not None:
        if val < 0:
            raise ValueError(f"Time cannot be negative: {time_str}")
        return val

    parts = time_str.split(":")
    try:
        if len(parts) == 2:
            m, s = int(parts[0]), float(parts[1])
            val = m * 60 + s
        elif len(parts) == 3:
            h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
            val = h * 3600 + m * 60 + s
        else:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError(
            f"Invalid time format: '{time_str}'. "
            "Use HH:MM:SS, MM:SS, or seconds."
        )

    if val < 0:
        raise ValueError(f"Time cannot be negative: {time_str}")
    return val


# ── FFmpeg runner ─────────────────────────────────────────────────


async def _run_ffmpeg(
    args: list,
    duration: float,
    progress_callback: Optional[ProgressCallback] = None,
    timeout: Optional[int] = None,
) -> None:
    """Execute an FFmpeg command and stream progress.

    *args* should **not** include the ``ffmpeg`` binary itself; it is
    prepended automatically.

    Raises :class:`RuntimeError` on failure.
    """
    if timeout is None:
        timeout = settings.JOB_TIMEOUT_SECONDS

    cmd = [settings.FFMPEG_PATH, *args]
    logger.info("FFmpeg command: %s", " ".join(str(a) for a in cmd))

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        raise RuntimeError("FFmpeg is not available. Please install FFmpeg.")

    try:
        stdout_data, stderr_data = await asyncio.wait_for(
            proc.communicate(), timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"FFmpeg timed out after {timeout} seconds")

    stderr_text = stderr_data.decode(errors="replace")

    # Best-effort progress from the last ``time=`` line in stderr
    if progress_callback and duration > 0:
        for line in stderr_text.splitlines():
            m = re.search(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", line)
            if m:
                h, mi, s = m.groups()
                current = int(h) * 3600 + int(mi) * 60 + float(s)
                pct = min(99.0, (current / duration) * 100)
                await progress_callback(pct, "Processing video…")

    if proc.returncode != 0:
        err_lines = [ln for ln in stderr_text.splitlines() if ln.strip()][-5:]
        error_msg = "\n".join(err_lines)
        logger.error("FFmpeg failed (exit %d): %s", proc.returncode, error_msg)
        raise RuntimeError(f"Video processing failed: {error_msg}")

    if progress_callback:
        await progress_callback(100.0, "Processing complete")


# ── Mode A: basic processing ─────────────────────────────────────


async def process_basic(
    input_path: Path,
    output_path: Path,
    media_info: MediaInfo,
    progress_callback: Optional[ProgressCallback] = None,
) -> None:
    """Format-normalise or stream-copy a video to H.264/AAC MP4."""
    if not media_info.has_video:
        raise ValueError(
            "File does not contain a video stream. "
            "Audio-only files are not supported."
        )

    if media_info.is_h264_aac_mp4 and input_path.suffix.lower() == ".mp4":
        # Fast path — stream copy
        args = [
            "-y", "-i", str(input_path),
            "-c", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ]
        if progress_callback:
            await progress_callback(None, "Stream copying (fast mode)…")
    else:
        args = [
            "-y", "-i", str(input_path),
            "-c:v", "libx264", "-crf", "23", "-preset", "medium",
            "-pix_fmt", "yuv420p",
        ]
        if media_info.has_audio:
            args += ["-c:a", "aac", "-b:a", "128k"]
        else:
            args.append("-an")
        args += ["-movflags", "+faststart", str(output_path)]

    await _run_ffmpeg(args, media_info.duration, progress_callback)


# ── Mode B helpers ────────────────────────────────────────────────


async def extract_clip(
    input_path: Path,
    output_path: Path,
    media_info: MediaInfo,
    clip_start_str: str,
    clip_end_str: str,
    progress_callback: Optional[ProgressCallback] = None,
) -> None:
    """Keep only the selected segment (e.g. 00:00 to 01:00 for a 1-minute clip)."""
    start = parse_time_to_seconds(clip_start_str)
    end = parse_time_to_seconds(clip_end_str)
    dur = media_info.duration

    if start >= end:
        raise ValueError(
            f"Clip start ({clip_start_str}) must be before clip end ({clip_end_str})"
        )
    if start >= dur:
        raise ValueError(
            f"Clip start ({clip_start_str}) is beyond video duration ({dur:.1f}s)"
        )

    clip_dur = min(end, dur) - start
    args = [
        "-y",
        "-ss", str(start),
        "-t", str(clip_dur),
        "-i", str(input_path),
        "-c:v", "libx264", "-crf", "23", "-preset", "medium",
        "-pix_fmt", "yuv420p",
    ]
    if media_info.has_audio:
        args += ["-c:a", "aac", "-b:a", "128k"]
    else:
        args.append("-an")
    args += ["-movflags", "+faststart", str(output_path)]

    await _run_ffmpeg(args, clip_dur, progress_callback)


async def split_video_into_parts(
    input_path: Path,
    output_dir: Path,
    base_name: str,
    media_info: MediaInfo,
    num_parts: Optional[int] = None,
    part_duration: Optional[float] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> Tuple[List[dict], Path]:
    """Split a video into multiple segments (e.g. 2-5 parts or 60s reels).

    Returns a list of part dictionaries and the path to the combined ZIP.
    """
    total_dur = media_info.duration
    intervals: List[Tuple[float, float]] = []

    if num_parts and num_parts >= 2:
        seg_dur = total_dur / num_parts
        for i in range(num_parts):
            start = i * seg_dur
            end = total_dur if i == num_parts - 1 else (i + 1) * seg_dur
            intervals.append((start, end))
    elif part_duration and part_duration > 0:
        count = math.ceil(total_dur / part_duration)
        for i in range(count):
            start = i * part_duration
            end = min(total_dur, (i + 1) * part_duration)
            if end - start > 0.5:  # ignore tiny leftovers
                intervals.append((start, end))
    else:
        raise ValueError("Must specify either valid num_parts (>= 2) or part_duration (> 0)")

    if not intervals:
        raise ValueError("Could not calculate split intervals for video")

    total_segments = len(intervals)
    results: List[dict] = []
    generated_files: List[Path] = []

    for idx, (start, end) in enumerate(intervals):
        seg_dur = end - start
        part_num = idx + 1
        part_name = f"{base_name}_Part_{part_num}.mp4"
        part_path = output_dir / part_name
        generated_files.append(part_path)

        if progress_callback:
            pct = round((idx / total_segments) * 90.0, 1)
            await progress_callback(
                pct, f"Exporting Part {part_num} of {total_segments} ({seg_dur:.0f}s)…"
            )

        args = [
            "-y",
            "-ss", str(start),
            "-t", str(seg_dur),
            "-i", str(input_path),
            "-c:v", "libx264", "-crf", "23", "-preset", "medium",
            "-pix_fmt", "yuv420p",
        ]
        if media_info.has_audio:
            args += ["-c:a", "aac", "-b:a", "128k"]
        else:
            args.append("-an")
        args += ["-movflags", "+faststart", str(part_path)]

        await _run_ffmpeg(args, seg_dur, None)

        file_size = part_path.stat().st_size if part_path.exists() else 0
        results.append({
            "part": part_num,
            "filename": part_name,
            "duration": round(seg_dur, 1),
            "size": file_size,
        })

    # Create a combined zip file containing all parts
    zip_name = f"{base_name}_All_Parts.zip"
    zip_path = output_dir / zip_name
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in generated_files:
            if f.exists():
                zf.write(f, arcname=f.name)

    if progress_callback:
        await progress_callback(100.0, f"Split into {total_segments} parts complete!")

    return results, zip_path


async def trim_section(
    input_path: Path,
    output_path: Path,
    media_info: MediaInfo,
    trim_start_str: str,
    trim_end_str: str,
    progress_callback: Optional[ProgressCallback] = None,
) -> None:
    """Remove the segment between *trim_start* and *trim_end*."""
    start = parse_time_to_seconds(trim_start_str)
    end = parse_time_to_seconds(trim_end_str)
    dur = media_info.duration

    if start >= end:
        raise ValueError(
            f"Trim start ({trim_start_str}) must be before "
            f"trim end ({trim_end_str})"
        )
    if start >= dur:
        raise ValueError(
            f"Trim start ({trim_start_str}) is beyond video "
            f"duration ({dur:.1f}s)"
        )
    if end > dur + 0.5:
        raise ValueError(
            f"Trim end ({trim_end_str}) is beyond video "
            f"duration ({dur:.1f}s)"
        )

    has_audio = media_info.has_audio
    parts, concat_in, idx = [], [], 0

    if start > 0.1:
        parts.append(
            f"[0:v]trim=start=0:end={start},setpts=PTS-STARTPTS[v{idx}]"
        )
        if has_audio:
            parts.append(
                f"[0:a]atrim=start=0:end={start},asetpts=PTS-STARTPTS[a{idx}]"
            )
            concat_in.append(f"[v{idx}][a{idx}]")
        else:
            concat_in.append(f"[v{idx}]")
        idx += 1

    if end < dur - 0.1:
        parts.append(
            f"[0:v]trim=start={end},setpts=PTS-STARTPTS[v{idx}]"
        )
        if has_audio:
            parts.append(
                f"[0:a]atrim=start={end},asetpts=PTS-STARTPTS[a{idx}]"
            )
            concat_in.append(f"[v{idx}][a{idx}]")
        else:
            concat_in.append(f"[v{idx}]")
        idx += 1

    if not concat_in:
        raise ValueError("Trimming would remove the entire video")

    cat = "".join(concat_in)
    if has_audio:
        parts.append(f"{cat}concat=n={idx}:v=1:a=1[outv][outa]")
    else:
        parts.append(f"{cat}concat=n={idx}:v=1:a=0[outv]")

    fc = ";".join(parts)
    args = ["-y", "-i", str(input_path), "-filter_complex", fc, "-map", "[outv]"]
    if has_audio:
        args += ["-map", "[outa]"]
    args += [
        "-c:v", "libx264", "-crf", "23", "-preset", "medium",
        "-pix_fmt", "yuv420p",
    ]
    if has_audio:
        args += ["-c:a", "aac", "-b:a", "128k"]
    args += ["-movflags", "+faststart", str(output_path)]

    expected = dur - (end - start)
    await _run_ffmpeg(args, expected, progress_callback)


async def replace_audio(
    input_path: Path,
    audio_path: Path,
    output_path: Path,
    media_info: MediaInfo,
    progress_callback: Optional[ProgressCallback] = None,
) -> None:
    """Replace the audio track with *audio_path*."""
    if not audio_path.exists():
        raise FileNotFoundError("Replacement audio file not found")

    args = [
        "-y",
        "-i", str(input_path),
        "-i", str(audio_path),
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        "-movflags", "+faststart",
        str(output_path),
    ]
    await _run_ffmpeg(args, media_info.duration, progress_callback)


async def mute_interval(
    input_path: Path,
    output_path: Path,
    media_info: MediaInfo,
    mute_start_str: str,
    mute_end_str: str,
    progress_callback: Optional[ProgressCallback] = None,
) -> None:
    """Mute audio between *mute_start* and *mute_end*."""
    ms = parse_time_to_seconds(mute_start_str)
    me = parse_time_to_seconds(mute_end_str)
    dur = media_info.duration

    if ms >= me:
        raise ValueError(
            f"Mute start ({mute_start_str}) must be before "
            f"mute end ({mute_end_str})"
        )
    if ms >= dur:
        raise ValueError(f"Mute start is beyond video duration ({dur:.1f}s)")
    if not media_info.has_audio:
        raise ValueError("Video has no audio stream to mute")

    af = f"volume=enable='between(t,{ms},{me})':volume=0"
    args = [
        "-y", "-i", str(input_path),
        "-c:v", "copy",
        "-af", af,
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_path),
    ]
    await _run_ffmpeg(args, dur, progress_callback)


async def add_subtitles(
    input_path: Path,
    srt_path: Path,
    output_path: Path,
    media_info: MediaInfo,
    progress_callback: Optional[ProgressCallback] = None,
) -> None:
    """Burn SRT subtitles into the video."""
    if not srt_path.exists():
        raise FileNotFoundError("Subtitle file not found")

    # Escape the path for the FFmpeg subtitles filter
    escaped = str(srt_path).replace("\\", "/").replace(":", "\\\\:")

    args = [
        "-y", "-i", str(input_path),
        "-vf", f"subtitles='{escaped}'",
        "-c:v", "libx264", "-crf", "23", "-preset", "medium",
        "-pix_fmt", "yuv420p",
    ]
    if media_info.has_audio:
        args += ["-c:a", "aac", "-b:a", "128k"]
    args += ["-movflags", "+faststart", str(output_path)]

    await _run_ffmpeg(args, media_info.duration, progress_callback)
