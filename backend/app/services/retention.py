"""Media retention: delete stored inputs and outputs after MEDIA_RETENTION_DAYS.

The job row and its generated text are kept, so the owner still sees what was made and why the
media is gone. Each job is claimed with a conditional update before its files are deleted, so a
concurrent retry or new version can never start from media that is being removed. Folders that
belong to no live job (a crash between storing files and saving the row, or an interrupted
delete) are swept once they are more than a day old.
"""
import logging
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.models.job import GenerationJob
from app.services.storage.local import job_directory

logger = logging.getLogger(__name__)
FINISHED = ("completed", "failed")
BATCH = 200
ORPHAN_GRACE_SECONDS = 86400
# PostgreSQL allows at most 65,535 parameters per query; look folders up in chunks.
ORPHAN_LOOKUP_CHUNK = 1000
MEDIA_FIELDS = ("input_file_path", "source_media_path", "music_path", "logo_path", "output_file_path",
                "thumbnail_file_path")


def purge_expired(session: Session, now: datetime | None = None) -> int:
    """Delete the media of finished jobs older than the retention period. Returns jobs purged."""
    days = get_settings().media_retention_days
    if days <= 0:
        return 0
    now = now or datetime.now(timezone.utc)
    finished_at = func.coalesce(GenerationJob.completed_at, GenerationJob.updated_at)
    expired = (GenerationJob.status.in_(FINISHED), GenerationJob.purged_at.is_(None),
               finished_at < now - timedelta(days=days))
    candidates = session.scalars(select(GenerationJob.id).where(*expired).limit(BATCH)).all()
    purged = 0
    for job_id in candidates:
        claimed = session.execute(update(GenerationJob).where(GenerationJob.id == job_id, *expired)
                                  .values(purged_at=now, **{field: None for field in MEDIA_FIELDS}))
        session.commit()
        if not claimed.rowcount:
            continue  # retried or already purged since it was selected
        purged += 1
        try:
            shutil.rmtree(job_directory(job_id))
        except FileNotFoundError:
            pass
        except OSError:
            # The orphan sweep removes what is left on a later run.
            logger.exception("Could not delete media for expired job %s", job_id)
    if purged:
        logger.info("Purged media for %s expired jobs (retention %s days)", purged, days)
    return purged


def purge_orphans(session: Session) -> int:
    """Remove job folders older than a day whose job no longer exists or has expired."""
    root = Path(get_settings().local_storage_path).resolve()
    if not root.is_dir():
        return 0
    cutoff = time.time() - ORPHAN_GRACE_SECONDS
    folders: dict[UUID, Path] = {}
    for entry in root.iterdir():
        try:
            job_id = UUID(entry.name)
        except ValueError:
            continue  # not a job folder (e.g. the development queue)
        if str(job_id) != entry.name:
            continue
        try:
            if entry.is_dir() and not entry.is_symlink() and entry.stat().st_mtime < cutoff:
                folders[job_id] = entry
        except FileNotFoundError:
            continue  # removed meanwhile (failed upload cleanup, or another purge run)
    if not folders:
        return 0
    ids, live = list(folders), set()
    for start in range(0, len(ids), ORPHAN_LOOKUP_CHUNK):
        chunk = ids[start:start + ORPHAN_LOOKUP_CHUNK]
        live.update(session.scalars(select(GenerationJob.id).where(GenerationJob.id.in_(chunk),
                                                                  GenerationJob.purged_at.is_(None))))
    removed = 0
    for job_id, folder in folders.items():
        if job_id not in live:
            shutil.rmtree(folder, ignore_errors=True)
            removed += 1
    if removed:
        logger.info("Removed %s orphaned job folders", removed)
    return removed
