from pathlib import Path
from celery import Celery
from celery.signals import worker_ready
from app.core.config import get_settings

settings = get_settings()


def broker_transport_options(stale_job_seconds: int) -> dict:
    """Redis transport options. kombu's Redis transport ignores broker_connection_timeout, and its
    socket timeouts default to None: without these, publishing to an unreachable or hung broker blocks
    for minutes (or forever), tying up API request threads and the outbox relay."""
    return {"visibility_timeout": stale_job_seconds, "socket_connect_timeout": 3, "socket_timeout": 5}


celery_app = Celery("social", broker=settings.celery_broker_url, include=["app.workers.tasks"])
celery_app.conf.update(task_ignore_result=True, task_acks_late=True,
    task_reject_on_worker_lost=True, worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=3, broker_transport_options=broker_transport_options(settings.stale_job_seconds),
    task_soft_time_limit=settings.stale_job_seconds - 30, task_time_limit=settings.stale_job_seconds,
    beat_schedule={"expire-abandoned-jobs": {"task": "social.recover_stale", "schedule": 60.0},
                   "purge-expired-media": {"task": "social.purge_expired", "schedule": 3600.0}})

# Explicit offline development transport; normal deployments use Redis.
if settings.celery_broker_url == "filesystem://":
    queue = Path(settings.local_storage_path).resolve() / "queue"
    queue.mkdir(parents=True, exist_ok=True)
    celery_app.conf.broker_transport_options = {
        "data_folder_in": str(queue), "data_folder_out": str(queue),
        "control_folder": str(queue / "control"), "store_processed": False,
    }


@worker_ready.connect
def purge_when_worker_starts(sender=None, **kwargs):
    """Interval schedules first fire one interval after the scheduler starts, so frequent restarts
    could postpone retention indefinitely; purge once whenever a worker comes up (every deploy).
    Hooked to the worker, not the scheduler: an embedded scheduler on macOS runs in a spawned
    process that never imports this module, so its signal handlers would not be connected."""
    celery_app.send_task("social.purge_expired")
