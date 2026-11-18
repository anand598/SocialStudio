from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from app.models.job import GenerationJob
from app.services.ai.provider import GenerationError
from app.services.media.renderer import inspect_video
from app.workers.tasks import expire_stale, generate
from test_upload import submit


def test_real_render_download_and_idempotency(client, image_bytes, monkeypatch):
    monkeypatch.setattr("app.workers.tasks.SessionLocal", client.session_factory)
    job_id = submit(client, image_bytes).json()["id"]
    assert client.get(f"/api/v1/generations/{job_id}/download").status_code == 409
    generate.run(job_id)
    job = client.get(f"/api/v1/generations/{job_id}").json()
    assert job["status"] == "completed", job
    assert job["progress"] == 100
    assert job["generated_content"]["benefits"] == []
    response = client.get(f"/api/v1/generations/{job_id}/download")
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert len(response.content) > 1000
    preview = client.get(f"/api/v1/generations/{job_id}/preview", headers={"Range": "bytes=0-99"})
    assert preview.status_code == 206
    assert len(preview.content) == 100
    from app.services.storage.local import job_directory
    output = next(job_directory(job_id).glob("output-*.mp4"))
    inspect_video(output, 9)
    before = output.stat().st_mtime_ns
    generate.run(job_id)
    assert output.stat().st_mtime_ns == before
    assert client.get(f"/api/v1/generations/{job_id}/content").json()["generation_mode"] == "demo"
    assert client.get(f"/api/v1/generations/{job_id}/thumbnail").status_code == 200


def test_safe_worker_failure_and_retry(client, image_bytes, monkeypatch):
    monkeypatch.setattr("app.workers.tasks.SessionLocal", client.session_factory)
    def fail(*args):
        raise RuntimeError("private service details")
    monkeypatch.setattr("app.workers.tasks.get_provider", fail)
    job_id = submit(client, image_bytes).json()["id"]
    generate.run(job_id)
    job = client.get(f"/api/v1/generations/{job_id}").json()
    assert job["status"] == "failed"
    assert job["error_code"] == "GENERATION_FAILED"
    assert "private" not in job["error_message"]
    assert client.post(f"/api/v1/generations/{job_id}/retry").status_code == 202
    assert client.post(f"/api/v1/generations/{job_id}/retry").status_code == 409


def test_stale_job_recovery(client, image_bytes):
    job_id = submit(client, image_bytes).json()["id"]
    from uuid import UUID
    with client.session_factory() as session:
        job = session.get(GenerationJob, UUID(job_id))
        job.status = "processing"
        job.updated_at = datetime.now(timezone.utc) - timedelta(hours=1)
        session.commit()
        assert expire_stale(session) == 1
    result = client.get(f"/api/v1/generations/{job_id}").json()
    assert result["error_code"] == "JOB_EXPIRED"


def test_queue_failure_leaves_the_job_queued_for_the_outbox_relay(client, image_bytes, monkeypatch):
    def fail(*args, **kwargs):
        raise ConnectionError("private broker address")
    monkeypatch.setattr("app.services.outbox.send", fail)
    response = submit(client, image_bytes)
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["error_code"] is None and response.json()["error_message"] is None


def test_expired_attempt_cannot_update_new_attempt(client, image_bytes):
    from uuid import UUID, uuid4
    from app.workers import tasks
    job_id = UUID(submit(client, image_bytes).json()["id"])
    old, current = uuid4(), uuid4()
    with client.session_factory() as session:
        job = session.get(GenerationJob, job_id)
        job.status, job.run_token = "processing", current
        session.commit()
    original = tasks.SessionLocal
    tasks.SessionLocal = client.session_factory
    try:
        assert tasks.transition(job_id, old, status="completed") is False
        assert tasks.transition(job_id, current, stage="rendering") is True
    finally:
        tasks.SessionLocal = original
