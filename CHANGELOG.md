# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

Owner-scoped memory hardening on top of 0.1.1. **Breaking:** one FalkorDB graph per `owner_id` (`{FALKORDB_GRAPH}_{owner_id}`); old shared-graph data is not migrated.

### Added

- Stable node `uid` (tools use it as `node_id`); startup backfill + indexes
- Graph-per-owner storage; per-owner vector/range indexes; `GRAPH.LIST` discovery
- Scoping: `owner_id` (hard) → `metadata.project` (soft, filterable) → `metadata.created_by`; typed `ReservedMetadata`
- Agent tools: `get_brief`, `ingest_knowledge`, `create_nodes`, `metadata_filter`, `possible_duplicates`, `as_of`, time-aware `recall_context`
- Admin HTTP `/admin/*` (+ optional `ADMIN_TOKEN`); `/metrics` (handlers, cache, jobs); owner delete / prune-empty
- Export/import with pagination + batch UNWIND; AOF in compose; `scripts/backup.sh`
- Iterative BFS for `get_context` / `recall_context`; stale archive job (`JOB_ARCHIVE_STALE_ENABLED`)
- Embedding prefixes (`EMBEDDING_QUERY_PREFIX` / `EMBEDDING_PASSAGE_PREFIX`); `VERSIONING_DEFAULT`; `MAX_SEARCH_LIMIT`
- CI (pre-commit + pytest + FalkorDB); `docs/admin.md`, policy + cheat sheet under `docs/`

### Changed

- All Cypher parametrized; relation property-key sanitization; `owner_id` / `node_id` validated everywhere
- `upsert_node` Redis-locked per `(owner_id, node_type, source.ref)`
- Admin ops off MCP by default (`MCP_EXPOSE_ADMIN_TOOLS=true` to re-expose)
- Dedup job uses ANN + union-find; entity merge via `name_norm`
- `memory_policies_for_LLM.md` lives in `docs/` (MCP resource still serves it; prefer AGENTS.md / client rules)
- `docs/roadmap.md` — unfinished items only
- Docs refreshed laconic (features, FAQ, admin, jobs); README + comparison keep fuller positioning; smoke example uses `health_check`
- Repo layout: root `__init__.py` removed; policy moved out of package `resources/`

### Fixed

- `delete_node` cascades `FactVersion`; jobs skip invalid owners / no owner_id interpolation
- `health_check` aggregate `healthy`; `get_stats` counts only Fact/Entity
- `recall_context` true `min_hop`; `include_paths` default `false`

## [0.1.1] - 2026-06-06

### Added

- **`search_type`** for MCP `search`: `pre_filter` (owner-scoped, default) and `post_filter` (ANN + filter)
- Config/env: `SEARCH_TYPE`, `POST_FILTER_ANN_K_MIN`, `POST_FILTER_ANN_K_MAX`
- **`owner_scoped_search`** module; dedup job uses owner-scoped similarity queries
- **Docker Compose** + `scripts/falkordb-up.sh` / `scripts/test.sh`
- **`upsert_node`** on simple server profile; inline `links` on upsert update path
- Graph Explorer GUI docs; relation policy (`RELATION_*` env)
- Auto vector index creation on search / auto_link; `ensure_vector_indexes` tool
- `get_context` pagination (`offset`, `has_more`); agent policy docs + FAQ

### Changed

- README: `uv sync`, agent policies, Streamable HTTP smoke test, FalkorDB via compose
- `FalkorDBClient.redis_client` for background job locks
- CPU-only PyTorch via `[tool.uv.sources]`; dev deps in uv lockfile

### Fixed

- Job locks use typed `redis_client` instead of missing attribute on `FalkorDBClient`
- `upsert_node` applies `links` on update (not only create); forwards `link_errors` / `link_warnings`

## [0.1.0] - 2026-02-11

Initial public release.

[0.1.1]: https://github.com/river-ai-lab/graph-memory-mcp/releases/tag/v0.1.1
[0.1.0]: https://github.com/river-ai-lab/graph-memory-mcp/releases/tag/v0.1.0
