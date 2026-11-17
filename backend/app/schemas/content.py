from pydantic import BaseModel, ConfigDict, Field, field_validator

PLACEHOLDERS = {"", "null", "none", "n/a", "na", "unknown", "unspecified"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProductAnalysis(StrictModel):
    product_name: str | None = Field(max_length=80)
    product_category: str = Field(min_length=1, max_length=100)
    visible_attributes: list[str] = Field(max_length=6)
    visible_text: list[str] = Field(max_length=6)
    likely_audience: str = Field(max_length=240, description="An inference, never an observed fact")
    visual_style: str = Field(max_length=240)
    # Order matters for constrained decoding: the model treats the limitations summary as the end of
    # its answer, so it must be the final property (a required field after it caused runaway output).
    facts_needing_user_confirmation: list[str] = Field(max_length=6)
    confidence_or_limitations: str = Field(min_length=1, max_length=500)

    @field_validator("product_name", mode="before")
    @classmethod
    def placeholder_is_none(cls, value):
        # Small models often return the string "null" instead of JSON null.
        return None if isinstance(value, str) and value.strip().lower() in PLACEHOLDERS else value


class Scene(StrictModel):
    text: str = Field(min_length=1, max_length=100,
                      description="Viewer-facing on-screen caption, max ~10 words; never a camera direction")
    duration_seconds: int = Field(ge=2, le=5)


class SocialContent(StrictModel):
    title: str = Field(default="", max_length=100, description="Upload title; required for YouTube")
    hook: str = Field(min_length=1, max_length=80)
    short_description: str = Field(min_length=1, max_length=240)
    benefits: list[str] = Field(max_length=3)
    caption: str = Field(min_length=1, max_length=1500)
    call_to_action: str = Field(min_length=1, max_length=100)
    hashtags: list[str] = Field(min_length=1, max_length=10)
    scenes: list[Scene] = Field(min_length=3, max_length=4)
    disclaimer_or_assumptions: str = Field(min_length=1, max_length=500)
