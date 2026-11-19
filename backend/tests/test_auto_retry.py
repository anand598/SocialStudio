"""Automatic retries after a transient failure (model unreachable, a product page timing out) go
through the outbox like every other hand-off to the queue.

They used to be published by the worker straight to the broker (Celery's self.retry). If the broker
was down at that moment the publish failed, the job sat in "retry_wait" until the stuck-job sweep
failed it, and nothing would ever pick it up. Now the requeue and its delayed outbox message are one
transaction, and the relay publishes the message when it is due.
"""
from datetime import timedelta
from uuid import UUID
import pytest
from sqlalchemy import select
from app.models.job import GenerationJob
from app.models.outbox import OutboxMessage
from app.services import outbox
from app.services.ai.provider import GenerationError
from app.workers import tasks
from app.workers.tasks import generate
from test_upload import submit

UNREACHABLE = GenerationError("AI_UNAVAILABLE", "The AI model could not be reached.", transient=True)


@pytest.fixture
def flaky(client, monkeypatch):
    """The model fails with a transient error; the broker records what is published."""
    monkeypatch.setattr("app.workers.tasks.SessionLocal", client.session_factory)
    published = []
    monkeypatch.setattr(outbox, "send", lambda task, job_id: published.append(str(job_id)))
    class Down:
        def analyze_product_image(self, path):
            raise UNREACHABLE
    monkeypatch.setattr(tasks, "get_provider", lambda mode: Down())
    return published


def job_of(client, job_id):
    with client.session_factory() as session:
        return session.get(GenerationJob, UUID(job_id))


def pending(client, job_id):
    with client.session_factory() as session:
        return session.scalars(select(OutboxMessage).where(OutboxMessage.job_id == UUID(job_id),
                                                           OutboxMessage.sent_at.is_(None))).all()


def test_a_transient_failure_requeues_through_the_outbox(client, image_bytes, flaky):
    job_id = submit(client, image_bytes).json()["id"]
    flaky.clear()
    generate.run(job_id)                               # no Retry raised: nothing goes to the broker directly
    job = job_of(client, job_id)
    assert (job.status, job.stage, job.auto_retries) == ("queued", "retry_wait", 1)
    [message] = pending(client, job_id)
    assert flaky == []
    with client.session_factory() as session:
        now = outbox.utcnow()
        assert outbox.relay_once(session, now=now) == 0                       # not before its delay
        assert outbox.relay_once(session, now=now + timedelta(seconds=6)) == 1
    assert flaky == [job_id] and pending(client, job_id) == []


def test_retries_are_bounded_then_the_job_fails_with_the_real_error(client, image_bytes, flaky):
    job_id = submit(client, image_bytes).json()["id"]
    delays = []
    for _ in range(3):
        generate.run(job_id)
        for message in pending(client, job_id):
            delays.append(round((message.next_attempt_at.replace(tzinfo=None)
                                 - outbox.utcnow().replace(tzinfo=None)).total_seconds()))
            with client.session_factory() as session:
                session.get(OutboxMessage, message.id).sent_at = outbox.utcnow()
                session.commit()
    job = job_of(client, job_id)
    assert (job.status, job.error_code, job.auto_retries) == ("failed", "AI_UNAVAILABLE", 2)
    assert delays == [5, 10]


def test_a_manual_retry_gets_a_fresh_set_of_automatic_retries(client, image_bytes, flaky):
    job_id = submit(client, image_bytes).json()["id"]
    for _ in range(3):
        generate.run(job_id)
    assert job_of(client, job_id).status == "failed"
    assert client.post(f"/api/v1/generations/{job_id}/retry").status_code == 202
    assert job_of(client, job_id).auto_retries == 0


def test_a_superseded_worker_does_not_requeue(client, image_bytes, flaky, monkeypatch):
    # The job was expired (and maybe retried by the user) while this worker was still waiting on the model.
    job_id = submit(client, image_bytes).json()["id"]
    before = len(pending(client, job_id))
    class Slow:
        def analyze_product_image(self, path):
            with client.session_factory() as session:
                session.get(GenerationJob, UUID(job_id)).status = "failed"
                session.commit()
            raise UNREACHABLE
    monkeypatch.setattr(tasks, "get_provider", lambda mode: Slow())
    generate.run(job_id)
    job = job_of(client, job_id)
    assert job.status == "failed" and job.auto_retries == 0
    assert len(pending(client, job_id)) == before
