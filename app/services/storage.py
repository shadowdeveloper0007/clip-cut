"""Safe file-storage helpers: sanitisation, chunked writes, cleanup."""

import logging
import re
import time
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

# Accepted extensions ─────────────────────────────────────────────

ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".aac", ".ogg", ".flac", ".m4a"}


# Filename helpers ────────────────────────────────────────────────


def sanitize_filename(filename: str) -> str:
    """Return a filesystem-safe version of *filename*.

    * Strips directory components (path traversal).
    * Removes characters outside ``[a-zA-Z0-9_.-]``.
    * Truncates to 200 characters (preserving extension).
    """
    name = Path(filename).name
    name = re.sub(r"[^\w\-.]", "_", name)
    if not name or name.startswith("."):
        name = f"file_{name}"
    if len(name) > 200:
        ext = Path(name).suffix
        name = name[: 200 - len(ext)] + ext
    return name


def get_file_extension(filename: str) -> str:
    """Lowercase extension including the leading dot."""
    return Path(filename).suffix.lower()


def is_valid_video_extension(filename: str) -> bool:
    return get_file_extension(filename) in ALLOWED_VIDEO_EXTENSIONS


def is_valid_audio_extension(filename: str) -> bool:
    return get_file_extension(filename) in ALLOWED_AUDIO_EXTENSIONS


# File I/O ────────────────────────────────────────────────────────


async def save_upload_chunked(
    file,
    dest_path: Path,
    chunk_size: int = 65_536,
) -> int:
    """Stream an uploaded ``UploadFile`` to *dest_path*.

    Returns the total number of bytes written.  Never loads the whole
    file into memory.
    """
    total = 0
    with open(dest_path, "wb") as fp:
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            fp.write(chunk)
            total += len(chunk)
    return total


def generate_safe_path(
    directory: Path,
    original_filename: str,
    prefix: str = "",
) -> Path:
    """Build a unique, safe file path inside *directory*."""
    safe = sanitize_filename(original_filename)
    unique = f"{prefix}{uuid4().hex[:12]}_{safe}"
    return directory / unique


# Cleanup ─────────────────────────────────────────────────────────


def cleanup_file(path: Path) -> None:
    """Silently remove *path* if it exists."""
    try:
        if path and path.exists():
            path.unlink()
            logger.info("Cleaned up file: %s", path.name)
    except OSError as exc:
        logger.warning("Failed to clean up %s: %s", path, exc)


def cleanup_old_files(directory: Path, max_age_seconds: int) -> int:
    """Delete files in *directory* older than *max_age_seconds*.

    Returns the number of files removed.
    """
    if not directory.exists():
        return 0
    now = time.time()
    count = 0
    try:
        for item in directory.iterdir():
            if item.is_file():
                age = now - item.stat().st_mtime
                if age > max_age_seconds:
                    item.unlink()
                    count += 1
                    logger.info("Removed old file: %s (age %.0fs)", item.name, age)
    except OSError as exc:
        logger.warning("Cleanup error in %s: %s", directory, exc)
    return count
