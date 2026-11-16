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
    platform: str
    format: str
    generation_mode: str
    created_at: datetime
    updated_at: datetime
    product_analysis: dict[str, Any] | None
    generated_content: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
