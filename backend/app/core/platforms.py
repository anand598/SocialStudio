from typing import Literal
from pydantic import BaseModel


class OutputFormat(BaseModel):
    platform: Literal["instagram"] = "instagram"
    format: Literal["reel"] = "reel"
    label: str = "Instagram Reel"
    width: int = 1080
    height: int = 1920
    aspect_ratio: str = "9:16"


INSTAGRAM_REEL = OutputFormat()
SUPPORTED_FORMATS = [INSTAGRAM_REEL]
