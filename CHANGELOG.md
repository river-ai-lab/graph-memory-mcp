# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
