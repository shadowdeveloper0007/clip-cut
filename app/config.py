"""Application configuration loaded from environment variables and .env file."""

from pathlib import Path
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """ClipClean application settings."""

    # Server
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # Paths — BASE_DIR defaults to the project root (parent of app/)
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Optional[Path] = None
    UPLOAD_DIR: Optional[Path] = None
    OUTPUT_DIR: Optional[Path] = None
    TEMP_DIR: Optional[Path] = None

    # Limits
    MAX_UPLOAD_SIZE_MB: int = 1024  # 1 GB
    MAX_DURATION_SECONDS: int = 1800  # 30 minutes
    MIN_DURATION_SECONDS: int = 1
    MAX_CONCURRENT_JOBS: int = 2
    JOB_TIMEOUT_SECONDS: int = 3600  # 1 hour
    CLEANUP_AGE_SECONDS: int = 3600  # 1 hour

    # FFmpeg
    FFMPEG_PATH: str = "ffmpeg"
    FFPROBE_PATH: str = "ffprobe"

    # Optional AI (Groq)
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "whisper-large-v3"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @model_validator(mode="after")
    def _set_derived_paths(self) -> "Settings":
        """Compute data directory paths from BASE_DIR if not set explicitly."""
        if self.DATA_DIR is None:
            self.DATA_DIR = self.BASE_DIR / "data"
        if self.UPLOAD_DIR is None:
            self.UPLOAD_DIR = self.DATA_DIR / "uploads"
        if self.OUTPUT_DIR is None:
            self.OUTPUT_DIR = self.DATA_DIR / "outputs"
        if self.TEMP_DIR is None:
            self.TEMP_DIR = self.DATA_DIR / "temp"

        # Auto-detect local ffmpeg binaries if present
        for candidate_dir in [
            self.BASE_DIR.parent / "ffmpeg" / "bin",
            self.BASE_DIR / "ffmpeg" / "bin",
        ]:
            if (candidate_dir / "ffmpeg.exe").is_file():
                if self.FFMPEG_PATH == "ffmpeg":
                    self.FFMPEG_PATH = str(candidate_dir / "ffmpeg.exe")
                if self.FFPROBE_PATH == "ffprobe":
                    self.FFPROBE_PATH = str(candidate_dir / "ffprobe.exe")
                break

        return self

    @property
    def MAX_UPLOAD_SIZE_BYTES(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    def ensure_directories(self) -> None:
        """Create data directories if they do not exist."""
        for d in [self.UPLOAD_DIR, self.OUTPUT_DIR, self.TEMP_DIR]:
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
