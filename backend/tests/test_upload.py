from pathlib import Path
from app.core.config import get_settings


def submit(client, content, mime="image/png", filename="product.png", **extra):
    return client.post("/api/v1/generations", files={"file": (filename, content, mime)},
                       data={"platform": "instagram", "format": "reel", **extra})


def test_valid_upload_is_persisted_and_normalized(client, image_bytes):
    response = submit(client, image_bytes, brand_name="Example")
    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "queued"
    assert job["generation_mode"] == "demo"
    assert "input_file_path" not in job
    assert client.get(f"/api/v1/generations/{job['id']}").json()["id"] == job["id"]
    assert (Path(get_settings().local_storage_path) / job["id"] / "input.jpg").exists()


def test_invalid_type_and_extension(client, image_bytes):
    assert submit(client, image_bytes, mime="text/plain").status_code == 415
    assert submit(client, image_bytes, filename="product.svg").status_code == 415


def test_malformed_or_mismatched_image(client, image_bytes):
    assert submit(client, b"not an image").status_code == 422
    assert submit(client, image_bytes, mime="image/jpeg", filename="product.jpg").status_code == 422


def test_upload_size_limit(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_size_mb", 1)
    assert submit(client, b"x" * (1024 * 1024 + 1)).status_code == 413


def test_unsupported_format(client, image_bytes):
    assert submit(client, image_bytes, format="square").status_code == 422
    assert client.get("/api/v1/generations/00000000-0000-0000-0000-000000000001").status_code == 404


def test_streamed_request_size_limit(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_size_mb", 1)
    monkeypatch.setattr(get_settings(), "max_video_upload_size_mb", 1)
    monkeypatch.setattr(get_settings(), "max_music_upload_size_mb", 1)
    monkeypatch.setattr(get_settings(), "max_logo_upload_size_mb", 1)
    # Limit: 1 (file) + 1 (music) + 1 (logo) + 1 (form overhead) = 4 MB; stream 6 MB without a length.
    response = client.post("/api/v1/generations", content=iter([b"x" * (6 * 1024 * 1024)]),
                           headers={"Content-Type": "multipart/form-data; boundary=test"})
    assert response.status_code == 413


def test_rate_limit(client, image_bytes, monkeypatch):
    monkeypatch.setattr(get_settings(), "requests_per_minute", 1)
    # Use a fresh client address to avoid other tests' requests.
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, client=("rate-test", 123)) as limited:
        assert submit(limited, image_bytes).status_code == 202
        assert submit(limited, image_bytes).status_code == 429


def test_proxies_pass_the_largest_request_the_api_accepts():
    # The browser uploads through Next.js (and Caddy in the public deployment). If either proxy's
    # body limit is below the API's, a valid upload is cut off mid-request and fails with a 500
    # instead of reaching the API's validation; this happened once with Next's 10 MB default.
    import re
    from pathlib import Path
    from app.core.config import get_settings
    from app.core.limits import request_size_limit
    root = Path(__file__).resolve().parents[2]
    settings = get_settings()
    largest = max(settings.max_upload_size_mb, settings.max_video_upload_size_mb)
    needed = (largest + settings.max_music_upload_size_mb + settings.max_logo_upload_size_mb) * 1024 * 1024
    limit = request_size_limit(settings)
    assert limit >= needed  # a maximum file, track and logo together are accepted
    next_mb = int(re.search(r'middlewareClientMaxBodySize:\s*"(\d+)mb"', (root / "frontend/next.config.mjs").read_text()).group(1))
    caddy_mb = int(re.search(r"max_size (\d+)MB", (root / "infrastructure/Caddyfile").read_text()).group(1))
    assert limit <= next_mb * 1024 * 1024 and limit <= caddy_mb * 1024 * 1024
