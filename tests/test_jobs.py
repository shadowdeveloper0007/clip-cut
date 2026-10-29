"""Tests for job lifecycle: creation, polling, download, deletion."""

import io
import time
from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import FFMPEG_AVAILABLE, skip_without_ffmpeg


# ── Job not found ─────────────────────────────────────────────────


def test_get_nonexistent_job(client):
    r = client.get("/api/jobs/does_not_exist")
    assert r.status_code == 404


def test_download_nonexistent_job(client):
    r = client.get("/api/jobs/does_not_exist/download")
    assert r.status_code == 404


def test_delete_nonexistent_job(client):
    r = client.delete("/api/jobs/does_not_exist")
    assert r.status_code == 404


# ── Job creation (requires FFmpeg for the probe step) ────────────


@skip_without_ffmpeg
def test_create_job_returns_job_id(client, synthetic_video):
    """Uploading a valid video should create a job."""
    if synthetic_video is None:
        pytest.skip("Synthetic video generation failed")

    with open(synthetic_video, "rb") as f:
        r = client.post(
            "/api/jobs",
            files={"file": ("test.mp4", f, "video/mp4")},
        )
    assert r.status_code == 201
    body = r.json()
    assert "job_id" in body
    assert len(body["job_id"]) == 32  # uuid hex


@skip_without_ffmpeg
def test_poll_job_status(client, synthetic_video):
    """After creation the job should be poll-able."""
    if synthetic_video is None:
        pytest.skip("Synthetic video generation failed")

    with open(synthetic_video, "rb") as f:
        r = client.post(
            "/api/jobs",
            files={"file": ("test.mp4", f, "video/mp4")},
        )
    job_id = r.json()["job_id"]

    # Poll — status might still be processing or already done
    r2 = client.get(f"/api/jobs/{job_id}")
    assert r2.status_code == 200
    body = r2.json()
    assert body["job_id"] == job_id
    assert "status" in body


@skip_without_ffmpeg
def test_full_processing_cycle(client, synthetic_video):
    """Upload → process → poll until done → download."""
    if synthetic_video is None:
        pytest.skip("Synthetic video generation failed")

    with open(synthetic_video, "rb") as f:
        r = client.post(
            "/api/jobs",
            files={"file": ("cycle.mp4", f, "video/mp4")},
        )
    assert r.status_code == 201
    job_id = r.json()["job_id"]

    # Wait for completion (up to 30s)
    for _ in range(30):
        r2 = client.get(f"/api/jobs/{job_id}")
        status = r2.json()["status"]
        if status in ("completed", "failed"):
            break
        time.sleep(1)

    assert status == "completed", f"Job ended with status: {status}, error: {r2.json().get('error')}"

    body = r2.json()
    assert body["output_filename"]
    assert body["output_size"] and body["output_size"] > 0
    assert body["output_duration"] and body["output_duration"] > 0

    # Download
    r3 = client.get(f"/api/jobs/{job_id}/download")
    assert r3.status_code == 200
    assert len(r3.content) > 0
    assert r3.headers["content-type"] == "video/mp4"


def test_download_before_completion(client, monkeypatch):
    """Downloading a non-completed job should return 409."""
    from app.services.job_manager import job_manager, Job
    from app.schemas import JobStatus

    job = Job(
        job_id="testjob123",
        status=JobStatus.PROCESSING,
        created_at="2024-01-01T00:00:00+00:00",
    )
    with job_manager._lock:
        job_manager._jobs["testjob123"] = job

    r = client.get("/api/jobs/testjob123/download")
    assert r.status_code == 409
    assert "not complete" in r.json()["detail"].lower()


@skip_without_ffmpeg
def test_delete_completed_job(client, synthetic_video):
    """Deleting a completed job should clean up files."""
    if synthetic_video is None:
        pytest.skip("Synthetic video generation failed")

    with open(synthetic_video, "rb") as f:
        r = client.post(
            "/api/jobs",
            files={"file": ("del.mp4", f, "video/mp4")},
        )
    job_id = r.json()["job_id"]

    # Wait for completion
    for _ in range(30):
        r2 = client.get(f"/api/jobs/{job_id}")
        if r2.json()["status"] in ("completed", "failed"):
            break
        time.sleep(1)

    # Delete
    r3 = client.delete(f"/api/jobs/{job_id}")
    assert r3.status_code == 200

    # Should be gone
    r4 = client.get(f"/api/jobs/{job_id}")
    assert r4.status_code == 404


# ── FFmpeg unavailable ────────────────────────────────────────────


def test_create_job_without_ffmpeg(client, dummy_video_bytes):
    """When FFmpeg is missing, job creation should return 503."""
    with patch(
        "app.routes.jobs.check_ffmpeg_available",
        new_callable=AsyncMock,
        return_value=False,
    ):
        r = client.post(
            "/api/jobs",
            files={"file": ("v.mp4", io.BytesIO(dummy_video_bytes), "video/mp4")},
        )
    assert r.status_code == 503
    assert "FFmpeg" in r.json()["detail"]
