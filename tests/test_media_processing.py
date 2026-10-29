"""Tests for media-processing helpers and edge cases."""

import io
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import FFMPEG_AVAILABLE, skip_without_ffmpeg


# ── Time parsing ──────────────────────────────────────────────────


class TestTimeParsing:
    """Unit tests for video_processor.parse_time_to_seconds."""

    def _parse(self, val):
        from app.services.video_processor import parse_time_to_seconds
        return parse_time_to_seconds(val)

    def test_plain_seconds(self):
        assert self._parse("10") == 10.0
        assert self._parse("0") == 0.0
        assert self._parse("1.5") == 1.5

    def test_mm_ss(self):
        assert self._parse("1:30") == 90.0
        assert self._parse("0:05") == 5.0

    def test_hh_mm_ss(self):
        assert self._parse("1:00:00") == 3600.0
        assert self._parse("0:01:30") == 90.0

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="negative"):
            self._parse("-5")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            self._parse("")

    def test_garbage_raises(self):
        with pytest.raises(ValueError):
            self._parse("abc")


# ── MediaProbe ────────────────────────────────────────────────────


@skip_without_ffmpeg
class TestMediaProbe:

    @pytest.mark.asyncio
    async def test_probe_valid_video(self, synthetic_video):
        if synthetic_video is None:
            pytest.skip("No synthetic video")
        from app.services.media_probe import probe_file
        info = await probe_file(synthetic_video)
        assert info.has_video
        assert info.duration > 0
        assert info.width > 0

    @pytest.mark.asyncio
    async def test_probe_empty_file(self, tmp_path):
        empty = tmp_path / "empty.mp4"
        empty.write_bytes(b"")
        from app.services.media_probe import probe_file
        with pytest.raises(ValueError, match="empty"):
            await probe_file(empty)

    @pytest.mark.asyncio
    async def test_probe_missing_file(self, tmp_path):
        from app.services.media_probe import probe_file
        with pytest.raises(FileNotFoundError):
            await probe_file(tmp_path / "nope.mp4")

    @pytest.mark.asyncio
    async def test_probe_corrupt_file(self, tmp_path):
        corrupt = tmp_path / "corrupt.mp4"
        corrupt.write_bytes(b"\x00\x01\x02\x03" * 256)
        from app.services.media_probe import probe_file
        with pytest.raises(ValueError):
            await probe_file(corrupt)


# ── Duration limits ───────────────────────────────────────────────


@skip_without_ffmpeg
def test_duration_limit_enforced(client, synthetic_video, monkeypatch):
    """Videos exceeding MAX_DURATION_SECONDS should be rejected."""
    if synthetic_video is None:
        pytest.skip("No synthetic video")

    from app.config import settings
    monkeypatch.setattr(settings, "MAX_DURATION_SECONDS", 1)  # 1 second limit

    with open(synthetic_video, "rb") as f:
        r = client.post(
            "/api/jobs",
            files={"file": ("long.mp4", f, "video/mp4")},
        )
    job_id = r.json()["job_id"]

    # Wait for the job to fail
    for _ in range(15):
        r2 = client.get(f"/api/jobs/{job_id}")
        status = r2.json()["status"]
        if status in ("completed", "failed"):
            break
        time.sleep(0.5)

    assert status == "failed"
    assert "too long" in r2.json()["error"].lower()


# ── Invalid timestamps ────────────────────────────────────────────


@skip_without_ffmpeg
def test_invalid_trim_timestamps(client, synthetic_video):
    """Trim with start >= end should fail."""
    if synthetic_video is None:
        pytest.skip("No synthetic video")

    import json
    opts = json.dumps({"trim_start": "2", "trim_end": "1"})

    with open(synthetic_video, "rb") as f:
        r = client.post(
            "/api/jobs",
            files={"file": ("trim.mp4", f, "video/mp4")},
            data={"options": opts},
        )
    job_id = r.json()["job_id"]

    for _ in range(15):
        r2 = client.get(f"/api/jobs/{job_id}")
        if r2.json()["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)

    assert r2.json()["status"] == "failed"
    assert "before" in r2.json()["error"].lower()


@skip_without_ffmpeg
def test_split_video_into_parts(client, synthetic_video):
    """Splitting video into 2 parts should produce parts and downloadable zip."""
    if synthetic_video is None:
        pytest.skip("No synthetic video")

    import json
    opts = json.dumps({"split_parts": 2})

    with open(synthetic_video, "rb") as f:
        r = client.post(
            "/api/jobs",
            files={"file": ("split_test.mp4", f, "video/mp4")},
            data={"options": opts},
        )
    assert r.status_code == 201
    job_id = r.json()["job_id"]

    for _ in range(30):
        r2 = client.get(f"/api/jobs/{job_id}")
        if r2.json()["status"] in ("completed", "failed"):
            break
        time.sleep(1)

    assert r2.json()["status"] == "completed"
    body = r2.json()
    assert body["is_multi_part"] is True
    assert len(body["output_parts"]) == 2

    # Download zip
    r_zip = client.get(f"/api/jobs/{job_id}/download")
    assert r_zip.status_code == 200
    assert r_zip.headers["content-type"] == "application/zip"

    # Download individual part
    r_part1 = client.get(f"/api/jobs/{job_id}/download?part=1")
    assert r_part1.status_code == 200
    assert r_part1.headers["content-type"] == "video/mp4"


# ── Output validation ────────────────────────────────────────────


@skip_without_ffmpeg
def test_output_is_valid_mp4(client, synthetic_video):
    """The processed output should be a valid MP4 according to FFprobe."""
    if synthetic_video is None:
        pytest.skip("No synthetic video")

    with open(synthetic_video, "rb") as f:
        r = client.post(
            "/api/jobs",
            files={"file": ("out.mp4", f, "video/mp4")},
        )
    job_id = r.json()["job_id"]

    for _ in range(30):
        r2 = client.get(f"/api/jobs/{job_id}")
        status = r2.json()["status"]
        if status in ("completed", "failed"):
            break
        time.sleep(1)

    assert status == "completed"
    body = r2.json()
    assert body["output_filename"].endswith(".mp4")
    assert body["output_size"] > 0
    assert body["output_duration"] > 0


# ── Partial file cleanup ─────────────────────────────────────────


def test_cleanup_on_failure(client, tmp_path, monkeypatch):
    """On processing failure, partial output files should be removed."""
    from app.services.job_manager import job_manager, Job
    from app.schemas import JobStatus
    from app.config import settings

    # Create a fake partial output file
    fake_output = settings.OUTPUT_DIR / "partial_output.mp4"
    fake_output.write_bytes(b"partial data")

    job = Job(
        job_id="cleanup_test",
        status=JobStatus.FAILED,
        output_path=fake_output,
        created_at="2024-01-01T00:00:00+00:00",
    )
    with job_manager._lock:
        job_manager._jobs["cleanup_test"] = job

    # Cancel/delete should clean up
    r = client.delete("/api/jobs/cleanup_test")
    assert r.status_code == 200
    assert not fake_output.exists()


# ── Audio-only detection ─────────────────────────────────────────


@skip_without_ffmpeg
def test_audio_only_rejected(client, synthetic_audio):
    """An audio-only file uploaded as video should be rejected."""
    if synthetic_audio is None:
        pytest.skip("No synthetic audio")

    # Rename to .mp4 to bypass extension check
    import shutil
    mp4_path = synthetic_audio.parent / "audio_only.mp4"
    shutil.copy(synthetic_audio, mp4_path)

    with open(mp4_path, "rb") as f:
        r = client.post(
            "/api/jobs",
            files={"file": ("audio_only.mp4", f, "video/mp4")},
        )

    if r.status_code == 201:
        job_id = r.json()["job_id"]
        for _ in range(15):
            r2 = client.get(f"/api/jobs/{job_id}")
            if r2.json()["status"] in ("completed", "failed"):
                break
            time.sleep(0.5)
        assert r2.json()["status"] == "failed"
        assert "video stream" in r2.json()["error"].lower()


# ── Storage helpers ───────────────────────────────────────────────


class TestStorage:

    def test_sanitize_filename_strips_path(self):
        from app.services.storage import sanitize_filename
        assert "/" not in sanitize_filename("../../etc/passwd")
        assert "\\" not in sanitize_filename("..\\..\\windows\\system32")

    def test_sanitize_filename_removes_special_chars(self):
        from app.services.storage import sanitize_filename
        result = sanitize_filename("my video (1).mp4")
        assert "(" not in result
        assert result.endswith(".mp4")

    def test_is_valid_video_extension(self):
        from app.services.storage import is_valid_video_extension
        assert is_valid_video_extension("test.mp4")
        assert is_valid_video_extension("test.MOV")
        assert is_valid_video_extension("test.mkv")
        assert is_valid_video_extension("test.webm")
        assert not is_valid_video_extension("test.txt")
        assert not is_valid_video_extension("test.exe")
        assert not is_valid_video_extension("test")

    def test_cleanup_file_nonexistent(self, tmp_path):
        from app.services.storage import cleanup_file
        # Should not raise
        cleanup_file(tmp_path / "nonexistent.file")

    def test_cleanup_old_files(self, tmp_path):
        from app.services.storage import cleanup_old_files
        import time
        old = tmp_path / "old.txt"
        old.write_text("old")
        # Set mtime to 2 hours ago
        import os
        old_time = time.time() - 7200
        os.utime(old, (old_time, old_time))

        new = tmp_path / "new.txt"
        new.write_text("new")

        removed = cleanup_old_files(tmp_path, 3600)  # 1h threshold
        assert removed == 1
        assert not old.exists()
        assert new.exists()
