import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import CheckConstraint, Index, DateTime, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.platforms import compose_post_text, get_format
from app.db.base import Base


class GenerationJob(Base):
    __tablename__ = "generation_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'processing', 'completed', 'failed')", name="job_status"),
        CheckConstraint("progress BETWEEN 0 AND 100", name="job_progress"),
        Index("ix_generation_jobs_owner_created", "owner_hash", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_token: Mapped[uuid.UUID | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), default="queued")
    stage: Mapped[str] = mapped_column(String(32), default="validating")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    input_type: Mapped[str] = mapped_column(String(16), default="image")
    # Normalized still used for analysis and templates; URL jobs receive it after fetching.
    input_file_path: Mapped[str | None] = mapped_column(Text)
    # Validated original video for video inputs.
    source_media_path: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    # Optional user-supplied background music for video outputs.
    music_path: Mapped[str | None] = mapped_column(Text)
    # Untrusted page metadata extracted from a product URL (title, description, site name).
    source_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # SHA-256 of the creating browser's owner cookie; only that browser may read the job.
    owner_hash: Mapped[str | None] = mapped_column(String(64))
    platform: Mapped[str] = mapped_column(String(32))
    format: Mapped[str] = mapped_column(String(32))
    brand_context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    generation_mode: Mapped[str] = mapped_column(String(16), default="ollama")
    product_analysis: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    generated_content: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    output_file_path: Mapped[str | None] = mapped_column(Text)
    thumbnail_file_path: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def output_format(self):
        return get_format(self.platform, self.format)

    @property
    def has_music(self) -> bool:
        return bool(self.music_path)

    @property
    def output_kind(self) -> str:
        output = self.output_format
        return output.kind if output else "video"

    @property
    def headline(self) -> str | None:
        content = self.generated_content or {}
        return (content.get("title") or content.get("hook") or None) if self.status == "completed" else None

    @property
    def post_text(self) -> str | None:
        output = self.output_format
        return compose_post_text(output, self.generated_content) if output and self.generated_content else None
