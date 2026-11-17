"""Promo-style rendering for template videos and posters.

Review found the still-to-video output read as a slideshow: a flat dark-green background, the
product in a beige mat, one static framing, captions baked into the frame, and dips to black.
"""
import time
from PIL import Image, ImageChops, ImageDraw, ImageStat
import pytest
from app.core.platforms import get_format
from app.services.media import promo, renderer


def textured(path, size=(1600, 1000), base=(40, 90, 200)):
    """A product-like photo with detail everywhere, so crops and motion are measurable."""
    image = Image.new("RGB", size, base)
    draw = ImageDraw.Draw(image)
    for x in range(0, size[0], 80):
        for y in range(0, size[1], 80):
            shade = (x * 7 + y * 3) % 160
            draw.rectangle((x, y, x + 60, y + 60), fill=(base[0], min(255, base[1] + shade // 2), base[2] - shade // 3))
    image.save(path)
    return str(path)


def scenes():
    return [("A fresh take on desk setups.", 2), ("Silver aluminum body.", 3), ("Black keys. Glass of water.", 3),
            ("Explore the collection", 3)]


def diff(a: Image.Image, b: Image.Image, box=None) -> float:
    if box:
        a, b = a.crop(box), b.crop(box)
    return sum(ImageStat.Stat(ImageChops.difference(a.convert("RGB"), b.convert("RGB"))).mean) / 3


def test_palette_follows_the_product_colour_and_falls_back_for_grey():
    dark, accent = promo.palette(Image.new("RGB", (64, 64), (200, 40, 40)))
    assert accent[0] > accent[1] and accent[0] > accent[2]          # red product → warm accent
    assert max(dark) < 80                                            # backdrop tint stays dark
    _, grey_accent = promo.palette(Image.new("RGB", (64, 64), (128, 128, 128)))
    assert grey_accent == promo.DEFAULT_ACCENT


def test_backdrop_is_built_from_the_product_photo(tmp_path):
    output = get_format("instagram", "feed_portrait")
    poster = renderer.compose_frame(output, textured(tmp_path / "blue.jpg"), "Headline", "", cta="Shop now")
    r, g, b = poster.getpixel((12, output.height // 2))
    assert b > g and b > r, "background should carry the product's blue, not a fixed green"


def card_aspect(output, photo):
    left, top, right, bottom = promo.Promo(output, photo, scenes(), brand="", cta="Shop").card
    return (right - left) / (bottom - top)


def test_card_adopts_the_photo_aspect_without_a_mat(tmp_path):
    wide = textured(tmp_path / "wide.jpg")                          # 1.6 : 1
    assert abs(card_aspect(get_format("youtube", "video"), wide) - 1.6) < 0.05
    # On 9:16 a very wide photo would leave a thin card and an empty frame: crop its sides to 1.3 : 1.
    assert abs(card_aspect(get_format("instagram", "reel"), wide) - 1.3) < 0.05
    square = textured(tmp_path / "square.jpg", size=(1000, 1000))
    assert abs(card_aspect(get_format("instagram", "reel"), square) - 1.0) < 0.05


def test_card_content_fills_the_card_at_every_zoom(tmp_path):
    video = promo.Promo(get_format("instagram", "reel"), textured(tmp_path / "p.jpg"), scenes(), brand="", cta="Shop")
    left, top, right, bottom = video.card
    for index in range(len(video.plan)):
        assert video._card_content(index, 0.5).size == (right - left, bottom - top)


def test_scenes_use_different_framings_and_motion(tmp_path):
    video = promo.Promo(get_format("instagram", "reel"), textured(tmp_path / "p.jpg"), scenes(), brand="", cta="Shop")
    plan = video.plan
    assert plan[0].start.zoom == 1.0 and plan[-1].end.zoom == 1.0   # opens and closes on the whole product
    assert any(step.start.zoom > 1.3 for step in plan[1:-1])          # close-up detail shots in between
    assert len({(step.start, step.end) for step in plan}) == len(plan)
    card = video.card
    first, later = video.frame(0.3), video.frame(1.6)
    assert diff(first, later, card) > 2, "the product should move within a scene"


def test_captions_animate_in(tmp_path):
    video = promo.Promo(get_format("tiktok", "video"), textured(tmp_path / "p.jpg"), scenes(), brand="", cta="Shop")
    box = video.text_box(1)
    start = 2  # second scene begins after the 2 s hook
    assert diff(video.frame(start + 0.6), video.frame(start + 1.5), box) < diff(video.frame(start + 0.02),
                                                                             video.frame(start + 1.5), box)


def test_scene_changes_cross_fade_instead_of_dipping_to_black(tmp_path):
    video = promo.Promo(get_format("instagram", "reel"), textured(tmp_path / "p.jpg"), scenes(), brand="", cta="Shop")
    def brightness(t):
        return sum(ImageStat.Stat(video.frame(t).convert("L")).mean)
    assert brightness(2.0) >= 0.85 * min(brightness(1.7), brightness(2.3))
    middle = video.frame(2.0)
    assert diff(middle, video.frame(1.7)) > 1 and diff(middle, video.frame(2.3)) > 1


def test_end_card_shows_brand_and_cta(tmp_path):
    video = promo.Promo(get_format("instagram", "reel"), textured(tmp_path / "p.jpg"), scenes(),
                        brand="Sunday Supply", cta="Explore the collection")
    end = video.frame(video.duration - 0.05)
    pill = video.cta_box
    assert pill is not None
    r, g, b = end.getpixel(((pill[0] + pill[2]) // 2, pill[1] + 4))
    assert (r, g, b) != end.getpixel((5, 5)) and min(r, g, b) > 120   # a light accent button is drawn


@pytest.mark.parametrize("platform,format", [("instagram", "reel"), ("youtube", "video")])
def test_promo_renders_exact_video_quickly(tmp_path, platform, format):
    from uuid import uuid4
    output = get_format(platform, format)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    from test_render_quality import content
    started = time.monotonic()
    path, thumbnail = renderer.render_slideshow(tmp_path, scratch, output, textured(tmp_path / "p.jpg"), content(),
                                                {"brand_name": "Sunday Supply"}, uuid4())
    assert time.monotonic() - started < 90
    assert path.suffix == ".mp4" and thumbnail.is_file()
