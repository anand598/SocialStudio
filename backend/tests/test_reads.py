"""Status reads stay cheap: polling never writes unless the job being read has actually gone stale.

The UI polls a running job every second or so, and every poll used to run the stuck-job sweep, an UPDATE
over the whole jobs table plus a commit. Now a read only checks the rows it returns, and the global sweep
is left to the scheduler (every minute). The create endpoint is async, so its database work runs in a
worker thread rather than on the event loop.
"""
import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID
from sqlalchemy import event
from app.core.config import get_settings
from app.models.job import GenerationJob
from app.services import outbox


def submit(client, image_bytes):
    response = client.post("/api/v1/generations", data={"platform": "instagram", "format": "feed_square"},
                           files={"file": ("product.png", image_bytes, "image/png")})
    assert response.status_code == 202
    return response.json()["id"]


def make_stale(client, job_id, status="processing"):
    with client.session_factory() as session:
        job = session.get(GenerationJob, UUID(job_id))
        job.status = status
        job.updated_at = datetime.now(timezone.utc) - timedelta(seconds=get_settings().stale_job_seconds + 60)
        session.commit()


@contextmanager
def writes(client):
    """Collects the UPDATE statements issued while the block runs."""
    seen = []
    engine = client.session_factory.kw["bind"]
    def listener(conn, cursor, statement, *args):
        if statement.lstrip().upper().startswith("UPDATE"):
            seen.append(statement)
    event.listen(engine, "before_cursor_execute", listener)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", listener)


def test_polling_a_healthy_job_does_not_write(client, image_bytes):
    job_id = submit(client, image_bytes)
    with writes(client) as updates:
        for _ in range(3):
            assert client.get(f"/api/v1/generations/{job_id}").status_code == 200
        assert client.get("/api/v1/generations").status_code == 200
    assert updates == []


def test_reading_a_stuck_job_still_reports_it_expired(client, image_bytes):
    job_id = submit(client, image_bytes)
    make_stale(client, job_id)
    body = client.get(f"/api/v1/generations/{job_id}").json()
    assert body["status"] == "failed" and body["error_code"] == "JOB_EXPIRED"


def test_a_job_stuck_in_the_queue_expires_on_read(client, image_bytes):
    job_id = submit(client, image_bytes)
    make_stale(client, job_id, status="queued")
    assert client.get(f"/api/v1/generations/{job_id}").json()["error_code"] == "JOB_EXPIRED"


def test_history_reports_stuck_jobs_as_expired(client, image_bytes):
    stuck, fine = submit(client, image_bytes), submit(client, image_bytes)
    make_stale(client, stuck)
    items = {item["id"]: item for item in client.get("/api/v1/generations").json()["items"]}
    assert items[stuck]["status"] == "failed" and items[stuck]["stage"] == "failed"
    assert items[fine]["status"] == "queued"


def test_a_read_only_touches_the_job_it_returns(client, image_bytes):
    mine, other = submit(client, image_bytes), submit(client, image_bytes)
    make_stale(client, other)
    client.get(f"/api/v1/generations/{mine}")
    with client.session_factory() as session:
        assert session.get(GenerationJob, UUID(other)).status == "processing"   # left to the scheduler


def test_a_job_finishing_meanwhile_is_not_overwritten(client, image_bytes, monkeypatch):
    # The read saw a stale row, but the worker completed it before the expiry update ran.
    job_id = submit(client, image_bytes)
    make_stale(client, job_id)
    from app.api import generations
    real = generations.expire_if_stale
    def finish_first(session, jobs):
        with client.session_factory() as other:
            row = other.get(GenerationJob, UUID(job_id))
            row.status, row.stage, row.updated_at = "completed", "completed", datetime.now(timezone.utc)
            other.commit()
        return real(session, jobs)
    monkeypatch.setattr(generations, "expire_if_stale", finish_first)
    assert client.get(f"/api/v1/generations/{job_id}").json()["status"] == "completed"


def test_create_does_its_database_work_off_the_event_loop(client, image_bytes, monkeypatch):
    loops = []
    real_add = outbox.add
    def add(session, job_id, *args, **kwargs):
        try:
            asyncio.get_running_loop()
            loops.append("event loop")
        except RuntimeError:
            loops.append("worker thread")
        return real_add(session, job_id, *args, **kwargs)
    monkeypatch.setattr(outbox, "add", add)
    submit(client, image_bytes)
    assert loops == ["worker thread"]
