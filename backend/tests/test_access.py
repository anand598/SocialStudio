"""Job results are visible only to the browser that created them.

A job URL alone is not enough: the creating browser holds an HttpOnly owner cookie whose hash is
stored on the job. Strangers get the same 404 as a missing job, so existence is not revealed.
"""
from uuid import UUID
from app.api.generations import OWNER_COOKIE, owner_hash
from app.models.job import GenerationJob


def submit(client, image_bytes):
    return client.post("/api/v1/generations", data={"platform": "instagram", "format": "feed_square"},
                       files={"file": ("product.png", image_bytes, "image/png")})


def test_creation_sets_httponly_owner_cookie(client, image_bytes):
    response = submit(client, image_bytes)
    assert response.status_code == 202
    header = response.headers["set-cookie"]
    assert header.startswith(f"{OWNER_COOKIE}=")
    assert "httponly" in header.lower() and "samesite=lax" in header.lower()
    token = client.cookies.get(OWNER_COOKIE)
    assert token and len(token) >= 40
    with client.session_factory() as session:
        job = session.get(GenerationJob, UUID(response.json()["id"]))
        assert job.owner_hash == owner_hash(token) and token not in job.owner_hash


def test_owner_cookie_is_reused_across_jobs(client, image_bytes):
    first = submit(client, image_bytes).json()["id"]
    token = client.cookies.get(OWNER_COOKIE)
    second = submit(client, image_bytes).json()["id"]
    assert client.cookies.get(OWNER_COOKIE) == token
    assert client.get(f"/api/v1/generations/{first}").status_code == 200
    assert client.get(f"/api/v1/generations/{second}").status_code == 200


def test_other_browsers_cannot_see_or_retry_a_job(client, image_bytes):
    job_id = submit(client, image_bytes).json()["id"]
    owner = client.cookies.get(OWNER_COOKIE)
    missing = client.get("/api/v1/generations/00000000-0000-4000-8000-000000000000").json()
    for cookies in ({}, {OWNER_COOKIE: "x" * 43}):
        client.cookies.clear()
        client.cookies.update(cookies)
        for path in ("", "/content", "/preview", "/download", "/thumbnail"):
            response = client.get(f"/api/v1/generations/{job_id}{path}")
            assert response.status_code == 404, path
            assert response.json() == missing
        assert client.post(f"/api/v1/generations/{job_id}/retry").status_code == 404
    client.cookies.clear()
    client.cookies.set(OWNER_COOKIE, owner)
    assert client.get(f"/api/v1/generations/{job_id}").status_code == 200


def test_jobs_without_an_owner_are_not_served(client, image_bytes):
    job_id = submit(client, image_bytes).json()["id"]
    with client.session_factory() as session:
        session.get(GenerationJob, UUID(job_id)).owner_hash = None
        session.commit()
    assert client.get(f"/api/v1/generations/{job_id}").status_code == 404


def test_malformed_owner_cookie_is_replaced(client, image_bytes):
    client.cookies.set(OWNER_COOKIE, "short")
    response = submit(client, image_bytes)
    token = response.cookies.get(OWNER_COOKIE)
    assert token != "short" and len(token) >= 40
    client.cookies.clear()
    client.cookies.set(OWNER_COOKIE, token)
    assert client.get(f"/api/v1/generations/{response.json()['id']}").status_code == 200


def test_secure_cookie_flag_follows_settings(client, image_bytes, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "cookie_secure", True)
    header = submit(client, image_bytes).headers["set-cookie"].lower()
    assert "; secure" in header
