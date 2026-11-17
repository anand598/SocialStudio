"""Optional background music for video outputs.

Image -> promo video: the track is trimmed or padded to length, loudness-normalized, and faded.
Video input: the music is mixed quietly under the clip's own sound.
"""
import re
import subprocess
from uuid import UUID
import pytest
from app.core.config import get_settings
from app.models.job import GenerationJob
from app.services.media.ffmpeg import probe
from app.services.storage.local import job_directory
from app.workers.tasks import generate
from test_formats import output_of, submit_video, video_bytes  # noqa: F401  (fixture)


def tone(tmp_path, suffix=".m4a", seconds=3, frequency=660):
    path = tmp_path / f"music{suffix}"
    codec = {".m4a": ["-c:a", "aac"], ".mp3": ["-c:a", "libmp3lame"], ".wav": ["-c:a", "pcm_s16le"]}[suffix]
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency={frequency}:duration={seconds}",
                    *codec, str(path)], check=True)
    return path.read_bytes()


MIME = {".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav"}


def submit_with_music(client, image_bytes, music, *, suffix=".m4a", mime=None, format="reel", platform="instagram"):
    return client.post("/api/v1/generations", data={"platform": platform, "format": format},
                       files={"file": ("product.png", image_bytes, "image/png"),
                              "music": (f"track{suffix}", music, mime or MIME[suffix])})


def mean_volume(path, start, seconds=1.0) -> float:
    result = subprocess.run(["ffmpeg", "-v", "info", "-ss", str(start), "-t", str(seconds), "-i", str(path),
                             "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True, check=True)
    return float(re.search(r"mean_volume: (-?[\d.]+) dB", result.stderr).group(1))


@pytest.mark.parametrize("suffix", [".m4a", ".mp3", ".wav"])
def test_music_is_stored_for_video_formats(client, image_bytes, tmp_path, suffix):
    response = submit_with_music(client, image_bytes, tone(tmp_path, suffix), suffix=suffix)
    assert response.status_code == 202, response.json()
    assert response.json()["has_music"] is True
    with client.session_factory() as session:
        job = session.get(GenerationJob, UUID(response.json()["id"]))
        assert job.music_path and job.music_path.endswith(suffix)
        assert job.music_path.startswith(str(job_directory(job.id)))


def test_music_is_refused_for_image_formats(client, image_bytes, tmp_path):
    response = submit_with_music(client, image_bytes, tone(tmp_path), format="feed_square")
    assert response.status_code == 422
    assert "video formats" in response.json()["detail"]


def test_invalid_music_is_rejected_and_cleaned_up(client, image_bytes, tmp_path, monkeypatch):
    media = job_directory("00000000-0000-4000-8000-000000000000").parent
    def leftovers():
        return set(media.iterdir()) if media.exists() else set()
    before = leftovers()
    assert submit_with_music(client, image_bytes, b"not audio", suffix=".mp3").status_code == 422
    assert submit_with_music(client, image_bytes, tone(tmp_path), mime="text/plain").status_code == 415
    monkeypatch.setattr(get_settings(), "max_music_seconds", 1)
    assert submit_with_music(client, image_bytes, tone(tmp_path)).status_code == 422
    monkeypatch.setattr(get_settings(), "max_music_upload_size_mb", 0)
    assert submit_with_music(client, image_bytes, tone(tmp_path)).status_code == 413
    assert leftovers() == before


def test_promo_video_gets_the_music_for_its_full_length(client, image_bytes, tmp_path, monkeypatch):
    monkeypatch.setattr("app.workers.tasks.SessionLocal", client.session_factory)
    job_id = submit_with_music(client, image_bytes, tone(tmp_path, seconds=3)).json()["id"]
    generate.run(job_id)
    assert client.get(f"/api/v1/generations/{job_id}").json()["status"] == "completed"
    output = output_of(job_id)
    metadata = probe(output)
    audio = [s for s in metadata["streams"] if s["codec_type"] == "audio"]
    assert len(audio) == 1 and audio[0]["codec_name"] == "aac"
    duration = float(metadata["format"]["duration"])
    assert abs(float(audio[0]["duration"]) - duration) < 0.3   # short tracks are padded, not cut short
    assert mean_volume(output, 1.0) > -35                      # the music is audible
    assert mean_volume(output, 0.0, 0.08) < mean_volume(output, 1.0) - 6   # and fades in


def test_video_input_mixes_music_under_its_own_sound(client, video_bytes, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr("app.workers.tasks.SessionLocal", client.session_factory)
    response = client.post("/api/v1/generations",
                           data={"platform": "tiktok", "format": "video", "input_type": "video"},
                           files={"file": ("clip.mp4", video_bytes, "video/mp4"),
                                  "music": ("track.m4a", tone(tmp_path, seconds=10, frequency=880), "audio/mp4")})
    job_id = response.json()["id"]
    generate.run(job_id)
    assert client.get(f"/api/v1/generations/{job_id}").json()["status"] == "completed"
    metadata = probe(output_of(job_id))
    audio = [s for s in metadata["streams"] if s["codec_type"] == "audio"]
    assert len(audio) == 1
    assert abs(float(metadata["format"]["duration"]) - 4) < 0.5   # music never extends the clip


def test_jobs_without_music_report_it(client, image_bytes):
    response = client.post("/api/v1/generations", data={"platform": "instagram", "format": "reel"},
                           files={"file": ("product.png", image_bytes, "image/png")})
    assert response.json()["has_music"] is False


def test_config_exposes_music_limits(client):
    config = client.get("/api/v1/config/platforms").json()
    assert config["max_music_upload_size_mb"] == get_settings().max_music_upload_size_mb
    assert config["max_music_seconds"] == get_settings().max_music_seconds
