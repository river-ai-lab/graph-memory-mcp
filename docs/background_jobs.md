# Background jobs

Optional (off by default). Normative API: [features.md](./features.md). APScheduler + Redis locks; per-owner; retries with backoff.

## Dedup

Merges near-duplicate Facts (ANN candidates, union-find). Config: `JOB_DEDUPLICATE_ENABLED`, `JOB_DEDUPLICATE_CRON`, `JOB_DEDUPLICATE_*_THRESHOLD`.

## Archive

Sets `status=archived` for expired TTL, including facts that still have relations. With `JOB_ARCHIVE_STALE_ENABLED`, also archives active Facts not recalled for `STALE_FACTS_DAYS`, and that path still skips Facts with active relations. Config: `JOB_ARCHIVE_ENABLED`, `JOB_ARCHIVE_CRON`, …

Locks: `JOBS_LOCK_TTL_SECONDS`. Metrics: `graph_memory_job_*` on `/metrics`.
