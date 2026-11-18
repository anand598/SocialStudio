"""Media retention: stored inputs and outputs are deleted after a configurable period.

The job row and its generated text stay, so the owner still sees what was made and why the media
is gone; every media endpoint answers 410 Gone instead of a confusing 404 or a broken player.
"""
import os
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import pytest
from app.core.config import get_settings
from app.models.job import GenerationJob
from app.services.retention import purge_expired, purge_orphans
from app.services.storage.local import job_directory
from app.workers import tasks
from app.workers.celery_app import celery_app

EXPIRED = "This result has expired and its media was deleted. Create a new one."


def submit(client, image_bytes):
    response = client.post("/api/v1/generations", data={"platform": "instagram", "format": "feed_square"},
                           files={"file": ("product.png", image_bytes, "image/png")})
    assert response.status_code == 202
    return response.json()["id"]


def age(client, job_id, *, days, status="completed"):
    """Make a job look finished `days` ago, with an output and thumbnail on disk."""
    directory = job_directory(job_id)
    (directory / "output-x.jpg").write_bytes(b"jpeg")
    (directory / "thumbnail-x.jpg").write_bytes(b"jpeg")
    when = datetime.now(timezone.utc) - timedelta(days=days)
    with client.session_factory() as session:
        job = session.get(GenerationJob, UUID(job_id))
        job.status = job.stage = status
        job.progress = 100 if status == "completed" else 0
        job.generated_content = {"hook": "Pour slower", "title": "", "caption": "Kept caption", "call_to_action": "Shop",
                                 "hashtags": ["#A"], "scenes": [], "benefits": [], "short_description": "s",
                                 "disclaimer_or_assumptions": "d"}
        job.output_file_path = str(directory / "output-x.jpg")
        job.thumbnail_file_path = str(directory / "thumbnail-x.jpg")
        job.completed_at = job.updated_at = when
        session.commit()


@pytest.fixture
def retention(monkeypatch):
    monkeypatch.setattr(get_settings(), "media_retention_days", 30)


def test_old_finished_jobs_lose_their_media_but_keep_their_record(client, image_bytes, retention):
    old = submit(client, image_bytes)
    age(client, old, days=31)
    with client.session_factory() as session:
        assert purge_expired(session) == 1
    assert not job_directory(old).exists()
    with client.session_factory() as session:
        job = session.get(GenerationJob, UUID(old))
        assert job.purged_at is not None and job.status == "completed"
        assert job.generated_content["caption"] == "Kept caption"
        assert not any([job.input_file_path, job.output_file_path, job.thumbnail_file_path, job.logo_path,
                        job.music_path, job.source_media_path])


def test_recent_and_unfinished_jobs_are_kept(client, image_bytes, retention):
    recent = submit(client, image_bytes)
    age(client, recent, days=29)
    running = submit(client, image_bytes)
    with client.session_factory() as session:
        job = session.get(GenerationJob, UUID(running))
        job.status, job.updated_at = "processing", datetime.now(timezone.utc) - timedelta(days=90)
        session.commit()
    queued = submit(client, image_bytes)
    with client.session_factory() as session:
        assert purge_expired(session) == 0
    for job_id in (recent, running, queued):
        assert job_directory(job_id).exists()


def test_old_failed_jobs_are_purged_too(client, image_bytes, retention):
    failed = submit(client, image_bytes)
    age(client, failed, days=40, status="failed")
    with client.session_factory() as session:
        assert purge_expired(session) == 1
    assert not job_directory(failed).exists()


def test_zero_days_keeps_media_forever(client, image_bytes, monkeypatch):
    monkeypatch.setattr(get_settings(), "media_retention_days", 0)
    old = submit(client, image_bytes)
    age(client, old, days=3650)
    with client.session_factory() as session:
        assert purge_expired(session) == 0
    assert job_directory(old).exists()


def test_purging_is_idempotent_and_tolerates_missing_folders(client, image_bytes, retention):
    gone = submit(client, image_bytes)
    age(client, gone, days=31)
    for path in job_directory(gone).iterdir():
        path.unlink()
    job_directory(gone).rmdir()
    with client.session_factory() as session:
        assert purge_expired(session) == 1
        assert purge_expired(session) == 0


def test_expired_media_answers_410_and_text_stays_available(client, image_bytes, retention):
    old = submit(client, image_bytes)
    age(client, old, days=31)
    with client.session_factory() as session:
        purge_expired(session)
    status = client.get(f"/api/v1/generations/{old}").json()
    assert status["expired"] is True and status["status"] == "completed"
    for path in ("/preview", "/download", "/thumbnail"):
        response = client.get(f"/api/v1/generations/{old}{path}")
        assert response.status_code == 410, path
        assert response.json()["detail"] == EXPIRED
    assert client.post(f"/api/v1/generations/{old}/variants").status_code == 410
    assert client.get(f"/api/v1/generations/{old}/content").json()["content"]["caption"] == "Kept caption"
    assert client.get("/api/v1/generations").json()["items"][0]["expired"] is True


def test_expired_failed_jobs_cannot_be_retried(client, image_bytes, retention):
    failed = submit(client, image_bytes)
    age(client, failed, days=31, status="failed")
    with client.session_factory() as session:
        purge_expired(session)
    response = client.post(f"/api/v1/generations/{failed}/retry")
    assert response.status_code == 410 and response.json()["detail"] == EXPIRED


def test_live_jobs_report_not_expired(client, image_bytes):
    job_id = submit(client, image_bytes)
    assert client.get(f"/api/v1/generations/{job_id}").json()["expired"] is False
    assert client.get("/api/v1/generations").json()["items"][0]["expired"] is False


def test_strangers_still_get_404_for_expired_jobs(client, image_bytes, retention):
    old = submit(client, image_bytes)
    age(client, old, days=31)
    with client.session_factory() as session:
        purge_expired(session)
    client.cookies.clear()
    assert client.get(f"/api/v1/generations/{old}/preview").status_code == 404


def test_orphaned_job_folders_are_removed_after_a_day(client, image_bytes, retention):
    kept_job = submit(client, image_bytes)
    root = job_directory(kept_job).parent
    old_orphan, new_orphan, not_a_job = root / str(uuid4()), root / str(uuid4()), root / "queue"
    for folder in (old_orphan, new_orphan, not_a_job):
        folder.mkdir()
        (folder / "input.jpg").write_bytes(b"x")
    two_days_ago = time.time() - 2 * 86400
    for folder in (old_orphan, not_a_job, job_directory(kept_job)):
        os.utime(folder, (two_days_ago, two_days_ago))
    with client.session_factory() as session:
        assert purge_orphans(session) == 1
    assert not old_orphan.exists()
    assert new_orphan.exists() and not_a_job.exists() and job_directory(kept_job).exists()


def test_purge_runs_hourly_on_the_scheduler(client, image_bytes, retention, monkeypatch):
    schedule = celery_app.conf.beat_schedule
    entry = next(item for item in schedule.values() if item["task"] == "social.purge_expired")
    assert entry["schedule"] == 3600.0
    old = submit(client, image_bytes)
    age(client, old, days=31)
    monkeypatch.setattr("app.workers.tasks.SessionLocal", client.session_factory)
    assert tasks.purge_expired_media.run() == {"jobs": 1, "orphans": 0}
    assert not job_directory(old).exists()


def test_config_exposes_retention(client, retention):
    assert client.get("/api/v1/config/platforms").json()["media_retention_days"] == 30


def test_worker_start_runs_a_purge_so_restarts_cannot_postpone_it(monkeypatch):
    # Interval schedules first fire one full interval after start; services restarted more
    # often than hourly would otherwise never purge.
    from celery.signals import worker_ready
    sent = []
    monkeypatch.setattr(celery_app, "send_task", lambda name, *a, **k: sent.append(name))
    worker_ready.send(sender=None)
    assert sent == ["social.purge_expired"]


def test_orphan_lookup_is_batched_and_still_exact(client, image_bytes, retention, monkeypatch):
    # PostgreSQL caps a query at 65,535 parameters, so live folders are checked in chunks.
    from app.services import retention as module
    monkeypatch.setattr(module, "ORPHAN_LOOKUP_CHUNK", 2)
    live = [submit(client, image_bytes) for _ in range(5)]
    root = job_directory(live[0]).parent
    orphan = root / str(uuid4())
    orphan.mkdir()
    old = time.time() - 2 * 86400
    for folder in [orphan, *(job_directory(job_id) for job_id in live)]:
        os.utime(folder, (old, old))
    statements = []
    from sqlalchemy import event
    engine = client.session_factory.kw["bind"]
    listener = lambda *args: statements.append(args[2])  # noqa: E731
    event.listen(engine, "before_cursor_execute", listener)
    try:
        with client.session_factory() as session:
            assert purge_orphans(session) == 1
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    assert not orphan.exists() and all(job_directory(job_id).exists() for job_id in live)
    assert len([s for s in statements if "generation_jobs" in s]) == 3   # 6 folders in chunks of 2


def test_a_folder_vanishing_mid_sweep_does_not_abort_it(client, image_bytes, retention, monkeypatch):
    root = job_directory(submit(client, image_bytes)).parent
    vanishing, orphan = root / str(uuid4()), root / str(uuid4())
    for folder in (vanishing, orphan):
        folder.mkdir()
        old = time.time() - 2 * 86400
        os.utime(folder, (old, old))
    from pathlib import Path
    real_stat = Path.stat
    def stat(self, *args, **kwargs):
        if self.name == vanishing.name:
            raise FileNotFoundError(self)
        return real_stat(self, *args, **kwargs)
    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "stat", stat)
        with client.session_factory() as session:
            assert purge_orphans(session) == 1
    assert not orphan.exists()
