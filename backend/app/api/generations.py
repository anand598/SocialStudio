import hashlib
import hmac
import logging
import os
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4
from fastapi import APIRouter, Cookie, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from app.core.config import get_settings
from app.core.platforms import SUPPORTED_FORMATS, get_format
from app.db.session import get_session
from app.models.job import GenerationJob
from app.schemas.jobs import JobHistory, JobResponse, VariantRequest
from app.services import outbox
from app.services.ingest.url import UrlRejected, check_url
from app.services.storage.local import (check_logo_type, check_music_type, create_job_directory, job_directory,
                                        store_image, store_logo, store_music, store_video)
from app.workers.tasks import expire_stale, is_stale

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)

# Access control: the browser that creates a job receives a random HttpOnly cookie, and the job
# stores only its hash. A job URL alone does not grant access; anyone else gets a plain 404.
OWNER_COOKIE = "studio_owner"
OWNER_COOKIE_DAYS = 30
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def owner_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def owner_token(studio_owner: str | None = Cookie(None)) -> str | None:
    return studio_owner if studio_owner and TOKEN_PATTERN.match(studio_owner) else None


def set_owner_cookie(response: Response, token: str) -> None:
    response.set_cookie(OWNER_COOKIE, token, max_age=OWNER_COOKIE_DAYS * 86400, path="/", httponly=True,
                        samesite="lax", secure=get_settings().cookie_secure)


@router.get("/config/platforms")
def platforms():
    settings = get_settings()
    return {"formats": [{**item.model_dump(exclude={"copy_guidance"})} for item in SUPPORTED_FORMATS],
            "input_types": ["image", "video", "url"],
            "generation_mode": settings.generation_mode,
            "max_upload_size_mb": settings.max_upload_size_mb,
            "max_video_upload_size_mb": settings.max_video_upload_size_mb,
            "max_source_video_seconds": settings.max_source_video_seconds,
            "max_music_upload_size_mb": settings.max_music_upload_size_mb,
            "max_music_seconds": settings.max_music_seconds,
            "max_logo_upload_size_mb": settings.max_logo_upload_size_mb,
            "media_retention_days": settings.media_retention_days}


@router.post("/generations", response_model=JobResponse, status_code=202)
async def create_generation(
    response: Response,
    platform: str = Form(...), format: str = Form(...),
    input_type: Literal["image", "video", "url"] = Form("image"),
    file: UploadFile | None = File(None),
    music: UploadFile | None = File(None),
    logo: UploadFile | None = File(None),
    source_url: str = Form("", max_length=2048),
    brand_name: str = Form("", max_length=80),
    brand_description: str = Form("", max_length=500),
    call_to_action: str = Form("Explore the collection", max_length=100),
    brand_color: str = Form("", pattern=r"^(#[0-9A-Fa-f]{6})?$"),
    token: str | None = Depends(owner_token),
    session: Session = Depends(get_session),
):
    output = get_format(platform, format)
    if output is None:
        raise HTTPException(422, "Choose a supported platform and format.")
    if music is not None and output.kind != "video":
        await music.close()
        raise HTTPException(422, "Background music applies to video formats only.")
    job_id = uuid4()
    still = media = url = music_path = logo_path = None
    try:
        if music is not None:
            check_music_type(music)
        if logo is not None:
            check_logo_type(logo)
        if input_type == "url":
            if file is not None:
                raise HTTPException(422, "Send either a product URL or a file, not both.")
            try:
                # Fast feedback for obviously unsafe or unresolvable URLs; the worker re-validates every hop.
                url = await run_in_threadpool(check_url, source_url)
            except UrlRejected as exc:
                raise HTTPException(422, str(exc)) from exc
            create_job_directory(job_id)
        elif file is None:
            raise HTTPException(422, f"Upload a product {input_type}.")
        elif input_type == "video":
            media, still = await store_video(file, job_id)
        else:
            still = await store_image(file, job_id)
        try:
            if music is not None:
                music_path = await store_music(music, job_directory(job_id))
            if logo is not None:
                logo_path = await store_logo(logo, job_directory(job_id))
        except HTTPException:
            shutil.rmtree(job_directory(job_id), ignore_errors=True)
            raise
    finally:
        for upload in (file, music, logo):
            if upload is not None:
                await upload.close()
    token = token or secrets.token_urlsafe(32)
    job = GenerationJob(id=job_id, input_type=input_type, input_file_path=still, source_media_path=media,
                        owner_hash=owner_hash(token),
                        source_url=url, music_path=music_path, logo_path=logo_path, platform=platform, format=format,
                        brand_context={"brand_name": brand_name.strip(), "brand_description": brand_description.strip(),
                                       "call_to_action": call_to_action.strip() or "Explore the collection",
                                       "brand_color": brand_color.upper() or None},
                        generation_mode=get_settings().generation_mode)
    # Blocking database calls run in a worker thread, never on the event loop.
    message = await run_in_threadpool(persist, session, job)
    set_owner_cookie(response, token)  # Refreshes the expiry on every new job.
    # Off the event loop: an unreachable broker blocks until its connect timeout.
    await run_in_threadpool(outbox.publish_now, session, message)
    return job


def persist(session: Session, job: GenerationJob) -> outbox.OutboxMessage:
    """Save a new job together with its queue message, in one transaction."""
    try:
        session.add(job)
        message = outbox.add(session, job.id)  # Same transaction: no job without its queue message.
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        shutil.rmtree(job_directory(job.id), ignore_errors=True)
        logger.exception("Could not persist job %s", job.id)
        raise HTTPException(503, "Storage is unavailable. Please try again shortly.") from exc
    # After the commit the job will run, so its media must stay even if this read fails (503 via the
    # global handler; the job then appears in the browser's history).
    session.refresh(job)
    return message


EXPIRED = "This result has expired and its media was deleted. Create a new one."


def require_media(job: GenerationJob) -> None:
    """410 Gone once retention has deleted the job's files (after the owner check, never before)."""
    if job.purged_at is not None:
        raise HTTPException(410, EXPIRED)


def expire_if_stale(session: Session, jobs) -> None:
    """Report stuck jobs as failed the moment their owner looks, without a write on every poll: only
    jobs being returned that have actually timed out are updated. The scheduler sweeps the rest."""
    stale = [job for job in jobs if is_stale(job)]
    if stale:
        expire_stale(session, [job.id for job in stale])
        for job in stale:
            session.refresh(job)


def find_job(job_id: UUID, session: Session, token: str | None) -> GenerationJob:
    job = session.get(GenerationJob, job_id)
    # Missing, ownerless, and other people's jobs are indistinguishable to the caller.
    if not job or not job.owner_hash or not token or not hmac.compare_digest(job.owner_hash, owner_hash(token)):
        raise HTTPException(404, "Generation not found.")
    expire_if_stale(session, [job])
    return job


Owner = Depends(owner_token)


@router.get("/generations", response_model=JobHistory)
def list_generations(limit: int = Query(20, ge=1, le=50), token: str | None = Owner,
                     session: Session = Depends(get_session)):
    """The calling browser's own jobs, newest first. No owner cookie means no history."""
    if not token:
        return {"items": []}
    jobs = list(session.scalars(select(GenerationJob).where(GenerationJob.owner_hash == owner_hash(token))
                                .order_by(GenerationJob.created_at.desc()).limit(limit)))
    expire_if_stale(session, jobs)
    return {"items": jobs}


@router.get("/generations/{job_id}", response_model=JobResponse)
def get_generation(job_id: UUID, token: str | None = Owner, session: Session = Depends(get_session)):
    return find_job(job_id, session, token)


@router.post("/generations/{job_id}/retry", response_model=JobResponse, status_code=202)
def retry_generation(job_id: UUID, token: str | None = Owner, session: Session = Depends(get_session)):
    job = find_job(job_id, session, token)
    require_media(job)
    if job.status != "failed":
        raise HTTPException(409, "Only failed generations can be retried.")
    # A conditional update prevents concurrent retries from publishing duplicate work.
    result = session.execute(update(GenerationJob).where(GenerationJob.id == job_id,
        GenerationJob.status == "failed", GenerationJob.purged_at.is_(None)).values(status="queued", stage="validating", progress=0,
            auto_retries=0, error_code=None, error_message=None, completed_at=None, updated_at=datetime.now(timezone.utc)))
    if not result.rowcount:
        session.rollback()
        raise HTTPException(409, "This generation has already been retried.")
    message = outbox.add(session, job_id)  # Committed with the status change, or not at all.
    session.commit()
    session.refresh(job)
    outbox.publish_now(session, message)
    return job


MISSING_INPUTS = "The original files for this generation are no longer available. Please create a new generation."


def link_or_copy(source: Path, target: Path) -> None:
    # A hard link costs no space; inputs are never modified in place (writes go through os.replace).
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def carry_inputs(source: GenerationJob, directory: Path, with_music: bool) -> dict[str, str | None]:
    """Give a new version its own copy of a finished job's stored inputs, so each job stays self-contained."""
    origin = job_directory(source.id)
    def carry(stored: str | None) -> str | None:
        if not stored:
            return None
        path = Path(stored).resolve()
        if path.parent != origin or not path.is_file():
            raise HTTPException(409, MISSING_INPUTS)
        link_or_copy(path, directory / path.name)
        return str(directory / path.name)
    paths = {"input_file_path": carry(source.input_file_path), "source_media_path": carry(source.source_media_path),
             "logo_path": carry(source.logo_path), "music_path": carry(source.music_path) if with_music else None}
    storyboard = origin / "storyboard.jpg"
    if source.input_type == "video" and storyboard.is_file():
        link_or_copy(storyboard, directory / storyboard.name)
    return paths


@router.post("/generations/{job_id}/variants", response_model=JobResponse, status_code=202)
def create_variant(job_id: UUID, response: Response, body: VariantRequest | None = None,
                   token: str | None = Owner, session: Session = Depends(get_session)):
    """Make another version of a finished result from its stored inputs, optionally in another format."""
    source = find_job(job_id, session, token)
    require_media(source)
    platform, format = (body.platform or None, body.format or None) if body else (None, None)
    if (platform is None) != (format is None):
        raise HTTPException(422, "Choose both a platform and a format, or neither.")
    platform, format = platform or source.platform, format or source.format
    output = get_format(platform, format)
    if output is None:
        raise HTTPException(422, "Choose a supported platform and format.")
    if source.status != "completed":
        raise HTTPException(409, "Only finished generations can have new versions.")
    new_id = uuid4()
    directory = create_job_directory(new_id)
    try:
        paths = carry_inputs(source, directory, with_music=output.kind == "video")
    except HTTPException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    except OSError as exc:
        shutil.rmtree(directory, ignore_errors=True)
        logger.exception("Could not copy inputs for a version of job %s", job_id)
        raise HTTPException(503, "Media storage is unavailable. Please try again shortly.") from exc
    root = source.root_id or source.id
    fields = dict(input_type=source.input_type, source_url=source.source_url,
                  source_metadata=dict(source.source_metadata) if source.source_metadata else None,
                  brand_context=dict(source.brand_context or {}), owner_hash=owner_hash(token),
                  platform=platform, format=format, generation_mode=get_settings().generation_mode,
                  parent_id=source.id, root_id=root, **paths)
    family = or_(GenerationJob.id == root, GenerationJob.root_id == root)
    for attempt in range(3):
        # Numbers are unique per family (database index); a concurrent request taking ours means recount.
        try:
            number = (session.scalar(select(func.max(GenerationJob.variant)).where(family)) or 1) + 1
            job = GenerationJob(id=new_id, variant=number, **fields)
            session.add(job)
            message = outbox.add(session, new_id)  # Same transaction as the new job.
            session.commit()
            break
        except IntegrityError:
            session.rollback()
            if attempt < 2:
                continue
            shutil.rmtree(directory, ignore_errors=True)
            raise HTTPException(409, "Another version was created at the same time. Please try again.")
        except SQLAlchemyError as exc:
            session.rollback()
            shutil.rmtree(directory, ignore_errors=True)
            logger.exception("Could not persist a version of job %s", job_id)
            raise HTTPException(503, "Storage is unavailable. Please try again shortly.") from exc
    session.refresh(job)  # outside the cleanup above: once committed, the version will run
    set_owner_cookie(response, token)
    outbox.publish_now(session, message)
    return job


@router.get("/generations/{job_id}/content")
def get_content(job_id: UUID, token: str | None = Owner, session: Session = Depends(get_session)):
    job = find_job(job_id, session, token)
    if job.status != "completed":
        raise HTTPException(409, "The generation is not complete yet.")
    return {"generation_mode": job.generation_mode, "analysis": job.product_analysis,
            "content": job.generated_content, "post_text": job.post_text, "source": job.source_metadata}


def completed_asset(job: GenerationJob, name: Literal["output", "thumbnail"]) -> Path:
    require_media(job)
    if job.status != "completed":
        raise HTTPException(409, "The generation is not complete yet.")
    stored = job.output_file_path if name == "output" else job.thumbnail_file_path
    if not stored:
        raise HTTPException(404, "This result is missing.")
    path = Path(stored).resolve()
    if path.parent != job_directory(job.id):
        raise HTTPException(404, "This result is unavailable.")
    if not path.is_file():
        raise HTTPException(404, "This result is missing. Please create a new generation.")
    return path


def media_type(path: Path) -> str:
    return "image/jpeg" if path.suffix == ".jpg" else "video/mp4"


@router.get("/generations/{job_id}/download")
def download(job_id: UUID, token: str | None = Owner, session: Session = Depends(get_session)):
    job = find_job(job_id, session, token)
    path = completed_asset(job, "output")
    return FileResponse(path, media_type=media_type(path), filename=f"{job.platform}-{job.format}-{job_id}{path.suffix}",
                        headers={"Cache-Control": "private, no-store"})


@router.get("/generations/{job_id}/preview")
def preview(job_id: UUID, token: str | None = Owner, session: Session = Depends(get_session)):
    path = completed_asset(find_job(job_id, session, token), "output")
    return FileResponse(path, media_type=media_type(path), headers={"Cache-Control": "private, no-store"})


@router.get("/generations/{job_id}/thumbnail")
def thumbnail(job_id: UUID, token: str | None = Owner, session: Session = Depends(get_session)):
    return FileResponse(completed_asset(find_job(job_id, session, token), "thumbnail"), media_type="image/jpeg",
                        headers={"Cache-Control": "private, no-store"})
