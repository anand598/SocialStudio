import uuid
from datetime import datetime
from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class OutboxMessage(Base):
    """A queue message written in the same transaction as the job change that needs it (transactional outbox).

    The API publishes it straight after commit; the relay in app.services.outbox publishes whatever is left.
    """
    __tablename__ = "outbox_messages"
    # Serves both the relay's "unsent and due" scan and the cleanup of old sent rows.
    __table_args__ = (Index("ix_outbox_messages_sent_due", "sent_at", "next_attempt_at"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column()
    # Celery task name; the job id is its only argument.
    task: Mapped[str] = mapped_column(String(64))
    # Publish attempts so far. Doubles as the version a relay compares when claiming the row.
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Not before this time: the backoff after a failure, or the lease held by whoever is publishing it.
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Set once the message is published, or retired unpublished because its job left the queue
    # (last_error then says why). Rows with sent_at set are deleted after a day.
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
