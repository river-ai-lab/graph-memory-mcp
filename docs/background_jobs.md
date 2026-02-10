# MCP Graph Memory — Background Jobs (non-normative)

This document describes **optional background jobs** and their runtime behavior.
The normative API contract lives in `docs/features.md`.

All jobs are configurable via `config.py` and run via APScheduler with retry logic and owner isolation.

## deduplication job

**What:** Merges semantically similar facts (creates merged fact, deletes originals, redirects relationships).

**Config keys:**
- `job_deduplicate_enabled` (bool, default: false)
- `job_deduplicate_cron` (string, default: "0 * * * *")
- `job_deduplicate_hours_threshold` (int, default: 24)
- `job_deduplicate_similarity_threshold` (float, default: 0.95)

**Guarantees:**
- Lock-based execution (prevents concurrent runs)
- Owner isolation (processes per `owner_id`)
- Incremental (processes only facts not checked recently)

## archival job

**What:** Archives facts with expired TTL (sets `status="archived"`).

**Config keys:**
- `job_archive_enabled` (bool, default: false)
- `job_archive_cron` (string, default: "0 3 * * 0")

**Guarantees:**
- Lock-based execution
- Owner isolation
- Preserves facts with active relationships

## Job Execution

- Scheduled via **APScheduler** (cron expressions)
- Retry logic with exponential backoff (`job_retry_max_attempts`, `job_retry_backoff_base`, `job_retry_backoff_max`)
- Idempotent and safe to run concurrently (with locking)
- Lock TTL: `jobs_lock_ttl_seconds` (default: 600)
