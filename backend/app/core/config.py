from functools import lru_cache
from typing import Literal
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")
    app_env: str = "development"
    frontend_origin: str = "http://localhost:3000"
    database_url: str = "postgresql+psycopg://app:app_password@localhost:5432/social_content"
    redis_url: str = "redis://localhost:6379/0"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3.5:4b"
    ollama_vision_model: str = "qwen3.5:4b"
    ollama_temperature: float = Field(default=0.2, ge=0, le=1)
    ollama_num_predict: int = Field(default=2200, ge=512, le=8192)
    ollama_num_ctx: int = Field(default=4096, ge=2048, le=32768)
    ollama_keep_alive: str = "60s"
    ollama_timeout_seconds: int = Field(default=120, gt=0)
    local_storage_path: str = str(Path(__file__).resolve().parents[3] / "storage")
    generation_mode: Literal["ollama", "demo"] = "ollama"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    requests_per_minute: int = Field(default=10, gt=0)
    font_path: str = ""
    font_bold_path: str = ""
    ffmpeg_timeout_seconds: int = Field(default=180, gt=0)
    stale_job_seconds: int = Field(default=900, ge=60)
    max_upload_size_mb: int = Field(default=15, gt=0)
    max_video_upload_size_mb: int = Field(default=100, gt=0)
    max_source_video_seconds: int = Field(default=180, gt=0)
    # Optional background music for video outputs (user-supplied; they must hold the rights).
    max_music_upload_size_mb: int = Field(default=20, ge=0)
    max_music_seconds: int = Field(default=600, gt=0)
    url_fetch_timeout_seconds: int = Field(default=10, gt=0)
    url_max_redirects: int = Field(default=3, ge=0, le=10)
    # Mark the job-owner cookie Secure; enable whenever the app is served over HTTPS.
    cookie_secure: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
