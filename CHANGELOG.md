# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added

- Explorer node text preview: **On hover** (default) or **Always**. Stored in `localStorage` as `gm_node_preview`. Always-mode labels hide when the map is zoomed out.
- `graph-memory-explorer --auth` with `GRAPH_MEMORY_API_KEY` or `--token` for `graph-memory-mcp --auth`. Tool calls omit `owner_id`.
- Token-mode API keys are a person (`name`) plus owner graphs (`projects`); writes record server-set `created_by` / `created_at` / `updated_by` / `updated_at`.
- `OWNER_SCOPE=client` (default) keeps the tool `owner_id`. `OWNER_SCOPE=header` ignores it and requires `X-Owner-Id` on `/mcp`.
- GROW ritual in the agent policies (Ground → Record → Orient → Write after meaningful work)
- Compact recall: `compact` on `search` / `recall_context`; responses always include `suggested_next`, `do_not`, `budget` (snippets under `COMPACT_RECALL_TOKEN_BUDGET`)
- `get_brief` returns an optional `about` anchor (`source.ref=about`) and recent facts without TTL, not a degree ranking
- Search rank is hybrid (`score` = cosine + identifier match + recency). Hits joined by an existing `CONTRADICTS` edge are returned in `contradiction_pairs`
- Default `search`, `recall_context`, and `get_context` omit facts that have `ttl_days`. `include_ttl=true` returns ones that have not expired. The server never assigns TTL. Expired TTL facts are archived even if they have relations.
- `create_node` / `upsert_node`: `auto_link` defaults to false. Pass true to add `MENTIONS` from a Fact to similar Entities.
- `get_context` and `recall_context` fill the node budget with `CONTRADICTS` and `FOLLOWS_FROM` before `MENTIONS`. `relation_priority` overrides the order; `exclude_relation_types` drops those edges.
- Task start is `get_brief`, then `search(..., compact=true)`. `suggested_next` hints at a possible next call; the agent chooses. A near-duplicate write returns `memory_duplicate` and must not be paraphrased again.

### Changed

- The server uses MCP 2 (`MCPServer`, `mcp>=2.3,<3`). FastMCP and mcp 1 are gone.
- PyPI packaging adds `README_pypi.md`, project metadata, and `.github/workflows/publish.yml` (OIDC, tags `v*`, environments `pypi` and `testpypi`).
- An `import_owner` call on `/mcp` is rejected when the body is larger than 4 MiB. `/admin/import` is not.
- Local embeddings default to ONNX Runtime and the fp32 `onnx/model.onnx` weights (`EMBEDDING_BACKEND=onnx`). `sentence-transformers` and torch moved to the optional `torch` extra (`uv sync --extra torch`, `EMBEDDING_BACKEND=torch`). Quantized ONNX files are not used. Pooling, L2 normalization, and `query:` / `passage:` prefixes are unchanged.
- In `client` and `header`, `created_by` / `updated_by` come from `metadata.created_by` and `metadata.updated_by`. Those keys stay in the stored JSON, and `update_node` still copies `metadata.created_by` onto `n.created_by`. Missing keys leave the fields empty. Token mode sets both fields from the key name and drops client-supplied audit fields. The server sets `created_at` / `updated_at`.
- `/admin` import keeps `created_*` / `updated_*` from the dump and fills them only when they are missing. The MCP `import_owner` tool strips them.
- `/internal/graph-size` requires `ADMIN_TOKEN` and `X-Owner-Id` in `client` and `header`. `token` uses the API key; a foreign project is HTTP 403.
- `OWNER_SCOPE=header` runs on `127.0.0.1` behind a gateway that sends `Authorization: Bearer $ADMIN_TOKEN`. `/mcp` returns 401 when that token is set and the bearer is missing or wrong. A non-loopback bind without `ADMIN_TOKEN` refuses to start; `ALLOW_INSECURE_HEADER=1` logs a warning and starts.
- `--simple` provenance argument `updated_at` is now `source_updated_at` (source document time). It is stored as `source.source_updated_at`, separate from the server's `updated_at`. Older `source.updated_at` values are still read.
- `OWNER_SCOPE=token` refuses to start without `ADMIN_TOKEN` and a readable keys file. `/admin` in that mode always requires `ADMIN_TOKEN`.
- `get_brief` returns `stale_count` instead of stale fact texts. `include_stale=true` returns those texts. `limit` still applies only to recent facts.

### Fixed

- Explorer search draws `CONTRADICTS` from `contradiction_pairs` and lists those pairs. Status "Any" includes outdated facts.
- Explorer draws one `CONTRADICTS` edge and highlights an existing relation on a path instead of adding the reverse arrow. Neighbor "+" uses stable `get_context` pages (`page=true`) so later pages do not skip nodes. Always-mode labels are one line and the layout leaves room for them. The brief counts outdated and archived facts. Details show validity and timestamps without opening metadata. Version history is readable. `get_trace` nodes include status, timestamps, and metadata. `--auth` shows the key's project in the owner field.
- Explorer context expansion sends `include_outdated` and `include_ttl`, so FOLLOWS_FROM / outdated neighbors appear on the map.
- Explorer details and search results show status, validity (`valid_from` / `valid_until`), TTL, and created/updated times. Unix-ms timestamps format correctly.
- `get_context` / `recall_context` return `status`, `created_at`, and `metadata` on walk nodes.
- Explorer styles `FOLLOWS_FROM` separately from related/mentions. Archived status has its own chip color.
- `--auth` and token mode resolve `owner_id` from the API key before validation. A call that omits it uses the key's first project. `--auth` still ignores a caller-supplied `owner_id`.
- `health_check` stays healthy when a sampled owner has data but no vector index. `vector_index_missing` lists those owners (up to 20). Search still creates the index.
- The first write for an owner (`create_node`, `create_nodes`, `upsert_node`, `create_relation`, entity creation, `import_owner`) creates Fact and Entity vector indexes. Later writes reuse a per-owner cache. Search still creates a missing index.

## [0.2.0] - 2026-07-20

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
- Packaging: drop dead `embeddings` / duplicate `dev` extras; pin torch/apscheduler/uvicorn; `httpx` + `numpy` in main deps (CPU torch via uv index)

### Fixed

- `delete_node` cascades `FactVersion`; jobs skip invalid owners / no owner_id interpolation
- `health_check` aggregate `healthy`; `get_stats` counts only Fact/Entity
- `recall_context` true `min_hop`; `include_paths` default `false`
- MCP tool default `owner_id` respects `DEFAULT_OWNER_ID` / `default_owner_id`
- `create_triplet` writes `metadata` (reserved keys on create; coalesce on match)
- `get_context` / BFS skip outdated/expired neighbors unless `include_outdated=true`
- `ingest_knowledge` fact keys: `facts[].ref` or `hash(text)` (not list index)
- `import_owner` accepts `FactVersion`; versions get `uid` for round-trip

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

[0.2.0]: https://github.com/river-ai-lab/graph-memory-mcp/releases/tag/v0.2.0
[0.1.1]: https://github.com/river-ai-lab/graph-memory-mcp/releases/tag/v0.1.1
[0.1.0]: https://github.com/river-ai-lab/graph-memory-mcp/releases/tag/v0.1.0
