import asyncio
import logging
import time
import os
import shutil
from pathlib import Path
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from alembic.config import Config
from alembic.script import ScriptDirectory
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from app.db.session import engine
from app.api.generations import router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.limits import UploadLimitsMiddleware
from app.services.outbox import OutboxRelay

settings = get_settings()
logger = logging.getLogger("social.api")



@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    # Publishes queue messages the request path could not (see app.services.outbox). It lives in the API,
    # not in Celery, so it keeps retrying while the broker is down; every API process runs one safely.
    relay = OutboxRelay() if get_settings().outbox_relay_enabled else None
    app.state.outbox_relay = relay
    if relay:
        relay.start()
    yield
    if relay:
        relay.stop()
    engine.dispose()


app = FastAPI(title="Social Content Generator", version="0.1.0", lifespan=lifespan)
@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError):
    logger.error("Database operation failed type=%s", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "The database is unavailable. Please try again shortly."})


app.include_router(router)
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin],
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type"], allow_credentials=True)


class HealthResponse(BaseModel):
    status: str


class ReadinessResponse(BaseModel):
    status: str
    dependencies: dict[str, str]


@app.middleware("http")
async def log_request(request: Request, call_next):
    started = time.monotonic()
    response = await call_next(request)
    logger.info("%s %s status=%s duration_ms=%.1f", request.method, request.url.path,
                response.status_code, (time.monotonic() - started) * 1000)
    return response


@app.get("/api/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@lru_cache
def latest_migration() -> str:
    """Head revision of the shipped migration scripts, so readiness never goes stale."""
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head()


def check_database() -> str:
    try:
        with engine.connect() as conn:
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            if revision != latest_migration():
                return "migration_required"
        return "ok"
    except Exception:
        return "unavailable"


async def check_redis() -> str:
    try:
        async with Redis.from_url(settings.redis_url, socket_connect_timeout=3, socket_timeout=3) as client:
            await client.ping()
        return "ok"
    except Exception:
        return "unavailable"


async def check_ollama() -> str:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
            response.raise_for_status()
            names = {model["name"] for model in response.json()["models"]}
            required = {settings.ollama_model, settings.ollama_vision_model}
            return "ok" if required <= names else "model_missing"
    except Exception:
        return "unavailable"


@app.get("/api/v1/ready", response_model=ReadinessResponse, responses={503: {"model": ReadinessResponse}})
async def ready():
    database, redis, ollama = await asyncio.gather(
        asyncio.to_thread(check_database), check_redis(), check_ollama())
    dependencies = {"database": database, "redis": redis, "ollama": ollama}
    if settings.generation_mode == "demo":
        dependencies["ollama"] = "not_required_demo"
    if settings.celery_broker_url == "filesystem://":
        directory = Path(settings.local_storage_path).resolve() / "queue"
        dependencies["redis"] = "not_required_filesystem" if directory.is_dir() and os.access(directory, os.W_OK) else "unavailable"
    dependencies["media_tools"] = "ok" if shutil.which("ffmpeg") and shutil.which("ffprobe") else "unavailable"
    healthy = all(value in {"ok", "not_required_demo", "not_required_filesystem"} for value in dependencies.values())
    return JSONResponse(status_code=200 if healthy else 503,
                        content={"status": "ready" if healthy else "not_ready", "dependencies": dependencies})


app.add_middleware(UploadLimitsMiddleware)
