"""Brand kit: an optional brand colour and logo, applied to every output path.

Without them, the palette still comes from the product photo and the brand name is set as text.
"""
import io
import subprocess
from uuid import UUID
import pytest
from PIL import Image
from app.core.config import get_settings
from app.core.platforms import get_format
from app.models.job import GenerationJob
from app.services.media import promo, renderer
from app.services.storage.local import job_directory
from app.workers.tasks import generate
from test_formats import output_of, video_bytes  # noqa: F401  (fixture)
from test_promo import scenes, textured

ORANGE = (228, 87, 46)
NAVY = (26, 35, 126)


def logo_png(colour=(220, 20, 20), size=(300, 120), margin=30) -> bytes:
    """A solid logo on a transparent canvas with empty margins (which should be trimmed)."""
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    image.paste(Image.new("RGBA", (size[0] - margin * 2, size[1] - margin * 2), (*colour, 255)), (margin, margin))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def submit(client, image_bytes, *, data=None, logo=None, format="feed_square"):
    files = {"file": ("product.png", image_bytes, "image/png")}
    if logo is not None:
        files["logo"] = logo
    return client.post("/api/v1/generations", data={"platform": "instagram", "format": format, **(data or {})},
                       files=files)


def close(pixel, colour, tolerance=12):
    return all(abs(a - b) <= tolerance for a, b in zip(pixel[:3], colour))


# ---------- API and storage ----------

def test_brand_colour_is_validated_and_normalised(client, image_bytes):
    response = submit(client, image_bytes, data={"brand_color": "#e4572e"})
    assert response.status_code == 202
    with client.session_factory() as session:
        job = session.get(GenerationJob, UUID(response.json()["id"]))
        assert job.brand_context["brand_color"] == "#E4572E"
    for bad in ("red", "#12345", "#1234567", "e4572e", "#GG0000"):
        assert submit(client, image_bytes, data={"brand_color": bad}).status_code == 422, bad


def test_brand_colour_is_optional(client, image_bytes):
    response = submit(client, image_bytes)
    with client.session_factory() as session:
        assert session.get(GenerationJob, UUID(response.json()["id"])).brand_context.get("brand_color") is None


def test_logo_is_stored_with_transparency_and_trimmed(client, image_bytes):
    response = submit(client, image_bytes, logo=("logo.png", logo_png(), "image/png"))
    assert response.status_code == 202, response.json()
    assert response.json()["has_logo"] is True
    with client.session_factory() as session:
        job = session.get(GenerationJob, UUID(response.json()["id"]))
        assert job.logo_path.startswith(str(job_directory(job.id)))
    with Image.open(job.logo_path) as stored:
        assert stored.format == "PNG" and stored.mode == "RGBA"
        assert stored.size == (240, 60)                     # transparent margins trimmed
        assert not stored.info.get("exif")


def test_jobs_without_a_logo_report_it(client, image_bytes):
    assert submit(client, image_bytes).json()["has_logo"] is False


def test_invalid_logos_are_rejected_and_cleaned_up(client, image_bytes, monkeypatch):
    media = job_directory("00000000-0000-4000-8000-000000000000").parent
    def leftovers():
        return set(media.iterdir()) if media.exists() else set()
    before = leftovers()
    assert submit(client, image_bytes, logo=("logo.png", b"not an image", "image/png")).status_code == 422
    assert submit(client, image_bytes, logo=("logo.gif", logo_png(), "image/gif")).status_code == 415
    assert submit(client, image_bytes, logo=("logo.jpg", logo_png(), "image/png")).status_code == 415
    blank = io.BytesIO()
    Image.new("RGBA", (200, 200), (0, 0, 0, 0)).save(blank, "PNG")
    assert submit(client, image_bytes, logo=("logo.png", blank.getvalue(), "image/png")).status_code == 422
    monkeypatch.setattr(get_settings(), "max_logo_upload_size_mb", 0)
    assert submit(client, image_bytes, logo=("logo.png", logo_png(), "image/png")).status_code == 413
    assert leftovers() == before


def test_config_exposes_logo_limit(client):
    assert client.get("/api/v1/config/platforms").json()["max_logo_upload_size_mb"] == \
        get_settings().max_logo_upload_size_mb


# ---------- rendering ----------

def test_label_colour_contrasts_with_the_fill():
    assert promo.text_on(NAVY) == (255, 255, 255)
    assert promo.text_on((216, 237, 158)) == promo.INK
    assert promo.text_on(ORANGE) in {(255, 255, 255), promo.INK}


def test_brand_colour_fills_the_cta_button(tmp_path):
    video = promo.Promo(get_format("instagram", "reel"), textured(tmp_path / "p.jpg"), scenes(),
                        brand="Sunday Supply", cta="Explore the collection", brand_color="#E4572E")
    end = video.frame(video.duration - 0.05)
    pill = video.cta_box
    assert close(end.getpixel(((pill[0] + pill[2]) // 2, pill[1] + 4)), ORANGE)


def test_brand_colour_tints_the_backdrop(tmp_path):
    grey = tmp_path / "grey.png"
    Image.new("RGB", (800, 800), (128, 128, 128)).save(grey)
    output = get_format("instagram", "feed_portrait")
    blue = renderer.compose_frame(output, str(grey), "Headline", "", cta="Shop", brand_color="#1E88E5")
    r, g, b = blue.getpixel((12, output.height // 3))
    assert b > r + 15, "backdrop should carry the brand's blue"
    orange = renderer.compose_frame(output, str(grey), "Headline", "", cta="Shop", brand_color="#E4572E")
    r, g, b = orange.getpixel((12, output.height // 3))
    assert r > b + 15, "backdrop should carry the brand's orange"


def test_dark_brand_colour_keeps_the_brand_name_readable(tmp_path):
    video = promo.Promo(get_format("instagram", "reel"), textured(tmp_path / "p.jpg"), scenes(),
                        brand="Night Owl", cta="Shop", brand_color="#1A237E")
    rgb, mask, _ = video._brand
    ink = [rgb.getpixel(xy) for xy in ((x, y) for x in range(rgb.width) for y in range(rgb.height))
           if mask.getpixel(xy) == 255]
    assert ink and min(sum(p) / 3 for p in ink) > 180


def test_logo_takes_the_brand_name_position(tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(logo_png())
    output = get_format("instagram", "feed_square")
    poster = renderer.compose_frame(output, textured(tmp_path / "p.jpg"), "Headline", "Sunday Supply", cta="Shop",
                                    logo=str(logo))
    x, y = promo.layout(output).brand
    assert close(poster.getpixel((x + 6, y + 6)), (220, 20, 20), tolerance=20)
    video = promo.Promo(output, textured(tmp_path / "p.jpg"), scenes(), brand="Sunday Supply", cta="Shop",
                        logo=str(logo))
    left, top, right, bottom = video.logo_box
    assert (left, top) == (x, y)
    assert 0 < bottom - top <= round(min(output.width, output.height) * 0.09)
    assert right - left <= output.width * 0.4
    assert abs((right - left) / (bottom - top) - 4.0) < 0.1      # aspect preserved (240 × 60)


def test_video_overlays_use_brand_colour_and_logo(tmp_path):
    output = get_format("tiktok", "video")
    cta = renderer.overlay_image(output, "Shop now", "bottom", accent=True, accent_colour=ORANGE)
    box = cta.getbbox()
    assert close(cta.getpixel((box[0] + 30, (box[1] + box[3]) // 2)), ORANGE)
    logo = tmp_path / "logo.png"
    logo.write_bytes(logo_png())
    layer = renderer.logo_overlay(output, str(logo))
    margin = round(min(output.width, output.height) * 0.06)
    assert layer.size == (output.width, output.height)
    assert close(layer.getpixel((margin + 6, round(output.height * 0.1) + 6)), (220, 20, 20), tolerance=20)
    assert layer.getpixel((output.width - 5, output.height - 5))[3] == 0


# ---------- end to end through the worker ----------

def test_poster_carries_brand_colour_and_logo_end_to_end(client, image_bytes, monkeypatch):
    monkeypatch.setattr("app.workers.tasks.SessionLocal", client.session_factory)
    response = submit(client, image_bytes, data={"brand_color": "#E4572E", "brand_name": "Sunday Supply"},
                      logo=("logo.png", logo_png(), "image/png"))
    job_id = response.json()["id"]
    generate.run(job_id)
    assert client.get(f"/api/v1/generations/{job_id}").json()["status"] == "completed"
    output = get_format("instagram", "feed_square")
    x, y = promo.layout(output).brand
    with Image.open(output_of(job_id)) as poster:
        assert close(poster.convert("RGB").getpixel((x + 6, y + 6)), (220, 20, 20), tolerance=25)


def test_reframed_video_carries_the_logo_end_to_end(client, video_bytes, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr("app.workers.tasks.SessionLocal", client.session_factory)
    response = client.post("/api/v1/generations",
                           data={"platform": "tiktok", "format": "video", "input_type": "video",
                                 "brand_color": "#E4572E"},
                           files={"file": ("clip.mp4", video_bytes, "video/mp4"),
                                  "logo": ("logo.png", logo_png(), "image/png")})
    job_id = response.json()["id"]
    generate.run(job_id)
    assert client.get(f"/api/v1/generations/{job_id}").json()["status"] == "completed"
    frame = tmp_path / "frame.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", str(output_of(job_id)), "-frames:v", "1",
                    str(frame)], check=True)
    output = get_format("tiktok", "video")
    margin = round(min(output.width, output.height) * 0.06)
    with Image.open(frame) as still:
        assert close(still.convert("RGB").getpixel((margin + 6, round(output.height * 0.1) + 6)), (220, 20, 20),
                     tolerance=30)
