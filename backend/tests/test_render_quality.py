"""Visual quality rules found by reviewing rendered output frame by frame."""
from pathlib import Path
import pytest
from PIL import Image, ImageChops
from app.core.platforms import get_format
from app.schemas.content import Scene, SocialContent
from app.services.media import renderer
from app.services.media.promo import layout


def content(hook="Glossy. Curved. Quiet.", first="Glossy finish."):
    return SocialContent(title="Teapot", hook=hook, short_description="d", benefits=[], caption="c",
                         call_to_action="Explore the collection", hashtags=["#Tea"],
                         scenes=[Scene(text=first, duration_seconds=3), Scene(text="Curved handle.", duration_seconds=3),
                                 Scene(text="Explore the collection", duration_seconds=3)],
                         disclaimer_or_assumptions="Review.")


def test_slideshow_opens_with_the_hook():
    scenes = renderer.slideshow_scenes(content())
    assert scenes[0] == ("Glossy. Curved. Quiet.", renderer.HOOK_SECONDS)
    assert [text for text, _ in scenes[1:]] == ["Glossy finish.", "Curved handle.", "Explore the collection"]


def test_slideshow_does_not_repeat_a_hook_already_on_the_first_scene():
    scenes = renderer.slideshow_scenes(content(hook="Glossy finish!", first="glossy finish."))
    assert len(scenes) == 3


@pytest.mark.parametrize("hook,first", [("Not for sale. Just for show.", "Not for sale."),
                                        ("Quiet.", "Quiet design, glossy finish.")])
def test_slideshow_skips_a_hook_that_the_first_scene_overlaps(hook, first):
    # Seen live: the model split its hook across the opening scenes, so a hook card repeated them.
    assert len(renderer.slideshow_scenes(content(hook=hook, first=first))) == 3


def test_headlines_use_a_bold_face_when_available():
    bold = [path for path in renderer.BOLD_FONTS if Path(path).is_file()]
    if not bold:
        pytest.skip("no bold system font installed")
    assert "bold" in " ".join(renderer.font(40, bold=True).getname()).lower()


def alpha_rows(layer: Image.Image) -> tuple[int, int]:
    _, top, _, bottom = layer.split()[-1].getbbox()
    return top, bottom - 1


@pytest.mark.parametrize("platform,format", [("tiktok", "video"), ("instagram", "reel"), ("youtube", "shorts")])
def test_vertical_video_overlays_stay_inside_platform_safe_zones(platform, format):
    output = get_format(platform, format)
    top, _ = alpha_rows(renderer.overlay_image(output, "Clean lines. Quiet confidence.", "top"))
    _, bottom = alpha_rows(renderer.overlay_image(output, "Explore the collection", "bottom", accent=True))
    # Top tabs/status bar cover roughly the first 10%; caption, username and music rows the last ~20%.
    assert top >= output.height * 0.1
    assert bottom <= output.height * 0.8


def test_overlay_text_is_large_enough_to_read_on_a_phone():
    output = get_format("tiktok", "video")
    first, last = alpha_rows(renderer.overlay_image(output, "Hi", "top"))
    assert last - first >= output.width * 0.08


def white_text_span(image: Image.Image, box) -> float:
    """Vertical extent of near-white (headline) pixels inside box, as a fraction of image height."""
    masks = [band.point(lambda v: 255 if v > 235 else 0) for band in image.crop(box).convert("RGB").split()]
    bbox = ImageChops.darker(ImageChops.darker(masks[0], masks[1]), masks[2]).getbbox()
    return (bbox[3] - bbox[1]) / image.height if bbox else 0.0


def test_thumbnail_headline_is_large(tmp_path):
    output = get_format("youtube", "thumbnail")
    product = tmp_path / "product.jpg"
    Image.new("RGB", (800, 600), "#333333").save(product)
    poster = renderer.compose_frame(output, str(product), "Glossy. Curved. Quiet.", "", cta="Explore the collection")
    # A thumbnail is seen at ~300 px wide, so the headline should own a large part of its column.
    assert white_text_span(poster, (0, 0, output.width // 2, output.height)) >= 0.2


def test_portrait_headline_fills_its_band(tmp_path):
    output = get_format("instagram", "feed_portrait")
    product = tmp_path / "product.jpg"
    Image.new("RGB", (600, 800), "#333333").save(product)
    poster = renderer.compose_frame(output, str(product), "Studio sample. Demo only.", "", cta="Explore the collection")
    band = (0, layout(output).card_area[3], output.width, output.height)
    assert white_text_span(poster, band) >= 0.06


def test_template_video_starts_and_ends_on_a_clean_frame(tmp_path):
    # Seen in Safari: the last scene faded to black, so the ended player (and the pre-play
    # first frame) showed a near-black picture.
    import subprocess
    from uuid import uuid4
    from PIL import ImageStat
    output = get_format("instagram", "reel")
    product = tmp_path / "product.jpg"
    Image.new("RGB", (800, 600), "#d9c4a0").save(product)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    video, _ = renderer.render_slideshow(tmp_path, scratch, output, str(product), content(), {}, uuid4())

    def brightness(*seek: str) -> float:
        frame = tmp_path / "frame.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", *seek, "-i", str(video), "-frames:v", "1", str(frame)], check=True)
        with Image.open(frame) as image:
            return sum(ImageStat.Stat(image.convert("L")).mean)

    middle = brightness("-ss", "4")
    assert brightness() >= middle * 0.9
    assert brightness("-sseof", "-0.05") >= middle * 0.9
