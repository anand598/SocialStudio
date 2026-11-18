"""Transactional outbox: a job and its queue message commit together, and a relay publishes the rest."""
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from app.core.config import get_settings
from app.main import app
from app.models.job import GenerationJob
from app.models.outbox import OutboxMessage
from app.services import outbox
from app.workers.tasks import expire_stale
from test_upload import submit

API = "/api/v1/generations"


class Broker:
    """Stands in for Celery publishing; `up = False` simulates a broker outage."""
    def __init__(self):
        self.up, self.sent, self.attempts = True, [], 0

    def __call__(self, task: str, job_id: UUID) -> None:
        self.attempts += 1
        if not self.up:
            raise ConnectionError("private broker address")
        self.sent.append((task, str(job_id)))


@pytest.fixture
def broker(client, monkeypatch):
    fake = Broker()
    monkeypatch.setattr("app.services.outbox.send", fake)
    monkeypatch.setattr(outbox, "_broker_down_until", 0.0)  # the breaker is process state
    return fake


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)  # SQLite drops the offset


def messages(client, job_id=None) -> list[OutboxMessage]:
    with client.session_factory() as session:
        query = select(OutboxMessage).order_by(OutboxMessage.created_at)
        if job_id is not None:
            query = query.where(OutboxMessage.job_id == UUID(str(job_id)))
        return list(session.scalars(query))


def count(client, model) -> int:
    with client.session_factory() as session:
        return session.scalar(select(func.count()).select_from(model))


def job(client, job_id) -> GenerationJob:
    with client.session_factory() as session:
        return session.get(GenerationJob, UUID(str(job_id)))


def relay(client, at: datetime | None = None) -> int:
    with client.session_factory() as session:
        return outbox.relay_once(session, now=at)


def finish(client, job_id):
    with client.session_factory() as session:
        stored = session.get(GenerationJob, UUID(job_id))
        stored.status, stored.stage, stored.progress = "completed", "completed", 100
        stored.generated_content = {"hook": "h", "title": "t"}
        session.commit()


def fail(client, job_id):
    with client.session_factory() as session:
        stored = session.get(GenerationJob, UUID(job_id))
        stored.status, stored.stage, stored.error_code = "failed", "failed", "GENERATION_FAILED"
        session.commit()


# ---------- writes are atomic ----------

def test_create_commits_a_job_with_its_message_and_publishes_at_once(client, image_bytes, broker):
    response = submit(client, image_bytes)
    assert response.status_code == 202
    job_id = response.json()["id"]
    assert broker.sent == [("social.generate", job_id)]
    [message] = messages(client, job_id)
    assert message.task == "social.generate"
    assert message.sent_at is not None and message.attempts == 1 and message.last_error is None


def test_retry_commits_the_status_change_with_a_new_message(client, image_bytes, broker):
    job_id = submit(client, image_bytes).json()["id"]
    fail(client, job_id)
    assert client.post(f"{API}/{job_id}/retry").status_code == 202
    assert broker.sent == [("social.generate", job_id)] * 2
    assert [m.sent_at is not None for m in messages(client, job_id)] == [True, True]


def test_variant_commits_the_new_job_with_its_message(client, image_bytes, broker):
    source = submit(client, image_bytes).json()["id"]
    finish(client, source)
    response = client.post(f"{API}/{source}/variants")
    assert response.status_code == 202, response.text
    new_id = response.json()["id"]
    assert broker.sent[-1] == ("social.generate", new_id)
    assert len(messages(client, new_id)) == 1


@pytest.fixture
def broken_outbox(monkeypatch):
    """The message insert violates NOT NULL, so the whole transaction must roll back."""
    original = outbox.add
    monkeypatch.setattr("app.services.outbox.add", lambda session, job_id: original(session, None))


def test_failed_create_transaction_leaves_neither_job_nor_message(client, image_bytes, broker, broken_outbox):
    assert submit(client, image_bytes).status_code == 503
    assert count(client, GenerationJob) == 0 and count(client, OutboxMessage) == 0
    assert broker.attempts == 0


def test_failed_retry_transaction_leaves_the_job_failed_and_no_message(client, image_bytes, broker, monkeypatch):
    job_id = submit(client, image_bytes).json()["id"]
    fail(client, job_id)
    original = outbox.add
    monkeypatch.setattr("app.services.outbox.add", lambda session, job_id: original(session, None))
    assert client.post(f"{API}/{job_id}/retry").status_code == 503
    assert job(client, job_id).status == "failed"
    assert len(messages(client, job_id)) == 1  # only the original submission's message
    assert broker.attempts == 1


def test_failed_variant_transaction_leaves_neither_job_nor_message(client, image_bytes, broker, monkeypatch):
    source = submit(client, image_bytes).json()["id"]
    finish(client, source)
    original = outbox.add
    monkeypatch.setattr("app.services.outbox.add", lambda session, job_id: original(session, None))
    assert client.post(f"{API}/{source}/variants").status_code in (409, 503)
    assert count(client, GenerationJob) == 1 and count(client, OutboxMessage) == 1
    assert broker.attempts == 1


# ---------- broker outages ----------

def test_broker_down_keeps_the_job_queued_with_a_pending_message(client, image_bytes, broker):
    broker.up = False
    before = utcnow()
    response = submit(client, image_bytes)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued" and body["error_code"] is None and body["error_message"] is None
    assert job(client, body["id"]).status == "queued"
    [message] = messages(client, body["id"])
    assert message.sent_at is None and message.attempts == 1
    assert "ConnectionError" in message.last_error
    delay = (aware(message.next_attempt_at) - before).total_seconds()
    assert outbox.backoff(1) <= delay <= outbox.backoff(1) + 5


def test_relay_waits_for_the_backoff_then_publishes_when_the_broker_returns(client, image_bytes, broker):
    broker.up = False
    job_id = submit(client, image_bytes).json()["id"]
    broker.up = True
    assert relay(client) == 0  # not due yet
    assert relay(client, utcnow() + timedelta(seconds=outbox.backoff(1) + 1)) == 1
    assert broker.sent == [("social.generate", job_id)]
    [message] = messages(client, job_id)
    assert message.sent_at is not None and message.attempts == 2
    assert relay(client, utcnow() + timedelta(hours=1)) == 0  # sent messages are never republished


def test_backoff_doubles_and_is_capped(monkeypatch):
    monkeypatch.setattr(get_settings(), "outbox_max_backoff_seconds", 60)
    assert [outbox.backoff(n) for n in range(1, 8)] == [2, 4, 8, 16, 32, 60, 60]


def test_relay_backs_off_and_stops_its_pass_at_the_first_failure(client, image_bytes, broker):
    broker.up = False
    ids = [submit(client, image_bytes).json()["id"] for _ in range(3)]
    assert broker.attempts == 1  # later requests skip the broker that just failed
    later = utcnow() + timedelta(minutes=5)
    assert relay(client, later) == 0
    assert broker.attempts == 2  # one failure ends the pass: no storm against a dead broker
    [attempted] = [m for m in messages(client) if aware(m.next_attempt_at) > later]
    delay = (aware(attempted.next_attempt_at) - later).total_seconds()
    assert delay == pytest.approx(outbox.backoff(attempted.attempts), abs=1)
    broker.up = True
    assert relay(client, later + timedelta(minutes=5)) == 3
    assert sorted(job_id for _, job_id in broker.sent) == sorted(ids)


def test_lost_fast_path_is_recovered_by_the_relay_after_the_lease(client, image_bytes, broker):
    """A crash between commit and publish leaves an unsent message leased to the request."""
    job_id = uuid4()
    with client.session_factory() as session:
        session.add(GenerationJob(id=job_id, platform="instagram", format="feed_square"))
        outbox.add(session, job_id)
        session.commit()
    assert relay(client) == 0  # the creating request still holds the lease
    assert relay(client, utcnow() + timedelta(seconds=outbox.LEASE_SECONDS + 1)) == 1
    assert broker.sent == [("social.generate", str(job_id))]


# ---------- interaction with stale-job expiry ----------

def test_messages_for_jobs_that_left_the_queue_are_retired_unpublished(client, image_bytes, broker):
    broker.up = False
    job_id = submit(client, image_bytes).json()["id"]
    with client.session_factory() as session:
        stored = session.get(GenerationJob, UUID(job_id))
        stored.updated_at = utcnow() - timedelta(seconds=get_settings().stale_job_seconds + 60)
        session.commit()
        assert expire_stale(session) == 1
    expired = client.get(f"{API}/{job_id}").json()
    assert expired["status"] == "failed" and expired["error_code"] == "JOB_EXPIRED"
    assert "queue" in expired["error_message"]
    broker.up = True
    assert relay(client, utcnow() + timedelta(hours=1)) == 0
    assert broker.sent == []
    [message] = messages(client, job_id)
    assert message.sent_at is not None and "failed" in message.last_error
    assert relay(client, utcnow() + timedelta(hours=2)) == 0 and broker.attempts == 1


# ---------- several relays ----------

def pending_message(client, at: datetime) -> UUID:
    job_id = uuid4()
    with client.session_factory() as session:
        session.add(GenerationJob(id=job_id, platform="instagram", format="feed_square"))
        message = outbox.add(session, job_id)
        message.next_attempt_at = at
        session.commit()
    return job_id


def test_a_message_can_be_claimed_by_only_one_relay(client, broker):
    now = utcnow()
    pending_message(client, now - timedelta(seconds=1))
    with client.session_factory() as first, client.session_factory() as second:
        [seen_by_first] = outbox.due(first, now)
        [seen_by_second] = outbox.due(second, now)
        assert outbox.claim(first, seen_by_first, now) is True
        assert outbox.claim(second, seen_by_second, now) is False


def test_a_relay_skips_messages_another_relay_published_meanwhile(client, broker):
    now = utcnow()
    ids = {pending_message(client, now - timedelta(seconds=1)) for _ in range(3)}
    with client.session_factory() as slow:
        stale_view = outbox.due(slow, now)
        assert relay(client, now) == 3  # another process publishes everything
        assert [outbox.claim(slow, row, now) for row in stale_view] == [False] * 3
    assert {UUID(job_id) for _, job_id in broker.sent} == ids and len(broker.sent) == 3


def test_a_claimed_message_is_leased_away_from_other_relays(client, broker):
    now = utcnow()
    pending_message(client, now - timedelta(seconds=1))
    with client.session_factory() as first:
        [row] = outbox.due(first, now)
        assert outbox.claim(first, row, now)
    assert relay(client, now) == 0
    assert relay(client, now + timedelta(seconds=outbox.LEASE_SECONDS + 1)) == 1


# ---------- housekeeping ----------

def test_sent_messages_are_deleted_after_a_day(client, broker):
    now = utcnow()
    with client.session_factory() as session:
        for sent_at in (now - timedelta(days=2), now - timedelta(hours=1), None):
            message = outbox.add(session, uuid4())
            message.sent_at = sent_at
            message.created_at = now - timedelta(days=3)
        session.commit()
        assert outbox.purge_sent(session, now) == 1
    remaining = messages(client)
    assert len(remaining) == 2 and any(m.sent_at is None for m in remaining)


# ---------- lifecycle ----------

def test_relay_runs_in_the_api_lifespan_and_stops_promptly(client, broker, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "outbox_relay_enabled", True)
    monkeypatch.setattr(settings, "outbox_poll_seconds", 0.05)
    monkeypatch.setattr("app.services.outbox.SessionLocal", client.session_factory)
    job_id = pending_message(client, utcnow() - timedelta(seconds=1))
    with TestClient(app) as running:
        relay_thread = running.app.state.outbox_relay
        assert relay_thread is not None and relay_thread.running
        deadline = time.monotonic() + 5
        while not broker.sent and time.monotonic() < deadline:
            time.sleep(0.02)
        assert broker.sent == [("social.generate", str(job_id))]
        started = time.monotonic()
    assert time.monotonic() - started < 2
    assert not relay_thread.running


def test_relay_is_off_in_tests_unless_started_explicitly(client):
    assert client.app.state.outbox_relay is None


def test_relay_survives_a_failing_pass(client, broker, monkeypatch):
    calls = []
    def boom(session, now=None):
        calls.append(1)
        raise RuntimeError("database unavailable")
    monkeypatch.setattr("app.services.outbox.relay_once", boom)
    monkeypatch.setattr("app.services.outbox.SessionLocal", client.session_factory)
    worker = outbox.OutboxRelay(interval=0.01)
    worker.start()
    deadline = time.monotonic() + 5
    while len(calls) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    worker.stop()
    assert len(calls) >= 3 and not worker.running


def test_requests_do_not_wait_on_a_broker_that_just_failed(client, image_bytes, broker):
    # Each publish to a dead broker waits for its connection timeout (seconds). After one failure the
    # fast path pauses and hands new messages straight to the relay instead.
    broker.up = False
    submit(client, image_bytes)
    second = submit(client, image_bytes).json()
    assert broker.attempts == 1
    assert second["status"] == "queued" and second["error_code"] is None
    [message] = messages(client, second["id"])
    assert message.sent_at is None and message.attempts == 0
    assert aware(message.next_attempt_at) <= utcnow()  # due for the relay at once, not after a lease


def test_fast_path_resumes_once_the_relay_reaches_the_broker(client, image_bytes, broker):
    broker.up = False
    submit(client, image_bytes)
    broker.up = True
    assert relay(client, utcnow() + timedelta(minutes=1)) == 1
    later = submit(client, image_bytes).json()["id"]
    assert ("social.generate", later) in broker.sent  # published by the request itself again


def test_fast_path_tries_the_broker_again_after_the_pause(client, image_bytes, broker, monkeypatch):
    broker.up = False
    submit(client, image_bytes)
    monkeypatch.setattr(outbox, "_broker_down_until", time.monotonic() - 1)  # pause over
    broker.up = True
    later = submit(client, image_bytes).json()["id"]
    assert ("social.generate", later) in broker.sent


def test_publishing_to_an_unreachable_broker_fails_fast():
    # kombu's Redis transport ignores broker_connection_timeout; without socket timeouts in the
    # transport options a publish to a blackholed broker blocks for 75-127 s (or forever if Redis
    # hangs), tying up request threads and the relay.
    from celery import Celery
    from app.workers.celery_app import broker_transport_options
    probe = Celery("probe", broker="redis://192.0.2.1:6379/1")  # TEST-NET-1: never routable
    probe.conf.update(broker_connection_timeout=3, broker_transport_options=broker_transport_options(900))
    started = time.monotonic()
    with pytest.raises(Exception):
        probe.send_task("social.generate", args=["x"], retry=False)
    assert time.monotonic() - started < 8


def test_a_failed_read_after_commit_keeps_the_committed_job_and_its_media(client, image_bytes, broker, monkeypatch):
    # The job and its queue message are committed, so the job will run: its inputs must stay.
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session
    from app.services.storage.local import job_directory
    real_refresh = Session.refresh
    def flaky(self, instance, *args, **kwargs):
        if isinstance(instance, GenerationJob):
            raise OperationalError("refresh", {}, Exception("connection lost"))
        return real_refresh(self, instance, *args, **kwargs)
    with monkeypatch.context() as scoped:
        scoped.setattr(Session, "refresh", flaky)
        response = submit(client, image_bytes)
    [stored] = list(job_directory(uuid4()).parent.iterdir())
    assert response.status_code in (202, 503)
    assert (stored / "input.jpg").is_file()
    assert count(client, GenerationJob) == 1 and count(client, OutboxMessage) == 1
