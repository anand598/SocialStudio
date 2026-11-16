import logging
import shutil
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.exc import SQLAlchemyError
from fastapi.responses import FileResponse
from app.workers.tasks import generate, expire_stale
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.core.platforms import SUPPORTED_FORMATS
from app.db.session import get_session
from app.models.job import GenerationJob
from app.schemas.jobs import JobResponse
from app.services.storage.local import job_directory, store_image

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)


@router.get("/config/platforms")
def platforms():
    return {"formats": SUPPORTED_FORMATS, "generation_mode": get_settings().generation_mode,
            "max_upload_size_mb": get_settings().max_upload_size_mb}


@router.post("/generations", response_model=JobResponse, status_code=202)
async def create_generation(
    file: UploadFile = File(...), platform: str = Form(...), format: str = Form(...),
    brand_name: str = Form("", max_length=80),
    brand_description: str = Form("", max_length=500),
    call_to_action: str = Form("Explore the collection", max_length=100),
    session: Session = Depends(get_session),
):
    if not any(item.platform == platform and item.format == format for item in SUPPORTED_FORMATS):
        raise HTTPException(422, "Only Instagram Reel is currently supported.")
    job_id = uuid4()
    try:
        path = await store_image(file, job_id)
    finally:
        await file.close()
    job = GenerationJob(id=job_id, input_file_path=path, platform=platform, format=format,
                        brand_context={"brand_name": brand_name.strip(), "brand_description": brand_description.strip(),
                                       "call_to_action": call_to_action.strip() or "Explore the collection"},
                        generation_mode=get_settings().generation_mode)
    try:
        session.add(job)
        session.commit()
        session.refresh(job)
    except SQLAlchemyError as exc:
        session.rollback()
        shutil.rmtree(job_directory(job_id), ignore_errors=True)
        logger.exception("Could not persist job %s", job_id)
        raise HTTPException(503, "Storage is unavailable. Please try again shortly.") from exc
    enqueue(job, session)
    return job


def find_job(job_id: UUID, session: Session) -> GenerationJob:
    expire_stale(session)
    job = session.get(GenerationJob, job_id)
    if not job:
        raise HTTPException(404, "Generation not found.")
    return job


@router.get("/generations/{job_id}", response_model=JobResponse)
def get_generation(job_id: UUID, session: Session = Depends(get_session)):
    return find_job(job_id, session)


def enqueue(job: GenerationJob, session: Session) -> None:
    try:
        generate.apply_async(args=[str(job.id)], retry=False)
    except Exception:
        logger.exception("Could not enqueue job %s", job.id)
        job.status, job.stage = "failed", "failed"
        job.error_code = "QUEUE_UNAVAILABLE"
        job.error_message = "The generation queue is unavailable. Start the broker and worker, then retry."
        session.commit()


@router.post("/generations/{job_id}/retry", response_model=JobResponse, status_code=202)
def retry_generation(job_id: UUID, session: Session = Depends(get_session)):
    job = find_job(job_id, session)
    if job.status != "failed":
        raise HTTPException(409, "Only failed generations can be retried.")
    # A conditional update prevents concurrent retries from publishing duplicate work.
    from sqlalchemy import update
    from datetime import datetime, timezone
    result = session.execute(update(GenerationJob).where(GenerationJob.id == job_id,
        GenerationJob.status == "failed").values(status="queued", stage="validating", progress=0,
            error_code=None, error_message=None, completed_at=None, updated_at=datetime.now(timezone.utc)))
    session.commit()
    if not result.rowcount:
        raise HTTPException(409, "This generation has already been retried.")
    session.refresh(job)
    enqueue(job, session)
    return job


@router.get("/generations/{job_id}/content")
def get_content(job_id: UUID, session: Session = Depends(get_session)):
    job = find_job(job_id, session)
    if job.status != "completed":
        raise HTTPException(409, "The generation is not complete yet.")
    return {"generation_mode": job.generation_mode, "analysis": job.product_analysis, "content": job.generated_content}


def completed_asset(job_id: UUID, session: Session, name: str):
    job = find_job(job_id, session)
    if job.status != "completed":
        raise HTTPException(409, "The generation is not complete yet.")
    from pathlib import Path
    stored = job.output_file_path if name == "output.mp4" else job.thumbnail_file_path
    if not stored:
        raise HTTPException(404, "This result is missing.")
    path = Path(stored).resolve()
    if path.parent != job_directory(job_id):
        raise HTTPException(404, "This result is unavailable.")
    if not path.is_file():
        raise HTTPException(404, "This result is missing. Please create a new generation.")
    return path


@router.get("/generations/{job_id}/download")
def download(job_id: UUID, session: Session = Depends(get_session)):
    return FileResponse(completed_asset(job_id, session, "output.mp4"), media_type="video/mp4",
                        filename=f"instagram-reel-{job_id}.mp4", headers={"Cache-Control": "private, no-store"})


@router.get("/generations/{job_id}/preview")
def preview(job_id: UUID, session: Session = Depends(get_session)):
    return FileResponse(completed_asset(job_id, session, "output.mp4"), media_type="video/mp4",
                        headers={"Cache-Control": "private, no-store"})


@router.get("/generations/{job_id}/thumbnail")
def thumbnail(job_id: UUID, session: Session = Depends(get_session)):
    return FileResponse(completed_asset(job_id, session, "thumbnail.jpg"), media_type="image/jpeg")
