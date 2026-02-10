import logging
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Awaitable, Callable, Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from graph_memory_mcp.config import load_mcp_server_config
from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.jobs.archive_old_facts import archive_old_facts
from graph_memory_mcp.jobs.deduplicate_facts import deduplicate_facts

logger = logging.getLogger(__name__)


JobFunc = Callable[[], Awaitable[None]]


_scheduler: Optional[AsyncIOScheduler] = None
_last_run: Dict[str, datetime] = {}
_last_error: Optional[str] = None
_scheduler_lock = RLock()


async def _run_instrumented(job_name: str, job_func: JobFunc) -> None:
    """Run a single job with logging."""
    global _last_error

    logger.info("Job started", extra={"job_name": job_name})
    try:
        await job_func()
        with _scheduler_lock:
            _last_run[job_name] = datetime.now(UTC)
        logger.info("Job finished", extra={"job_name": job_name})
    except Exception as exc:  # noqa: BLE001
        with _scheduler_lock:
            _last_error = str(exc)
        logger.error(
            "Job failed",
            extra={"job_name": job_name, "error": str(exc)},
        )


def _ensure_scheduler() -> AsyncIOScheduler:
    global _scheduler

    with _scheduler_lock:
        if _scheduler is None:
            _scheduler = AsyncIOScheduler()
        return _scheduler


def start_scheduler() -> AsyncIOScheduler:
    """Create scheduler instance, register jobs and start it.

    Idempotent: safe to call multiple times.
    """
    scheduler = _ensure_scheduler()

    if scheduler.running:
        return scheduler

    config = load_mcp_server_config()

    if not config.enabled:
        logger.info("Background scheduler: memory server disabled, not starting")
        return scheduler

    if not config.jobs_enabled:
        logger.info("Background scheduler: jobs are disabled in config, not starting")
        return scheduler

    # Initialize FalkorDB client
    db = FalkorDBClient(
        host=config.falkordb_host,
        port=config.falkordb_port,
        graph_name=config.falkordb_graph,
        password=config.falkordb_password,
    )

    # Test connection
    health = db.health_check()
    if health.get("status") != "healthy":
        logger.warning(
            "Background scheduler: failed to connect to FalkorDB, not starting"
        )
        return scheduler

    # Wrapper functions for AsyncIOScheduler
    async def run_deduplicate_facts():
        await _run_instrumented(
            "deduplicate_facts", lambda: deduplicate_facts(db=db, config=config)
        )

    async def run_archive_old_facts():
        await _run_instrumented(
            "archive_old_facts", lambda: archive_old_facts(db=db, config=config)
        )

    if config.job_deduplicate_enabled:
        scheduler.add_job(
            run_deduplicate_facts,
            CronTrigger.from_crontab(config.job_deduplicate_cron),
            id="deduplicate_facts",
            replace_existing=True,
        )

    if config.job_archive_enabled:
        scheduler.add_job(
            run_archive_old_facts,
            CronTrigger.from_crontab(config.job_archive_cron),
            id="archive_old_facts",
            replace_existing=True,
        )

    if not scheduler.get_jobs():
        logger.info(
            "Background scheduler: jobs_enabled=true, but no jobs enabled; not starting"
        )
        return scheduler

    scheduler.start()
    logger.info(
        "Background scheduler started",
        extra={"jobs": [job.id for job in scheduler.get_jobs()]},
    )
    return scheduler


def shutdown_scheduler() -> None:
    """Stop scheduler if it is running."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Background scheduler stopped")
    elif _scheduler:
        _scheduler = None


async def run_job_now(job_name: str) -> Dict[str, Any]:
    """Run a known job immediately via API."""
    config = load_mcp_server_config()

    db = FalkorDBClient(
        host=config.falkordb_host,
        port=config.falkordb_port,
        graph_name=config.falkordb_graph,
        password=config.falkordb_password,
    )

    # Test connection
    health = db.health_check()
    if health.get("status") != "healthy":
        return {
            "success": False,
            "error": "Failed to connect to FalkorDB",
        }

    if job_name == "deduplicate_facts":
        await _run_instrumented(
            job_name, lambda: deduplicate_facts(db=db, config=config)
        )
    elif job_name == "archive_old_facts":
        await _run_instrumented(
            job_name, lambda: archive_old_facts(db=db, config=config)
        )
    else:
        return {
            "success": False,
            "error": f"Unknown job '{job_name}'",
        }

    return {
        "success": True,
        "job_name": job_name,
        "last_run": (
            _last_run.get(job_name).isoformat() if job_name in _last_run else None
        ),
    }


def get_scheduler_health() -> Dict[str, Any]:
    """Return lightweight scheduler health information."""
    scheduler = _scheduler
    running = bool(scheduler and scheduler.running)

    jobs_info = []
    if scheduler:
        for job in scheduler.get_jobs():
            jobs_info.append(
                {
                    "id": job.id,
                    "next_run_time": (
                        job.next_run_time.isoformat() if job.next_run_time else None
                    ),
                }
            )

    # Copy data under lock to avoid race conditions
    with _scheduler_lock:
        last_run_copy = dict(_last_run)
        last_error_copy = _last_error

    return {
        "running": running,
        "jobs": jobs_info,
        "last_run": {name: ts.isoformat() for name, ts in last_run_copy.items()},
        "last_error": last_error_copy,
    }
