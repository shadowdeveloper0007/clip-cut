"""Tests for upload validation — extensions, size, and empty files."""

import io
from unittest.mock import AsyncMock, patch


def test_reject_unsupported_extension(client, dummy_video_bytes):
    """Files with non-video extensions should be rejected."""
    r = client.post(
        "/api/jobs",
        files={"file": ("test.txt", io.BytesIO(dummy_video_bytes), "text/plain")},
    )
    assert r.status_code == 400
    assert "Unsupported" in r.json()["detail"]


def test_reject_exe_extension(client, dummy_video_bytes):
    r = client.post(
        "/api/jobs",
        files={"file": ("malware.exe", io.BytesIO(dummy_video_bytes), "application/octet-stream")},
    )
    assert r.status_code == 400


def test_reject_empty_file(client):
    """An empty upload should be rejected with 400."""
    with patch("app.routes.jobs.check_ffmpeg_available", new_callable=AsyncMock, return_value=True):
        r = client.post(
            "/api/jobs",
            files={"file": ("empty.mp4", io.BytesIO(b""), "video/mp4")},
        )
    assert r.status_code == 400
    assert "empty" in r.json()["detail"].lower()


def test_reject_no_filename(client):
    r = client.post(
        "/api/jobs",
        files={"file": ("", io.BytesIO(b"\x00"), "video/mp4")},
    )
    assert r.status_code in (400, 422)


def test_reject_oversized_file(client, monkeypatch):
    """Files exceeding MAX_UPLOAD_SIZE_MB should be rejected."""
    from app.config import settings
    # Set a very small limit so we can test easily
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 0)  # 0 MB = reject everything

    data = b"\x00" * 1024  # 1 KB > 0 MB
    with patch("app.routes.jobs.check_ffmpeg_available", new_callable=AsyncMock, return_value=True):
        r = client.post(
            "/api/jobs",
            files={"file": ("big.mp4", io.BytesIO(data), "video/mp4")},
        )
    assert r.status_code == 413
    assert "too large" in r.json()["detail"].lower()


def test_accept_valid_extensions(client):
    """All accepted extensions should pass the extension check.

    They'll still fail at FFmpeg probe (503 if FFmpeg missing, or
    media-validation error), but shouldn't fail the extension check.
    """
    for ext in ("mp4", "mov", "mkv", "webm"):
        r = client.post(
            "/api/jobs",
            files={
                "file": (
                    f"video.{ext}",
                    io.BytesIO(b"\x00" * 512),
                    "video/mp4",
                )
            },
        )
        # Should NOT be 400-"Unsupported"
        if r.status_code == 400:
            assert "Unsupported" not in r.json().get("detail", "")


def test_reject_invalid_options_json(client, dummy_video_bytes):
    r = client.post(
        "/api/jobs",
        files={"file": ("v.mp4", io.BytesIO(dummy_video_bytes), "video/mp4")},
        data={"options": "NOT JSON"},
    )
    assert r.status_code == 400
    assert "options" in r.json()["detail"].lower()


def test_reject_invalid_audio_extension(client, dummy_video_bytes):
    r = client.post(
        "/api/jobs",
        files={
            "file": ("v.mp4", io.BytesIO(dummy_video_bytes), "video/mp4"),
            "replacement_audio": ("song.exe", io.BytesIO(b"\x00" * 100), "application/octet-stream"),
        },
    )
    assert r.status_code == 400
    assert "audio" in r.json()["detail"].lower()
