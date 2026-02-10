Background jobs infrastructure (APScheduler)
============================================

This package contains infrastructure for background jobs implemented on top of **APScheduler**.

Available Jobs
--------------

The following background jobs are implemented and configurable:

1.  **Deduplication (`deduplicate_facts`)**
    -   **Function**: Periodic search and merge of duplicate facts and entities using vector similarity.
    -   **Config**: Controlled by `JOB_DEDUPLICATE_ENABLED`, `JOB_DEDUPLICATE_CRON`, etc.
    -   **Implementation**: `graph_memory_mcp/jobs/deduplicate_facts.py`

2.  **Archival (`archive_old_facts`)**
    -   **Function**: Archives facts that have exceeded their Time-To-Live (TTL).
    -   **Config**: Controlled by `JOB_ARCHIVE_ENABLED`, `JOB_ARCHIVE_CRON`.
    -   **Implementation**: `graph_memory_mcp/jobs/archive_old_facts.py`

Infrastructure Features
-----------------------

-   **Cron-like scheduling**: Using `AsyncIOScheduler` and `CronTrigger`.
-   **Distributed Locking**: Redis-based locking prevents multiple workers from running the same job concurrently.
-   **Retry Logic**: Exponential backoff for transient failures (e.g., database connection).
-   **Observability**: Logging of job start/finish/failure events.
-   **Health Check**: `get_scheduler_health()` returns job status and last run times.

How to add a new job
--------------------

1.  Create a module in `graph_memory_mcp/jobs/` (e.g., `my_new_job.py`) and define a coroutine:

    ```python
    import logging
    from graph_memory_mcp.config import MCPServerConfig
    from graph_memory_mcp.graph_memory.database import FalkorDBClient

    logger = logging.getLogger(__name__)

    async def my_new_job(db: FalkorDBClient, config: MCPServerConfig) -> None:
        logger.info("My job started")
        # Your logic here
        logger.info("My job finished")
    ```

2.  Register the job in `start_scheduler()` in `graph_memory_mcp/jobs/scheduler.py`:

    ```python
    from graph_memory_mcp.jobs.my_new_job import my_new_job

    async def run_my_job():
        await _run_instrumented("my_new_job", lambda: my_new_job(db=db, config=config))

    if config.my_job_enabled:
        scheduler.add_job(
            run_my_job,
            CronTrigger.from_crontab(config.my_job_cron),
            id="my_new_job",
            replace_existing=True,
        )
    ```

3.  (Optional) add manual triggering to `run_job_now()` in `scheduler.py`.
