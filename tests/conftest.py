"""Shared pytest fixtures for ClipClean tests."""

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _ffmpeg_available() -> bool:
    try:
        from app.config import settings
        bin_path = settings.FFMPEG_PATH
        r = subprocess.run(
            [bin_path, "-version"], capture_output=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


FFMPEG_AVAILABLE = _ffmpeg_available()

skip_without_ffmpeg = pytest.mark.skipif(
    not FFMPEG_AVAILABLE, reason="FFmpeg not available"
)


@pytest.fixture()
def temp_dirs(tmp_path):
    """Create the three runtime directories in a temp folder."""
    dirs = {
        "uploads": tmp_path / "uploads",
        "outputs": tmp_path / "outputs",
        "temp": tmp_path / "temp",
    }
    for d in dirs.values():
        d.mkdir()
    return dirs


@pytest.fixture()
def client(temp_dirs, monkeypatch):
    """FastAPI ``TestClient`` wired to temporary directories."""
    from app.config import settings

    monkeypatch.setattr(settings, "UPLOAD_DIR", temp_dirs["uploads"])
    monkeypatch.setattr(settings, "OUTPUT_DIR", temp_dirs["outputs"])
    monkeypatch.setattr(settings, "TEMP_DIR", temp_dirs["temp"])
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 10)  # keep tests fast
    monkeypatch.setattr(settings, "MAX_DURATION_SECONDS", 60)
    monkeypatch.setattr(settings, "CLEANUP_AGE_SECONDS", 3600)

    # Reset job manager state between tests
    from app.services.job_manager import job_manager
    job_manager._jobs.clear()
    job_manager._semaphore = None

    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc


@pytest.fixture()
def synthetic_video(tmp_path):
    """Generate a tiny 3-second test video with FFmpeg.

    Returns ``None`` when FFmpeg is not installed.
    """
    if not FFMPEG_AVAILABLE:
        return None
    from app.config import settings
    out = tmp_path / "test_input.mp4"
    subprocess.run(
        [
            settings.FFMPEG_PATH, "-y",
            "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=25",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
            "-c:v", "libx264", "-c:a", "aac", "-shortest",
            str(out),
        ],
        capture_output=True,
        timeout=30,
    )
    return out if out.exists() else None


@pytest.fixture()
def synthetic_audio(tmp_path):
    """Generate a tiny 3-second WAV file."""
    if not FFMPEG_AVAILABLE:
        return None
    from app.config import settings
    out = tmp_path / "test_audio.wav"
    subprocess.run(
        [
            settings.FFMPEG_PATH, "-y",
            "-f", "lavfi", "-i", "sine=frequency=880:duration=3",
            "-ar", "44100", "-ac", "2",
            str(out),
        ],
        capture_output=True,
        timeout=15,
    )
    return out if out.exists() else None


@pytest.fixture()
def dummy_video_bytes() -> bytes:
    """Return a tiny (invalid) byte string for extension / size tests."""
    return b"\x00" * 1024
