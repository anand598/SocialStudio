"""Transactional outbox: guaranteed delivery of generation jobs from the database to the Celery queue.

Every job change that needs a worker (create, retry, new version) inserts an OutboxMessage in the same
transaction, so a committed job always has its queue message and a rolled-back one never does. Right
after commit the API publishes the message itself (the fast path), so the normal case stays instant.
Anything left unsent (the broker was down, or the process died between commit and publish) is published
by OutboxRelay, a thread in each API process. It talks to the database and the broker directly, not
through Celery, so it keeps retrying while the broker is down.

Several relays (one per API process) may run at once. A relay claims a message with a conditional update
on its attempt counter, which also leases it (next_attempt_at moves LEASE_SECONDS ahead), so only one
relay publishes it at a time; this works the same on PostgreSQL and SQLite. A rare duplicate (a publish
that succeeded but whose "sent" mark did not commit) is harmless: the worker atomically claims only
queued jobs. Messages whose job is no longer queued, e.g. expired by the stale-job sweep, are retired
without being published.
"""
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID
from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.job import GenerationJob
from app.models.outbox import OutboxMessage
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
GENERATE = "social.generate"
# How long whoever is publishing a message holds it before another relay may take it over.
LEASE_SECONDS = 30
BATCH_SIZE = 50
SENT_RETENTION = timedelta(days=1)
PURGE_EVERY_SECONDS = 600


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def send(task: str, job_id: UUID) -> None:
    """Publish one message. No Celery-level retry: a failure is retried by the outbox, with backoff."""
    celery_app.send_task(task, args=[str(job_id)], retry=False)


def backoff(attempts: int) -> int:
    """Seconds to wait after the given number of failed attempts: 2, 4, 8, ... up to the configured cap."""
    return min(2 ** attempts, get_settings().outbox_max_backoff_seconds)


def add(session: Session, job_id: UUID, task: str = GENERATE) -> OutboxMessage:
    """Stage a message in the caller's transaction. It starts leased to the caller, who publishes it
    with publish_now after commit; the relay only steps in if that has not happened when the lease ends."""
    message = OutboxMessage(job_id=job_id, task=task, attempts=0,
                            next_attempt_at=utcnow() + timedelta(seconds=LEASE_SECONDS))
    session.add(message)
    return message


def deliver(session: Session, message_id: UUID, task: str, job_id: UUID, attempts: int, now: datetime) -> bool:
    """Publish a message this process holds, then record the outcome. `attempts` includes this one."""
    pending = (OutboxMessage.id == message_id, OutboxMessage.sent_at.is_(None))
    try:
        send(task, job_id)
    except Exception as exc:
        delay = backoff(attempts)
        session.execute(update(OutboxMessage).where(*pending).values(
            attempts=attempts, next_attempt_at=now + timedelta(seconds=delay),
            last_error=f"{type(exc).__name__}: {exc}"[:500]))
        session.commit()
        logger.warning("Could not publish job %s (attempt %s, %s); retrying in %ss",
                       job_id, attempts, type(exc).__name__, delay)
        return False
    session.execute(update(OutboxMessage).where(*pending).values(attempts=attempts, sent_at=utcnow(), last_error=None))
    session.commit()
    return True


def publish_now(session: Session, message: OutboxMessage) -> bool:
    """Fast path, called right after the message was committed. Never raises: the job is already saved
    and stays queued, so on any failure the message is simply left for the relay."""
    try:
        return deliver(session, message.id, message.task, message.job_id, 1, utcnow())
    except SQLAlchemyError:
        session.rollback()
        logger.exception("Could not record the publish of job %s; the outbox relay will publish it", message.job_id)
        return False


def due(session: Session, now: datetime, limit: int = BATCH_SIZE):
    """Unsent messages whose time has come, oldest first, with their job's current status."""
    return session.execute(
        select(OutboxMessage.id, OutboxMessage.task, OutboxMessage.job_id, OutboxMessage.attempts,
               GenerationJob.status)
        .outerjoin(GenerationJob, GenerationJob.id == OutboxMessage.job_id)
        .where(OutboxMessage.sent_at.is_(None), OutboxMessage.next_attempt_at <= now)
        .order_by(OutboxMessage.next_attempt_at).limit(limit)).all()


def claim(session: Session, row, now: datetime) -> bool:
    """Take the lease on a message read by due(). The attempt counter acts as a version: if another
    relay claimed or published the message since it was read, nothing matches and the claim fails."""
    result = session.execute(update(OutboxMessage).where(
        OutboxMessage.id == row.id, OutboxMessage.attempts == row.attempts, OutboxMessage.sent_at.is_(None)
    ).values(attempts=row.attempts + 1, next_attempt_at=now + timedelta(seconds=LEASE_SECONDS)))
    session.commit()
    return result.rowcount == 1


def retire(session: Session, row, now: datetime) -> None:
    """Close a message without publishing it because its job has left the queue (expired, running, done)."""
    session.execute(update(OutboxMessage).where(OutboxMessage.id == row.id, OutboxMessage.sent_at.is_(None))
                    .values(sent_at=now, last_error=f"Not published: the job is {row.status or 'missing'}."))
    session.commit()


def relay_once(session: Session, now: datetime | None = None, limit: int = BATCH_SIZE) -> int:
    """One relay pass over at most `limit` due messages. Returns how many were published."""
    now = now or utcnow()
    published = retired = 0
    for row in due(session, now, limit):
        if row.status != "queued":
            retire(session, row, now)
            retired += 1
        elif claim(session, row, now):
            if not deliver(session, row.id, row.task, row.job_id, row.attempts + 1, now):
                break  # The broker is most likely down: leave the rest for a later pass rather than hammer it.
            published += 1
    if published or retired:
        logger.info("Outbox relay published=%s retired=%s", published, retired)
    return published


def purge_sent(session: Session, now: datetime | None = None) -> int:
    """Delete messages that were sent or retired more than a day ago."""
    result = session.execute(delete(OutboxMessage).where(OutboxMessage.sent_at < (now or utcnow()) - SENT_RETENTION))
    session.commit()
    return result.rowcount


class OutboxRelay:
    """Runs relay passes on a background thread until stopped. Started by the API lifespan (app.main)."""

    def __init__(self, interval: float | None = None):
        self.interval = interval or get_settings().outbox_poll_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="outbox-relay", daemon=True)

    @property
    def running(self) -> bool:
        return self._thread.is_alive()

    def start(self) -> None:
        self._thread.start()
        logger.info("Outbox relay started interval=%ss", self.interval)

    def stop(self, timeout: float = 5.0) -> None:
        # A pass in progress finishes first; a publish to an unreachable broker is bounded by its connect
        # timeout. The thread is a daemon, so even a stuck pass cannot keep the process alive.
        self._stop.set()
        self._thread.join(timeout)

    def _run(self) -> None:
        next_purge = 0.0
        while not self._stop.is_set():
            try:
                with SessionLocal() as session:
                    relay_once(session)
                    if time.monotonic() >= next_purge:
                        purge_sent(session)
                        next_purge = time.monotonic() + PURGE_EVERY_SECONDS
            except Exception:
                logger.exception("Outbox relay pass failed; retrying in %ss", self.interval)
            self._stop.wait(self.interval)
