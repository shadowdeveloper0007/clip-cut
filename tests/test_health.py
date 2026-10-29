"""Tests for the /api/health endpoint."""

from unittest.mock import AsyncMock, patch


def test_health_returns_200(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert "ffmpeg_available" in body
    assert "version" in body


def test_health_reports_ffmpeg_missing(client):
    """When FFmpeg is missing, health should still return 200 but flag it."""
    with patch(
        "app.routes.health.check_ffmpeg_available",
        new_callable=AsyncMock,
        return_value=False,
    ):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["ffmpeg_available"] is False


def test_health_reports_ai_unavailable(client, monkeypatch):
    from app.services.ai_provider import ai_provider
    monkeypatch.setattr(ai_provider, "_api_key", "")
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ai_available"] is False
