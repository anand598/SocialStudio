"""Font loading and text fitting shared by posters, promo videos, and video overlays."""
from functools import lru_cache
from pathlib import Path
from PIL import ImageFont
from app.core.config import get_settings

REGULAR_FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf"]
BOLD_FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/System/Library/Fonts/Supplemental/Arial Bold.ttf"]


def font(size: int, bold: bool = False):
    settings = get_settings()
    # A configured font (e.g. for non-Latin scripts) wins over bundled bold faces.
    configured = [settings.font_bold_path or settings.font_path] if bold else [settings.font_path]
    return _load_font(tuple(configured + (BOLD_FONTS if bold else []) + REGULAR_FONTS), size)


@lru_cache(maxsize=256)
def _load_font(candidates: tuple[str, ...], size: int):
    for name in candidates:
        if name and Path(name).is_file():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default(size=size)


def wrap_text(draw, text: str, face, width: int) -> list[str]:
    # Break oversized words too, so arbitrary user CTA cannot escape the canvas.
    lines, line = [], ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=face) <= width:
            line = candidate
            continue
        if line:
            lines.append(line)
        line = ""
        for char in word:
            if draw.textlength(line + char, font=face) > width:
                lines.append(line)
                line = char
            else:
                line += char
    if line:
        lines.append(line)
    return lines or [""]


def fit_text(draw, text: str, width: int, height: int, size: int,
             bold: bool = False) -> tuple[object, list[str], int]:
    """Shrink the font until the wrapped text fits the box; truncate only as a last resort."""
    minimum = max(14, int(size * 0.6))
    while True:
        face = font(size, bold)
        lines = wrap_text(draw, text, face, width)
        line_height = round(size * 1.2)
        if len(lines) * line_height <= height or size <= minimum:
            return face, lines[:max(1, height // line_height)], line_height
        size = max(minimum, int(size * 0.88))
