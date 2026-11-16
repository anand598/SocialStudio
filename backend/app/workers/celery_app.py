from pathlib import Path
from celery import Celery
from app.core.config import get_settings

settings = get_settings()
celery_app = Celery("social", broker=settings.celery_broker_url, include=["app.workers.tasks"])
celery_app.conf.update(task_ignore_result=True, task_acks_late=True,
    task_reject_on_worker_lost=True, worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=3, broker_transport_options={"visibility_timeout": settings.stale_job_seconds},
    task_soft_time_limit=settings.stale_job_seconds - 30, task_time_limit=settings.stale_job_seconds,
    beat_schedule={"expire-abandoned-jobs": {"task": "social.recover_stale", "schedule": 60.0}})

# Explicit offline development transport; normal deployments use Redis.
if settings.celery_broker_url == "filesystem://":
    queue = Path(settings.local_storage_path).resolve() / "queue"
    queue.mkdir(parents=True, exist_ok=True)
    celery_app.conf.broker_transport_options = {
        "data_folder_in": str(queue), "data_folder_out": str(queue),
        "control_folder": str(queue / "control"), "store_processed": False,
    }
