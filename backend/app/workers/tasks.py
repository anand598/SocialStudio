import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import update
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.job import GenerationJob
from app.services.ai.provider import GenerationError, get_provider
from app.core.platforms import get_format
from app.services.ingest.url import ingest_url
from app.services.media.renderer import render_output
from app.services.storage.local import job_directory
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def now() -> datetime:
    return datetime.now(timezone.utc)


def transition(job_id: UUID, run_token: UUID, **values) -> bool:
    with SessionLocal() as session:
        result = session.execute(update(GenerationJob).where(GenerationJob.id == job_id,
            GenerationJob.status == "processing", GenerationJob.run_token == run_token).values(**values, updated_at=now()))
        session.commit()
        return result.rowcount == 1


def expire_stale(session) -> int:
    cutoff = now() - timedelta(seconds=get_settings().stale_job_seconds)
    result = session.execute(update(GenerationJob).where(
        GenerationJob.status.in_(["queued", "processing"]), GenerationJob.updated_at < cutoff).values(
        status="failed", stage="failed", error_code="JOB_EXPIRED",
        error_message="This generation stopped responding. Please retry it.", completed_at=now(), updated_at=now()))
    session.commit()
    return result.rowcount


@celery_app.task(name="social.recover_stale")
def recover_stale():
    with SessionLocal() as session:
        return expire_stale(session)


@celery_app.task(bind=True, name="social.generate", max_retries=2)
def generate(self, job_id_string: str):
    job_id = UUID(job_id_string)
    run_token = uuid4()
    with SessionLocal() as session:
        # Atomic claim makes duplicate broker deliveries harmless.
        result = session.execute(update(GenerationJob).where(GenerationJob.id == job_id,
            GenerationJob.status == "queued").values(run_token=run_token, status="processing", stage="validating", progress=5,
                started_at=now(), updated_at=now(), error_code=None, error_message=None))
        session.commit()
        if not result.rowcount:
            return
        job = session.get(GenerationJob, job_id)
    try:
        output = get_format(job.platform, job.format)
        if output is None:
            raise GenerationError("UNSUPPORTED_FORMAT", "This output format is no longer supported.")
        provider = get_provider(job.generation_mode)
        still, source = job.input_file_path, job.source_metadata
        if job.input_type == "url" and not still:
            # Fetch inside the worker: slow, untrusted network I/O stays off the API, and a retry
            # after a successful fetch reuses the stored image instead of refetching.
            if not transition(job_id, run_token, stage="fetching", progress=10):
                return
            still, source = ingest_url(job.source_url, job_directory(job_id))
            if not transition(job_id, run_token, input_file_path=still, source_metadata=source):
                return
        if not transition(job_id, run_token, stage="analyzing", progress=20):
            return
        storyboard = job_directory(job_id) / "storyboard.jpg"
        if job.input_type == "video" and storyboard.is_file():
            # Four moments across the clip, not one frame, so later shots and angles inform the copy.
            analysis = provider.analyze_product_video(str(storyboard))
        else:
            analysis = provider.analyze_product_image(still)
        if not transition(job_id, run_token, stage="writing_copy", progress=40, product_analysis=analysis.model_dump()):
            return
        content = provider.generate_social_content(analysis, job.brand_context, output, source)
        if not transition(job_id, run_token, stage="rendering", progress=55, generated_content=content.model_dump()):
            return
        rendered, thumbnail = render_output(job.id, output, still, content, job.brand_context, run_token,
                                            job.source_media_path if job.input_type == "video" else None,
                                            music=job.music_path)
        if not transition(job_id, run_token, stage="finalizing", progress=95):
            return
        transition(job_id, run_token, status="completed", stage="completed", progress=100,
                   output_file_path=str(rendered), thumbnail_file_path=str(thumbnail), completed_at=now())
        logger.info("Generation completed job_id=%s mode=%s input=%s format=%s/%s", job_id, job.generation_mode,
                    job.input_type, job.platform, job.format)
    except GenerationError as exc:
        if exc.transient and self.request.retries < self.max_retries:
            transition(job_id, run_token, status="queued", stage="retry_wait", progress=0)
            raise self.retry(exc=exc, countdown=5 * (self.request.retries + 1))
        transition(job_id, run_token, status="failed", stage="failed", error_code=exc.code,
                   error_message=exc.message, completed_at=now())
    except (Exception, SoftTimeLimitExceeded):
        logger.exception("Generation failed job_id=%s", job_id)
        transition(job_id, run_token, status="failed", stage="failed", error_code="GENERATION_FAILED",
                   error_message="Generation could not finish. Check the worker configuration and retry.", completed_at=now())
