"""Typed registry of supported platform output formats.

Every renderer, validator and API response reads dimensions and copy rules from here,
so adding a format is a data change plus a test, not a code path.
"""
from typing import Literal
from pydantic import BaseModel

Kind = Literal["video", "image"]


class OutputFormat(BaseModel):
    platform: Literal["instagram", "tiktok", "youtube"]
    platform_label: str
    format: str
    label: str
    kind: Kind
    width: int
    height: int
    aspect_ratio: str
    description: str
    # Platform post-text rules applied to the downloadable caption package.
    caption_limit: int
    max_hashtags: int
    # Upper bound for video outputs rendered from a source video.
    max_video_seconds: int = 0
    copy_guidance: str

    @property
    def orientation(self) -> Literal["portrait", "square", "landscape"]:
        ratio = self.height / self.width
        return "portrait" if ratio > 1.1 else "landscape" if ratio < 0.9 else "square"


SUPPORTED_FORMATS = [
    OutputFormat(platform="instagram", platform_label="Instagram", format="reel", label="Instagram Reel",
                 kind="video", width=1080, height=1920, aspect_ratio="9:16", max_video_seconds=30,
                 description="Vertical MP4 for Reels", caption_limit=2200, max_hashtags=5,
                 copy_guidance="Instagram Reel: punchy hook, warm conversational caption, 3-5 relevant hashtags."),
    OutputFormat(platform="instagram", platform_label="Instagram", format="feed_portrait", label="Instagram Feed Post (4:5)",
                 kind="image", width=1080, height=1350, aspect_ratio="4:5",
                 description="Portrait JPEG for the feed", caption_limit=2200, max_hashtags=5,
                 copy_guidance="Instagram feed image post: one strong headline, descriptive caption, 3-5 hashtags."),
    OutputFormat(platform="instagram", platform_label="Instagram", format="feed_square", label="Instagram Square Post (1:1)",
                 kind="image", width=1080, height=1080, aspect_ratio="1:1",
                 description="Square JPEG for the feed", caption_limit=2200, max_hashtags=5,
                 copy_guidance="Instagram square image post: one strong headline, descriptive caption, 3-5 hashtags."),
    OutputFormat(platform="tiktok", platform_label="TikTok", format="video", label="TikTok Video",
                 kind="video", width=1080, height=1920, aspect_ratio="9:16", max_video_seconds=30,
                 description="Vertical MP4 for the For You feed", caption_limit=2200, max_hashtags=5,
                 copy_guidance="TikTok: casual, energetic, native tone; very short caption; 3-5 hashtags."),
    OutputFormat(platform="youtube", platform_label="YouTube", format="shorts", label="YouTube Short",
                 kind="video", width=1080, height=1920, aspect_ratio="9:16", max_video_seconds=30,
                 description="Vertical MP4 for Shorts", caption_limit=5000, max_hashtags=3,
                 copy_guidance="YouTube Shorts: searchable title under 100 characters, short description, up to 3 hashtags."),
    OutputFormat(platform="youtube", platform_label="YouTube", format="video", label="YouTube Video (16:9)",
                 kind="video", width=1920, height=1080, aspect_ratio="16:9", max_video_seconds=30,
                 description="Landscape 1080p MP4", caption_limit=5000, max_hashtags=3,
                 copy_guidance="YouTube video: searchable title under 100 characters, informative description, up to 3 hashtags."),
    OutputFormat(platform="youtube", platform_label="YouTube", format="thumbnail", label="YouTube Thumbnail",
                 kind="image", width=1280, height=720, aspect_ratio="16:9",
                 description="1280 × 720 JPEG thumbnail", caption_limit=5000, max_hashtags=3,
                 copy_guidance="YouTube thumbnail: 2-5 word bold headline, plus title and description for the upload."),
]

INSTAGRAM_REEL = SUPPORTED_FORMATS[0]


def get_format(platform: str, format: str) -> OutputFormat | None:
    return next((item for item in SUPPORTED_FORMATS if item.platform == platform and item.format == format), None)


def compose_post_text(output: OutputFormat, content: dict) -> str:
    """Build the platform-ready post text, enforcing hashtag and length limits.

    Models often repeat hashtags or the CTA inside the caption; those are moved or dropped so
    each appears once, in its own section.
    """
    words = str(content.get("caption", "")).split()
    caption = " ".join(word for word in words if not word.startswith("#"))
    tags = []
    for tag in [word for word in words if word.startswith("#")] + list(content.get("hashtags", [])):
        tag = "#" + "".join(ch for ch in str(tag).lstrip("#") if ch.isalnum() or ch == "_")
        if len(tag) > 1 and tag.lower() not in {t.lower() for t in tags}:
            tags.append(tag)
    tags = tags[:output.max_hashtags]
    cta = str(content.get("call_to_action", "")).strip()
    if cta and cta.lower().rstrip(".!") in caption.lower():
        cta = ""
    parts = []
    if output.platform == "youtube" and content.get("title"):
        parts.append(f"Title: {content['title'][:100]}")
    parts += [caption, cta, " ".join(tags)]
    text = "\n\n".join(part for part in parts if part)
    return text if len(text) <= output.caption_limit else text[:output.caption_limit - 1].rstrip() + "…"
