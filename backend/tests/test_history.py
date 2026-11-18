"""Job history: a browser can list the jobs it created, and only those."""
from datetime import datetime, timedelta, timezone
from uuid import UUID
from app.api.generations import OWNER_COOKIE
from app.models.job import GenerationJob

HISTORY = "/api/v1/generations"


def submit(client, image_bytes, platform="instagram", format="feed_square"):
    response = client.post(HISTORY, data={"platform": platform, "format": format},
                           files={"file": ("product.png", image_bytes, "image/png")})
    assert response.status_code == 202
    return response.json()["id"]


def set_job(client, job_id, **fields):
    with client.session_factory() as session:
        job = session.get(GenerationJob, UUID(job_id))
        for name, value in fields.items():
            setattr(job, name, value)
        session.commit()


def test_history_lists_own_jobs_newest_first(client, image_bytes):
    base = datetime(2026, 11, 1, tzinfo=timezone.utc)
    oldest = submit(client, image_bytes)
    newest = submit(client, image_bytes, "tiktok", "video")
    middle = submit(client, image_bytes, "youtube", "thumbnail")
    for offset, job_id in enumerate((oldest, middle, newest)):
        set_job(client, job_id, created_at=base + timedelta(minutes=offset))
    items = client.get(HISTORY).json()["items"]
    assert [item["id"] for item in items] == [newest, middle, oldest]
    assert items[0]["platform"] == "tiktok" and items[0]["format"] == "video"
    assert items[0]["output_kind"] == "video" and items[1]["output_kind"] == "image"
    assert items[0]["status"] == "queued" and items[0]["input_type"] == "image"


def test_history_excludes_other_browsers_jobs(client, image_bytes):
    mine = submit(client, image_bytes)
    owner = client.cookies.get(OWNER_COOKIE)
    client.cookies.clear()
    theirs = submit(client, image_bytes)
    assert [item["id"] for item in client.get(HISTORY).json()["items"]] == [theirs]
    client.cookies.clear()
    client.cookies.set(OWNER_COOKIE, owner)
    assert [item["id"] for item in client.get(HISTORY).json()["items"]] == [mine]


def test_history_without_owner_cookie_is_empty_and_sets_no_cookie(client, image_bytes):
    submit(client, image_bytes)
    client.cookies.clear()
    response = client.get(HISTORY)
    assert response.status_code == 200
    assert response.json() == {"items": []}
    assert "set-cookie" not in response.headers


def test_history_respects_limit(client, image_bytes):
    for _ in range(3):
        submit(client, image_bytes)
    assert len(client.get(HISTORY, params={"limit": 2}).json()["items"]) == 2
    assert client.get(HISTORY, params={"limit": 0}).status_code == 422
    assert client.get(HISTORY, params={"limit": 51}).status_code == 422


def test_history_headline_comes_from_generated_copy(client, image_bytes):
    hooked = submit(client, image_bytes)
    titled = submit(client, image_bytes, "youtube", "video")
    pending = submit(client, image_bytes)
    set_job(client, hooked, status="completed", generated_content={"hook": "Pour slower", "title": ""})
    set_job(client, titled, status="completed", generated_content={"hook": "Hook", "title": "Desk tour"})
    headlines = {item["id"]: item["headline"] for item in client.get(HISTORY).json()["items"]}
    assert headlines == {hooked: "Pour slower", titled: "Desk tour", pending: None}


def test_history_omits_heavy_fields(client, image_bytes):
    job_id = submit(client, image_bytes)
    set_job(client, job_id, status="completed", generated_content={"hook": "H", "caption": "long caption"},
            product_analysis={"product_category": "mug"})
    item = client.get(HISTORY).json()["items"][0]
    assert not {"generated_content", "product_analysis", "post_text"} & item.keys()
