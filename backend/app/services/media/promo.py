"""Promo-style design for still images: posters and animated promo videos.

Every design is built from the product photo itself rather than a fixed template colour:
  * backdrop - the photo, cover-scaled, heavily blurred, and tinted dark in its own colour;
  * card     - the photo at its own aspect ratio (no mat), with rounded corners and a soft shadow;
  * accent   - a light tint of the product colour for the caption bar and the CTA button.

Videos follow a shot plan (whole product -> close-ups -> whole product on the end card) with eased
zoom/pan inside the card, captions that slide in, a slow backdrop drift, and cross-fades between
scenes. Frames are composed in Pillow with sub-pixel sampling (FFmpeg's zoompan visibly jitters on
slow moves) and streamed to FFmpeg as raw video.
"""
import colorsys
import re
from dataclasses import dataclass
from PIL import Image, ImageDraw, ImageFilter, ImageOps
from app.core.platforms import OutputFormat
from app.services.media.typography import fit_text, font, wrap_text

DEFAULT_DARK = (16, 47, 43)
DEFAULT_ACCENT = (204, 237, 203)
INK = (16, 32, 30)
FPS = 24
CROSSFADE = 0.4


def palette(image: Image.Image) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """(dark backdrop tint, light accent) derived from the product's most prominent colour."""
    small = image.convert("RGB").resize((48, 48))
    quantized = small.quantize(colors=6, method=Image.Quantize.MEDIANCUT)
    colours = quantized.getpalette()
    best, best_score = None, 0.0
    for count, index in quantized.getcolors():
        r, g, b = colours[index * 3:index * 3 + 3]
        hue, saturation, value = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if saturation < 0.22 or not 0.15 <= value <= 0.97:
            continue
        if count * saturation > best_score:
            best, best_score = (hue, saturation), count * saturation
    if best is None:  # Greys and near-monochrome products keep the studio palette.
        return DEFAULT_DARK, DEFAULT_ACCENT
    hue, saturation = best
    def rgb(s: float, v: float) -> tuple[int, int, int]:
        return tuple(round(c * 255) for c in colorsys.hsv_to_rgb(hue, s, v))
    return rgb(min(0.65, saturation * 0.8 + 0.1), 0.17), rgb(min(0.5, max(0.3, saturation * 0.6)), 0.96)


Colour = tuple[int, int, int]
WHITE = (255, 255, 255)


def hex_rgb(value: str) -> Colour:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def contrast(a: Colour, b: Colour) -> float:
    """WCAG contrast ratio between two sRGB colours."""
    def luminance(colour: Colour) -> float:
        channels = [c / 255 for c in colour]
        r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def text_on(fill: Colour) -> Colour:
    """White or dark ink, whichever reads better on the fill."""
    return WHITE if contrast(fill, WHITE) >= contrast(fill, INK) else INK


def brand_palette(colour: str) -> tuple[Colour, Colour]:
    """(dark backdrop tint, accent) for a brand colour: the accent is the exact colour, the tint its hue."""
    accent = hex_rgb(colour)
    hue, saturation, _ = colorsys.rgb_to_hsv(*(c / 255 for c in accent))
    dark = tuple(round(c * 255) for c in colorsys.hsv_to_rgb(hue, min(0.7, saturation * 0.85 + 0.1), 0.2))
    return dark, accent


def fit_logo(path: str, output: OutputFormat) -> Image.Image:
    """The logo scaled for the brand position: a fixed cap height, never wider than 40 % of the frame."""
    with Image.open(path) as image:
        logo = image.convert("RGBA")
    box = logo.getchannel("A").getbbox()  # place by the visible mark, not its transparent margins
    if box:
        logo = logo.crop(box)
    height = round(min(output.width, output.height) * 0.07)
    scale = min(height / logo.height, output.width * 0.4 / logo.width)
    return logo.resize((max(1, round(logo.width * scale)), max(1, round(logo.height * scale))),
                       Image.Resampling.LANCZOS)


def smooth(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


@dataclass(frozen=True)
class Layout:
    brand: tuple[int, int]
    card_area: tuple[int, int, int, int]
    text: tuple[int, int, int, int]
    headline: int
    cta: tuple[int, int]


def layout(output: OutputFormat) -> Layout:
    w, h = output.width, output.height
    if output.orientation == "landscape":
        m = round(h * 0.08)
        # Thumbnails are judged at ~300 px wide, so their headline is much larger than a video caption's.
        size = round(h * (0.12 if output.kind == "image" else 0.085))
        return Layout((m, round(h * 0.09)), (round(w * 0.5), round(h * 0.1), w - m, round(h * 0.9)),
                      (m, round(h * 0.22), round(w * 0.45), round(h * 0.74)), size, (m, round(h * 0.8)))
    m = round(w * 0.075)
    if h / w >= 1.6:  # 9:16 - everything inside vertical-feed safe zones (top 10 %, bottom 20 %)
        return Layout((m, round(h * 0.1)), (m, round(h * 0.14), w - m, round(h * 0.6)),
                      (m, round(h * 0.645), w - m, round(h * 0.745)), round(w * 0.07), (m, round(h * 0.755)))
    if h / w >= 1.1:  # 4:5
        return Layout((m, round(h * 0.055)), (m, round(h * 0.1), w - m, round(h * 0.6)),
                      (m, round(h * 0.65), w - m, round(h * 0.84)), round(w * 0.07), (m, round(h * 0.87)))
    return Layout((m, round(h * 0.06)), (m, round(h * 0.11), w - m, round(h * 0.58)),
                  (m, round(h * 0.635), w - m, round(h * 0.82)), round(w * 0.066), (m, round(h * 0.855)))


@dataclass(frozen=True)
class Framing:
    cx: float
    cy: float
    zoom: float


@dataclass(frozen=True)
class Shot:
    start: Framing
    end: Framing


OPENING = Shot(Framing(0.5, 0.5, 1.0), Framing(0.5, 0.5, 1.08))
DETAILS = [Shot(Framing(0.5, 0.45, 1.5), Framing(0.5, 0.45, 1.68)),     # push in on the centre
           Shot(Framing(0.36, 0.5, 1.42), Framing(0.62, 0.5, 1.42)),     # pan across
           Shot(Framing(0.62, 0.55, 1.62), Framing(0.56, 0.5, 1.45))]    # pull back
CLOSING = Shot(Framing(0.5, 0.5, 1.1), Framing(0.5, 0.5, 1.0))


def shot_plan(count: int, max_zoom: float) -> list[Shot]:
    """Whole product first and last, close-ups between; zoom is limited by source resolution."""
    def limit(f: Framing) -> Framing:
        return Framing(f.cx, f.cy, 1 + (f.zoom - 1) * min(1.0, (max_zoom - 1) / 0.68)) if max_zoom < 1.68 else f
    middle = [DETAILS[i % len(DETAILS)] for i in range(max(0, count - 2))]
    plan = [OPENING, *middle, CLOSING][:count] if count > 1 else [OPENING]
    return [Shot(limit(s.start), limit(s.end)) for s in plan]


def same_text(a: str, b: str) -> bool:
    def key(text: str) -> str:
        return re.sub(r"[^a-z0-9]", "", text.lower())
    return key(a) == key(b)


class Promo:
    """Composes promo frames for a still product image; also renders the static poster."""

    def __init__(self, output: OutputFormat, source: str, scenes: list[tuple[str, int]], *, brand: str, cta: str,
                 brand_color: str | None = None, logo: str | None = None):
        self.output, self.size = output, (output.width, output.height)
        with Image.open(source) as image:
            self.photo = image.convert("RGB")
        self.dark, self.accent = brand_palette(brand_color) if brand_color else palette(self.photo)
        # Brand name and accent bar sit on the dark backdrop: a dark brand colour falls back to white there.
        self.highlight = self.accent if contrast(self.accent, self.dark) >= 3 else WHITE
        self.layout = layout(output)
        self.cta = cta.strip()
        # The end card carries the CTA as a button; if its caption is just the CTA, echo the opening line.
        texts = [text for text, _ in scenes]
        if len(texts) > 1 and self.cta and same_text(texts[-1], self.cta):
            texts[-1] = texts[0]
        self.texts, self.seconds = texts, [seconds for _, seconds in scenes]
        self.starts = [sum(self.seconds[:i]) for i in range(len(scenes))]
        self.duration = sum(self.seconds)
        self.card = self._card_box()
        card_w, card_h = self.card[2] - self.card[0], self.card[3] - self.card[1]
        self.plan = shot_plan(len(scenes), self.photo.width / (card_w * 0.9))
        self._backdrop = self._make_backdrop(oversize=1.08)
        self._mask, self._shadow = self._card_masks(card_w, card_h)
        self._sources: dict[int, tuple[Image.Image, float]] = {}
        self.logo_box = None
        if logo:
            mark = fit_logo(logo, output)
            x, y = self.layout.brand
            self.logo_box = (x, y, x + mark.width, y + mark.height)
            self._brand = (mark.convert("RGB"), mark.getchannel("A"), (x, y))
        else:
            self._brand = self._text_layer((brand or "Product spotlight").upper()[:60], self.layout.brand,
                                           round(min(self.size) * 0.03), self.highlight, shadow=False)
        self._texts = [self._headline_layer(text) for text in self.texts]
        self.cta_box, self._cta = self._cta_layer() if self.cta else (None, None)

    # ---------- static elements ----------
    def _card_box(self) -> tuple[int, int, int, int]:
        x0, y0, x1, y1 = self.layout.card_area
        aspect = self.photo.width / self.photo.height
        if self.output.height / self.output.width >= 1.6:
            aspect = min(aspect, 1.3)  # a very wide photo would leave a thin card in a tall frame
        box_w, box_h = x1 - x0, y1 - y0
        fitted = (box_w, round(box_w / aspect)) if box_w / aspect <= box_h else (round(box_h * aspect), box_h)
        left = x0 + (x1 - x0 - fitted[0]) // 2
        # Portrait canvases keep product and caption together; landscape centres the card.
        top = y1 - fitted[1] if self.output.orientation != "landscape" else y0 + (y1 - y0 - fitted[1]) // 2
        return left, top, left + fitted[0], top + fitted[1]

    def _make_backdrop(self, oversize: float) -> Image.Image:
        w, h = round(self.size[0] * oversize), round(self.size[1] * oversize)
        small = ImageOps.fit(self.photo, (max(8, w // 12), max(8, h // 12)))
        blurred = small.filter(ImageFilter.GaussianBlur(radius=max(3, small.width // 9)))
        backdrop = Image.blend(blurred.resize((w, h), Image.Resampling.BICUBIC), Image.new("RGB", (w, h), self.dark), 0.58)
        # Darken where text sits so captions stay readable over any photo.
        ramp = Image.linear_gradient("L")
        if self.output.orientation == "landscape":
            shade = ramp.rotate(90, expand=True).resize((w, h)).point(lambda v: round(v * 0.62))
        else:
            shade = ramp.resize((w, h)).point(lambda v: round(max(0, v - 90) * 0.85))
        backdrop.paste((0, 0, 0), (0, 0), shade)
        return backdrop

    def _card_masks(self, w: int, h: int) -> tuple[Image.Image, tuple[Image.Image, tuple[int, int]]]:
        radius = round(min(w, h) * 0.045)
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
        pad = round(min(self.size) * 0.05)
        shadow = Image.new("L", (w + pad * 2, h + pad * 2), 0)
        shadow.paste(Image.new("L", (w, h), 150), (pad, pad), mask)
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=pad // 2))
        return mask, (shadow, (self.card[0] - pad, self.card[1] - pad + round(h * 0.03)))

    def _text_layer(self, text: str, origin: tuple[int, int], size: int, colour, *, shadow: bool,
                    width: int | None = None, height: int | None = None, bold: bool = True):
        probe = ImageDraw.Draw(Image.new("L", (1, 1)))
        width = width or self.size[0] - origin[0] * 2
        face, lines, line_height = fit_text(probe, text, width, height or size * 2, size, bold=bold)
        pad = round(size * 0.35)
        layer = Image.new("RGBA", (width + pad * 2, len(lines) * line_height + pad * 2), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        for row, line in enumerate(lines):
            draw.text((pad, pad + row * line_height), line, font=face, fill=(*colour, 255))
        if shadow:
            alpha = layer.getchannel("A").filter(ImageFilter.GaussianBlur(radius=max(2, size // 12)))
            under = Image.new("RGBA", layer.size, (0, 0, 0, 0))
            under.putalpha(alpha.point(lambda v: round(v * 0.55)))
            layer = Image.alpha_composite(under, layer)
        return layer.convert("RGB"), layer.getchannel("A"), (origin[0] - pad, origin[1] - pad)

    def _headline_layer(self, text: str):
        x0, y0, x1, y1 = self.layout.text
        return self._text_layer(text, (x0, y0), self.layout.headline, (255, 255, 255), shadow=True,
                                width=x1 - x0, height=y1 - y0)

    def _cta_layer(self):
        size = max(22, round(min(self.size) * (0.032 if self.output.orientation != "landscape" else 0.04)))
        face = font(size, bold=True)
        probe = ImageDraw.Draw(Image.new("L", (1, 1)))
        label = wrap_text(probe, self.cta, face, self.size[0] // 2)[0]
        w, h = round(probe.textlength(label, font=face) + size * 2.2), round(size * 2.2)
        pill = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(pill)
        draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2, fill=(*self.accent, 255))
        draw.text((size * 1.1, (h - size) / 2 - size * 0.08), label, font=face, fill=(*text_on(self.accent), 255))
        x, y = self.layout.cta
        return (x, y, x + w, y + h), (pill.convert("RGB"), pill.getchannel("A"), (x, y))

    def text_box(self, index: int) -> tuple[int, int, int, int]:
        rgb, _, (x, y) = self._texts[index]
        return x, y, x + rgb.width, y + rgb.height

    # ---------- animation ----------
    def _source_for(self, index: int) -> tuple[Image.Image, float]:
        """Photo pre-scaled for one shot so sampling stays near 1:1 (no shimmer from downscaling)."""
        if index not in self._sources:
            shot = self.plan[index]
            zoom = max(shot.start.zoom, shot.end.zoom)
            card_w = self.card[2] - self.card[0]
            scale = min(1.0, card_w * zoom / self.photo.width)
            size = (max(1, round(self.photo.width * scale)), max(1, round(self.photo.height * scale)))
            self._sources[index] = (self.photo.resize(size, Image.Resampling.LANCZOS), scale)
        return self._sources[index]

    def _card_content(self, index: int, progress: float) -> Image.Image:
        source, _ = self._source_for(index)
        shot = self.plan[index]
        p = smooth(progress)
        zoom = shot.start.zoom + (shot.end.zoom - shot.start.zoom) * p
        cx = shot.start.cx + (shot.end.cx - shot.start.cx) * p
        cy = shot.start.cy + (shot.end.cy - shot.start.cy) * p
        # Largest card-shaped window in the photo (cropping the sides of extra-wide photos), then zoom.
        size = (self.card[2] - self.card[0], self.card[3] - self.card[1])
        aspect = size[0] / size[1]
        base_w = min(source.width, source.height * aspect)
        w, h = base_w / zoom, base_w / aspect / zoom
        left = min(max(cx * source.width - w / 2, 0), source.width - w)
        top = min(max(cy * source.height - h / 2, 0), source.height - h)
        return source.transform(size, Image.Transform.EXTENT, (left, top, left + w, top + h), Image.Resampling.BICUBIC)

    def _paste(self, base: Image.Image, layer, alpha: float = 1.0, dy: int = 0) -> None:
        rgb, mask, (x, y) = layer
        if alpha <= 0:
            return
        base.paste(rgb, (x, y + dy), mask if alpha >= 1 else mask.point(lambda v: round(v * alpha)))

    def _scene_frame(self, index: int, local: float, clock: float) -> Image.Image:
        bw, bh = self._backdrop.size
        drift = 0.15 + 0.7 * (clock / self.duration if self.duration else 0)
        ox, oy = round((bw - self.size[0]) * drift), (bh - self.size[1]) // 2
        frame = self._backdrop.crop((ox, oy, ox + self.size[0], oy + self.size[1]))
        shadow, origin = self._shadow
        frame.paste((0, 0, 0), origin, shadow)
        frame.paste(self._card_content(index, local / self.seconds[index]), self.card[:2], self._mask)
        self._paste(frame, self._brand)
        # Accent bar grows, then the caption slides up into place.
        x0, y0 = self.layout.text[:2]
        bar = round(min(self.size) * 0.11 * smooth((local - 0.05) / 0.4))
        if bar > 0:
            thickness = max(6, round(min(self.size) * 0.008))
            ImageDraw.Draw(frame).rectangle((x0, y0 - thickness * 3, x0 + bar, y0 - thickness * 2), fill=self.highlight)
        reveal = smooth((local - 0.15) / 0.45)
        self._paste(frame, self._texts[index], reveal, round((1 - reveal) * self.size[1] * 0.025))
        if self._cta and index == len(self.texts) - 1:  # the end card (or the poster) carries the button
            pop = smooth((local - 0.45) / 0.4)
            self._paste(frame, self._cta, pop, round((1 - pop) * self.size[1] * 0.02))
        return frame

    def _scene_at(self, clock: float) -> int:
        return max(i for i, start in enumerate(self.starts) if start <= clock) if clock >= 0 else 0

    def frame(self, clock: float) -> Image.Image:
        clock = min(max(clock, 0.0), self.duration)
        index = min(self._scene_at(clock), len(self.texts) - 1)
        half = CROSSFADE / 2
        pair = None
        if index + 1 < len(self.texts) and clock >= self.starts[index + 1] - half:
            pair = (index, index + 1)
        elif index > 0 and clock < self.starts[index] + half:
            pair = (index - 1, index)
        if pair is None:
            return self._scene_frame(index, clock - self.starts[index], clock)
        before, after = pair
        mix = smooth((clock - (self.starts[after] - half)) / CROSSFADE)
        return Image.blend(self._scene_frame(before, clock - self.starts[before], clock),
                           self._scene_frame(after, max(0.0, clock - self.starts[after]), clock), mix)

    def frames(self):
        for k in range(round(self.duration * FPS)):
            yield self.frame(k / FPS)

    # ---------- poster ----------
    def poster(self) -> Image.Image:
        """The finished look as one still: whole product, headline, brand, and CTA button."""
        frame = self._scene_frame(0, self.seconds[0], self.duration / 2)
        frame.paste(self._card_content(0, 0.0), self.card[:2], self._mask)  # whole product, unzoomed
        return frame
