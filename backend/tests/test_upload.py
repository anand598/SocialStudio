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
    response = client.post("/api/v1/generations", content=iter([b"x" * (2 * 1024 * 1024)]),
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
