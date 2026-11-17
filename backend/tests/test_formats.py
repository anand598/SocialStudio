"""Every registered format renders at its exact platform dimensions, from images and videos."""
import subprocess
from uuid import UUID
import pytest
from PIL import Image
from app.core.platforms import SUPPORTED_FORMATS, compose_post_text, get_format
from app.services.media.ffmpeg import probe, video_stream
from app.services.storage.local import job_directory
from app.workers.tasks import generate
from test_upload import submit


@pytest.fixture
def video_bytes(tmp_path):
    """A 4-second landscape H.264 clip with an audio track."""
    path = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=4",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(path)], check=True)
    return path.read_bytes()


def submit_video(client, content, platform="tiktok", format="video", **extra):
    return client.post("/api/v1/generations", files={"file": ("clip.mp4", content, "video/mp4")},
                       data={"platform": platform, "format": format, "input_type": "video", **extra})


def output_of(job_id):
    return next(job_directory(job_id).glob("output-*.*"))


def test_registry_covers_each_platform_with_correct_dimensions():
    dims = {(f.platform, f.format): (f.width, f.height, f.kind) for f in SUPPORTED_FORMATS}
    assert dims[("instagram", "reel")] == (1080, 1920, "video")
    assert dims[("instagram", "feed_portrait")] == (1080, 1350, "image")
    assert dims[("instagram", "feed_square")] == (1080, 1080, "image")
    assert dims[("tiktok", "video")] == (1080, 1920, "video")
    assert dims[("youtube", "shorts")] == (1080, 1920, "video")
    assert dims[("youtube", "video")] == (1920, 1080, "video")
    assert dims[("youtube", "thumbnail")] == (1280, 720, "image")
    for item in SUPPORTED_FORMATS:
        w, h = (int(x) for x in item.aspect_ratio.split(":"))
        assert abs(item.width / item.height - w / h) < 0.01


def test_post_text_enforces_platform_hashtag_limits_and_title():
    content = {"title": "Desk lamp", "caption": "Meet the lamp.", "call_to_action": "Shop now",
               "hashtags": ["#One", "two", "#Three", "#Four", "#one", "#bad tag!"]}
    youtube = compose_post_text(get_format("youtube", "shorts"), content)
    assert youtube.startswith("Title: Desk lamp")
    assert youtube.endswith("#One #two #Three")  # YouTube: at most 3, deduplicated
    tiktok = compose_post_text(get_format("tiktok", "video"), content)
    assert "Title:" not in tiktok and tiktok.endswith("#One #two #Three #Four #badtag")
    long = compose_post_text(get_format("instagram", "reel"), {**content, "caption": "x" * 3000})
    assert len(long) == 2200


def test_config_exposes_formats_and_inputs(client):
    config = client.get("/api/v1/config/platforms").json()
    assert {f["platform"] for f in config["formats"]} == {"instagram", "tiktok", "youtube"}
    assert config["input_types"] == ["image", "video", "url"]
    assert "copy_guidance" not in config["formats"][0]


@pytest.mark.parametrize("platform,format", [("instagram", "feed_portrait"), ("instagram", "feed_square"),
                                              ("youtube", "thumbnail")])
def test_image_formats_render_exact_jpeg(client, image_bytes, monkeypatch, platform, format):
    monkeypatch.setattr("app.workers.tasks.SessionLocal", client.session_factory)
    job_id = submit(client, image_bytes, platform=platform, format=format).json()["id"]
    generate.run(job_id)
    job = client.get(f"/api/v1/generations/{job_id}").json()
    assert job["status"] == "completed", job
    assert job["output_kind"] == "image"
    response = client.get(f"/api/v1/generations/{job_id}/download")
    assert response.headers["content-type"] == "image/jpeg"
    assert f'{platform}-{format}-{job_id}.jpg' in response.headers["content-disposition"]
    expected = get_format(platform, format)
    with Image.open(output_of(job_id)) as image:
        assert image.format == "JPEG" and image.size == (expected.width, expected.height)
    assert job["post_text"]


def test_still_image_to_landscape_youtube_video(client, image_bytes, monkeypatch):
    monkeypatch.setattr("app.workers.tasks.SessionLocal", client.session_factory)
    job_id = submit(client, image_bytes, platform="youtube", format="video").json()["id"]
    generate.run(job_id)
    job = client.get(f"/api/v1/generations/{job_id}").json()
    assert job["status"] == "completed", job
    assert job["post_text"].startswith("Title: ")
    stream = video_stream(probe(output_of(job_id)))
    assert (stream["width"], stream["height"]) == (1920, 1080)


def test_video_upload_is_validated_and_keyframe_extracted(client, video_bytes):
    response = submit_video(client, video_bytes)
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["input_type"] == "video"
    directory = job_directory(job["id"])
    assert (directory / "source.mp4").exists() and (directory / "input.jpg").exists()


def test_invalid_video_uploads_are_rejected(client, video_bytes, image_bytes, monkeypatch):
    assert submit_video(client, b"not a video").status_code == 422
    assert client.post("/api/v1/generations", files={"file": ("clip.avi", video_bytes, "video/x-msvideo")},
                       data={"platform": "tiktok", "format": "video", "input_type": "video"}).status_code == 415
    # An image disguised as a video fails content validation.
    assert submit_video(client, image_bytes).status_code == 422
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "max_source_video_seconds", 2)
    assert submit_video(client, video_bytes).status_code == 422


@pytest.mark.parametrize("platform,format,size", [("tiktok", "video", (1080, 1920)), ("youtube", "video", (1920, 1080))])
def test_source_video_is_reframed_with_audio(client, video_bytes, monkeypatch, platform, format, size):
    monkeypatch.setattr("app.workers.tasks.SessionLocal", client.session_factory)
    job_id = submit_video(client, video_bytes, platform=platform, format=format, brand_name="Acme").json()["id"]
    generate.run(job_id)
    job = client.get(f"/api/v1/generations/{job_id}").json()
    assert job["status"] == "completed", job
    metadata = probe(output_of(job_id))
    stream = video_stream(metadata)
    assert (stream["width"], stream["height"]) == size
    assert any(s["codec_type"] == "audio" for s in metadata["streams"])
    assert abs(float(metadata["format"]["duration"]) - 4) < 0.5
    assert client.get(f"/api/v1/generations/{job_id}/thumbnail").status_code == 200


def test_video_input_to_image_format_uses_keyframe(client, video_bytes, monkeypatch):
    monkeypatch.setattr("app.workers.tasks.SessionLocal", client.session_factory)
    job_id = submit_video(client, video_bytes, platform="instagram", format="feed_square").json()["id"]
    generate.run(job_id)
    assert client.get(f"/api/v1/generations/{job_id}").json()["status"] == "completed"
    with Image.open(output_of(job_id)) as image:
        assert image.size == (1080, 1080)


def test_unknown_format_and_missing_file(client, image_bytes):
    assert submit(client, image_bytes, platform="tiktok", format="reel").status_code == 422
    response = client.post("/api/v1/generations", data={"platform": "tiktok", "format": "video", "input_type": "video"})
    assert response.status_code == 422


def test_video_upload_builds_time_ordered_storyboard(client, video_bytes):
    job_id = submit_video(client, video_bytes).json()["id"]
    with Image.open(job_directory(job_id) / "storyboard.jpg") as sheet:
        assert sheet.size == (1280, 1280)
        # Four distinct moments of a moving test pattern: quadrants must differ.
        quadrants = [sheet.crop((x, y, x + 640, y + 640)).tobytes() for y in (0, 640) for x in (0, 640)]
        assert len(set(quadrants)) == 4


def test_video_jobs_use_multi_frame_analysis(client, video_bytes, monkeypatch):
    from app.services.ai.provider import DemoProvider
    calls = []
    class Recording(DemoProvider):
        def analyze_product_video(self, storyboard_path):
            calls.append(("video", storyboard_path))
            return super().analyze_product_video(storyboard_path)
        def analyze_product_image(self, image_path):
            calls.append(("image", image_path))
            return super().analyze_product_image(image_path)
    monkeypatch.setattr("app.workers.tasks.get_provider", lambda mode: Recording())
    monkeypatch.setattr("app.workers.tasks.SessionLocal", client.session_factory)
    video_job = submit_video(client, video_bytes).json()["id"]
    generate.run(video_job)
    assert calls == [("video", str(job_directory(video_job) / "storyboard.jpg"))]
    job = client.get(f"/api/v1/generations/{video_job}").json()
    assert job["status"] == "completed"
    assert "video" in job["product_analysis"]["confidence_or_limitations"].lower()


def test_post_text_does_not_duplicate_hashtags_or_cta():
    tiktok = compose_post_text(get_format("tiktok", "video"), {
        "caption": "Studio vibes only. #SundaySupply #Minimal", "call_to_action": "Explore the collection",
        "hashtags": ["#SundaySupply", "#ProductShot"]})
    assert tiktok == "Studio vibes only.\n\nExplore the collection\n\n#SundaySupply #Minimal #ProductShot"
    youtube = compose_post_text(get_format("youtube", "thumbnail"), {
        "title": "Elegant Black Teapot", "caption": "Explore the collection", "call_to_action": "Explore the collection",
        "hashtags": ["#Teapot"]})
    assert youtube == "Title: Elegant Black Teapot\n\nExplore the collection\n\n#Teapot"
