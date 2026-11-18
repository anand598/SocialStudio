from datetime import datetime
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: Literal["queued", "processing", "completed", "failed"]
    stage: str
    progress: int
    input_type: Literal["image", "video", "url"]
    source_url: str | None
    platform: str
    format: str
    output_kind: Literal["video", "image"]
    has_music: bool
    generation_mode: str
    created_at: datetime
    updated_at: datetime
    product_analysis: dict[str, Any] | None
    generated_content: dict[str, Any] | None
    # Platform-ready post text with hashtag and length rules applied.
    post_text: str | None
    error_code: str | None
    error_message: str | None


class JobSummary(BaseModel):
    """A light history row; full results stay behind GET /generations/{id}."""
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: Literal["queued", "processing", "completed", "failed"]
    stage: str
    progress: int
    input_type: Literal["image", "video", "url"]
    platform: str
    format: str
    output_kind: Literal["video", "image"]
    headline: str | None
    created_at: datetime


class JobHistory(BaseModel):
    items: list[JobSummary]
