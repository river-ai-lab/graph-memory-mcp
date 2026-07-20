# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added

- **Stable node ids**: every node gets a `uid` (UUID hex); all tools accept/return it as `node_id`. Legacy nodes are backfilled at server startup; `uid` range indexes are created automatically
- **`possible_duplicates`** in `create_node` response — server-side backstop for "search before create"
- **`get_brief`** tool — session warm-up: top facts by connectivity/recency, `CONTRADICTS` pairs, stale facts, stats
- **Usage tracking**: `search` / `recall_context` bump `access_count` / `last_accessed_at`; `get_brief.stale_facts` lists facts not recalled for `STALE_FACTS_DAYS`
- **CI** (GitHub Actions): pre-commit + pytest against a FalkorDB service container
- `get_trace(directed=false)` — undirected shortest path; `recall_context` paths are undirected (consistent with its BFS)
- `docs/memory_policy_cheatsheet.md` — compact agent policy (full doc stays the reference)
- `owner_id` validated on **all** handlers (reads included); `node_id` format validated before queries
- `MAX_SEARCH_LIMIT` (default 100) caps `limit` on search-like tools
- **`metadata_filter`** in `search` / `recall_context` — native in-DB filtering over promoted metadata keys (`type`, `tags`, `confidence_min`); keys are mirrored to flat node properties at write time
- **`create_nodes`** — bulk ingest (≤200 items) in one query with batched embeddings
- **`export_owner` / `import_owner`** — owner backup/migration; nodes merge by `uid`, embeddings preserved or regenerated
- **`/metrics`** (Prometheus) — handler latency/success, cache hit/miss, node counts by label
- **Time-aware recall** — `recall_context` score multiplied by recency (`RECALL_RECENCY_WEIGHT`, half-life) and usage (`RECALL_USAGE_WEIGHT`) factors
- **`as_of`** in `get_node` — read node state at a point in time via `FactVersion` snapshots
- **Embedding prompt prefixes** (`EMBEDDING_QUERY_PREFIX` / `EMBEDDING_PASSAGE_PREFIX`) — e5-family models need `"query: "` / `"passage: "`; empty by default (enabling on an existing corpus requires re-embedding)
- **Agent/admin separation** — admin ops moved to HTTP `/admin/*` routes (optional `ADMIN_TOKEN`); `test_connection` / `ensure_vector_indexes` / `export_owner` / `import_owner` are no longer MCP tools unless `MCP_EXPOSE_ADMIN_TOOLS=true`
- `limitations.md` — living document of known weaknesses and improvement paths
- **Dedup job scalability** — candidate neighbor lookup now uses the ANN vector index (HNSW) instead of an exact scan over the owner corpus; overlapping candidate groups are merged via union-find into disjoint components
- **Graph-per-owner storage layout** — every owner lives in its own FalkorDB graph (`{FALKORDB_GRAPH}_{owner_id}`): per-owner vector/range indexes (no ANN dilution between tenants), physically isolated data, owner discovery via `GRAPH.LIST`. **Breaking**: data in the old single shared graph is not migrated automatically
- **`ingest_knowledge`** — one call to persist agent-extracted knowledge from a document/conversation: source node, facts with provenance (`source.ref = "doc#N"`), `EXTRACTED_FROM` links, triplets; idempotent re-ingest updates facts in place
- **Backups** — AOF persistence in docker-compose (`--appendonly yes`), `scripts/backup.sh` (BGSAVE + rotated RDB copies), README section
- **`VERSIONING_DEFAULT`** — config default for `versioning` when callers omit it on `update_node`/`upsert_node`
- **Export pagination / batch import** — `export_owner(limit, offset, section)` with `has_more`/`next_offset`; `import_owner` merges nodes/relations in UNWIND batches of 200
- **Iterative BFS traversal** — `get_context` / `recall_context` expand one hop per query with a total node budget (no `[*0..depth]` path explosion on hub nodes); multi-source with per-seed hop labels for ranking
- **Stale auto-archive** — `JOB_ARCHIVE_STALE_ENABLED=true` archives active facts not recalled for `STALE_FACTS_DAYS` (safety checks preserved; off by default)
- **Owner graph lifecycle** — `DELETE /admin/owners/{owner_id}` and `POST /admin/prune-empty-owners`; job metrics (`graph_memory_job_*`) in `/metrics`; graph-size gauge refresh cached (≤1/min)
- **Docs** — `docs/admin.md` (operator API), rewritten compact agent policy (full + cheat sheet)
- **Scoping model & reserved metadata keys** — `owner_id` (hard isolation, own graph) → `metadata.project` (soft partition, promoted + range-indexed + filterable) → `metadata.created_by` (attribution). Reserved keys validated via typed model (`ReservedMetadata`, pydantic, `extra="allow"`); wrong types → `memory_validation_error`; non-reserved keys stay free-form. Documented in policy + cheat sheet

### Changed

- `memory_policies_for_LLM.md` moved from `graph_memory_mcp/resources/` to `docs/` (canonical docs location for clone + uv); MCP resource still serves that file; prefer AGENTS.md / client rules over relying on `resources/read`
- All Cypher queries parametrized (no string interpolation of values); embeddings passed as `vecf32($param)`
- `create_relation` validates edge property keys (identifiers only)
- `upsert_node` serialized per `(owner_id, node_type, source.ref)` via Redis lock — concurrent upserts no longer create duplicates
- `health_check` reports per-component flags plus aggregate `healthy` (was: all flags zeroed on any failure)
- `get_stats` counts only `Fact`/`Entity` nodes (no `FactVersion`/`Collection`)
- Version reported from package metadata (removed hardcoded "2.0.0")
- `recall_context` `min_hop` is now the true minimal hop distance; `include_paths` defaults to `false`
- Embedding cache honors `CACHE_EMBEDDINGS_*` config (was a fixed hidden LRU)
- `create_triplet` / `search_triplets` merge entities on normalized name (`name_norm`); original casing kept in `text`; legacy entities backfilled at startup
- Repo layout normalized: root `__init__.py` removed; `server_simple` now only overrides node write tools (shared tools inherited)
- ANN sizing count query cached per client for 60s; dedup marks duplicates with `merged_into`

### Fixed

- `delete_node` cascades `FactVersion` snapshots
- Dedup/archive jobs no longer interpolate `owner_id` into queries; invalid discovered owners are skipped

## [0.1.1] - 2026-06-06

### Added

- **`search_type`** for MCP `search`: `pre_filter` (owner-scoped, default) and `post_filter` (global ANN + filter)
- Config/env: `SEARCH_TYPE`, `POST_FILTER_ANN_K_MIN`, `POST_FILTER_ANN_K_MAX`
- **`owner_scoped_search`** module; dedup job uses owner-scoped similarity queries
- **Docker Compose** + `scripts/falkordb-up.sh` / `scripts/test.sh` for local FalkorDB and full test runs
- **`upsert_node`** on simple server profile; inline `links` on upsert update path
- Graph Explorer GUI docs; relation policy (`RELATION_*` env)
- Auto vector index creation on search / auto_link; `ensure_vector_indexes` tool
- `get_context` pagination (`offset`, `has_more`); expanded agent docs (`memory_policies_for_LLM.md`, FAQ)

### Changed

- README: `uv sync`, agent policies, Streamable HTTP smoke test, FalkorDB via compose
- `FalkorDBClient.redis_client` property for background job locks
- CPU-only PyTorch via `[tool.uv.sources]`; dev deps in uv lockfile

### Fixed

- Job locks use typed `redis_client` instead of missing attribute on `FalkorDBClient`
- `upsert_node` applies `links` on update (not only create); forwards `link_errors` / `link_warnings`

## [0.1.0] - 2026-02-11

Initial public release.

[0.1.1]: https://github.com/river-ai-lab/graph-memory-mcp/releases/tag/v0.1.1
[0.1.0]: https://github.com/river-ai-lab/graph-memory-mcp/releases/tag/v0.1.0
