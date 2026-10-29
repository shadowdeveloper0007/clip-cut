"""Optional AI provider for speech transcription (Groq Whisper free tier).

All AI features are disabled gracefully when no API key is configured.
The application never depends on this module for core processing.
"""

import logging
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class AIProvider:
    """Thin wrapper around the Groq Whisper transcription API."""

    def __init__(self) -> None:
        self._api_key: str = settings.GROQ_API_KEY
        self._model: str = settings.GROQ_MODEL
        self._base_url: str = "https://api.groq.com/openai/v1"
        self._max_file_size: int = 25 * 1024 * 1024  # 25 MB

    # ── Status ────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        """``True`` when an API key has been configured."""
        return bool(self._api_key)

    def status_message(self) -> str:
        if self.available:
            return "AI transcription available (Groq Whisper)"
        return "AI features unavailable — no API key configured"

    # ── Transcription ─────────────────────────────────────────────

    async def transcribe_audio(
        self,
        audio_path: Path,
        language: Optional[str] = None,
    ) -> Optional[dict]:
        """Transcribe *audio_path* via Groq's Whisper endpoint.

        Returns ``None`` when AI is unavailable.

        Raises
        ------
        RuntimeError
            On API / network errors.
        ValueError
            When the audio file exceeds the provider size limit.
        """
        if not self.available:
            return None

        if not audio_path.exists():
            raise FileNotFoundError("Audio file not found")

        file_size = audio_path.stat().st_size
        if file_size > self._max_file_size:
            raise ValueError(
                f"Audio file too large for transcription "
                f"({file_size / 1024 / 1024:.1f} MB, "
                f"max {self._max_file_size / 1024 / 1024:.0f} MB)"
            )

        try:
            import httpx  # noqa: delay import
        except ImportError:
            logger.warning("httpx not installed — AI features disabled")
            return None

        url = f"{self._base_url}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self._api_key}"}

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                with open(audio_path, "rb") as fh:
                    files = {"file": (audio_path.name, fh, "audio/wav")}
                    data: dict = {
                        "model": self._model,
                        "response_format": "verbose_json",
                    }
                    if language:
                        data["language"] = language

                    response = await client.post(
                        url, headers=headers, files=files, data=data,
                    )

            if response.status_code == 429:
                raise RuntimeError(
                    "AI service rate limit exceeded. Please try again later."
                )
            if response.status_code == 401:
                raise RuntimeError(
                    "AI service authentication failed. Check your GROQ_API_KEY."
                )
            if response.status_code >= 400:
                raise RuntimeError(
                    f"AI service error (HTTP {response.status_code})"
                )

            result = response.json()
            return {
                "text": result.get("text", ""),
                "segments": result.get("segments", []),
                "language": result.get("language"),
                "duration": result.get("duration"),
            }

        except httpx.TimeoutException:
            raise RuntimeError("AI service request timed out")
        except httpx.RequestError as exc:
            raise RuntimeError(f"Could not connect to AI service: {exc}")


# Module-level singleton
ai_provider = AIProvider()
