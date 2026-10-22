# Background jobs

Off until `JOBS_ENABLED=true`. Archive and dedup both run. `JOB_ARCHIVE_ENABLED=false` or `JOB_DEDUPLICATE_ENABLED=false` turns one off.

`JOBS_OWNER_IDS` limits both jobs to those owners (`team_a` or `team_a,team_b`). Empty means every owner. `JOBS_PROCESS_ALL_OWNERS=true` runs for every owner even when the list is set.

Falkor takes a Redis lock per job and owner. Arcade does not. If the graph backend is down at process start, the scheduler retries every 30s.

## Dedup

Merges near-duplicate Facts and Entities (cosine ≥ `JOB_DEDUPLICATE_SIMILARITY_THRESHOLD`, default 0.95). Cron: `JOB_DEDUPLICATE_CRON` (hourly).

The survivor keeps its own `created_by` and `created_at`. The outdated duplicate keeps its own `created_by`; only its `updated_at` changes. A new edge copied onto the survivor keeps the duplicate edge's `created_by` / `created_at`, with `updated_at` set to the merge time. If that edge already exists on the survivor, its `created_*` stay and only `updated_at` becomes the merge time.

## Archive

Sets `status=archived` on Facts whose `expires_at` has passed, including Facts that still have relations. Cron: `JOB_ARCHIVE_CRON` (weekly).

`JOB_ARCHIVE_STALE_ENABLED=true` also archives active Facts not recalled for `STALE_FACTS_DAYS`. That path skips a Fact that still has an active neighbor.

Lock TTL: `JOBS_LOCK_TTL_SECONDS`. Metrics: `graph_memory_job_*` on `/metrics`.
