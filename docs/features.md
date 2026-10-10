# API contract

Normative tool signatures. Jobs: [background_jobs.md](./background_jobs.md). Agents: [memory_policies_for_LLM.md](./memory_policies_for_LLM.md). Admin: [admin.md](./admin.md).

**Storage:** FalkorDB by default, one graph per `owner_id` (`{FALKORDB_GRAPH}_{owner_id}`). `GRAPH_BACKEND=arcadedb` uses one ArcadeDB database per owner (`{ARCADE_DATABASE}_{owner_id}`), with that owner's own HNSW indexes. **IDs:** tools use stable `node_id` (= `uid`, UUID hex); legacy nodes backfilled at startup.

## Data model

**Common:** `node_id`, `owner_id`, `metadata`, `created_at`, `status` (`active`|`outdated`|`archived`), optional `ttl_days`/`expires_at`, `source` `{ref,type,uri,content_hash,updated_at,version}`, `embedding` (not returned via MCP).

**Fact** — `text`. **Entity** — optional `type`. Practical labels, not ontology.

**Reserved metadata** (typed, promoted, filterable): `project`, `created_by`, `tags`, `type`, `confidence`. Other keys free-form.

**Edges:** `RELATED_TO`, `MENTIONS`, `SUMMARIZES`, `FOLLOWS_FROM`, `CONTRADICTS`, triplet predicates, `EXTRACTED_FROM`. Policy: `RELATION_POLICY_ENFORCE` (`off`|`warn`|`enforce`), `RELATION_ALLOWED_TYPES`. Fact `auto_link` (default false) → `MENTIONS` to similar Entities when passed true.

**Indexes:** Fact + Entity vectors — auto on first search/auto_link, `AUTO_CREATE_INDEXES=true`, or `POST /admin/ensure-indexes`.

## Validation

| Field | Rule | Default |
|-------|------|---------|
| `text` | max length | 10_000 |
| `metadata` | max bytes | 100_000 |
| `ttl_days` | range | (0, 3650] |
| `owner_id` | `[A-Za-z0-9_@-]+` | |
| `relation_type` | `[A-Za-z0-9_]+` | |

Errors: `{success:false, error, code}` — `memory_validation_error`, `memory_not_found`, `memory_duplicate`, `memory_relation_policy_error`, `memory_service_error`, `memory_conflict`, `memory_embedding_error`, `connection_error`. `memory_duplicate` also returns `possible_duplicates` (each item has `diff_hint`). The node is not written. `memory_embedding_error` means search did not run: an empty result list is not used for a missing vector. `memory_conflict` is the Falkor Redis lock when two upserts hit the same `(owner_id, node_type, source.ref)`. Arcade has no Redis client, so that lock is skipped.

## Cache

LRU embeddings + TTL search (defaults in `env.example`). Search cache cleared on mutations. In-process only. Falkor locks upsert and jobs with Redis. Arcade is one process and does not. Stats in `health_check` / `/metrics`.

## `--simple` profile

Same tools/handlers; provenance is flat (`ref`, `provenance_type`, …) instead of nested `source`. `upsert_node` requires `ref`.

## Agent tools

Defaults: `owner_id` from `DEFAULT_OWNER_ID` (env, default `"default"`). Pass `owner_id` explicitly in agent rules.

`OWNER_SCOPE=client` (default) uses that argument. `OWNER_SCOPE=header` ignores it and takes `X-Owner-Id`; a missing header is `memory_validation_error` and does not use `DEFAULT_OWNER_ID`. Tool schemas do not change. Jobs are in-process and keep their own owner. See [admin.md](./admin.md).

### Writes

**`create_node`** — `text`; opt: `node_type`, `owner_id`, `metadata`, `description`, `status`, `ttl_days`, `source`, `entity_type`, `auto_link` (default false), `semantic_threshold`, `links[{to_id,relation_type,properties?}]`, `check_duplicates` (default true). The server never sets `ttl_days`. A Fact near-paraphrase at or above `CREATE_DUPLICATE_BLOCK_THRESHOLD` (0.92) is rejected (`memory_duplicate`, with `diff_hint`) before write. A similar but different fact is written with `check_duplicates=false`. Text longer than `LONG_TEXT_WARN_CHARS` (600) adds `warnings` and is still stored. `auto_link=true` adds `MENTIONS` to similar Entities (threshold `AUTO_LINKING_SEMANTIC_THRESHOLD`).
→ success `{node, possible_duplicates?, warnings?, link_errors?, link_warnings?}`

**`upsert_node`** — `text`, `source.ref`; same write fields as `create_node` except `check_duplicates` (upsert updates the node for that ref, including a revised `about`). Opt `auto_link` (default false) + `versioning`. On Falkor, Redis-locked per `(owner_id, node_type, ref)`. Arcade does not take that lock. → `{success, node, operation}`

**`create_nodes`** — `items[{text,…}]` ≤200; opt `node_type`, `owner_id`. No auto_link / duplicates.

**`ingest_knowledge`** — agent extracts; server writes. `document{ref,…}`; opt `facts[{text, ref?,…}]`, `triplets[{subject,predicate,object,metadata?}]`, `owner_id`, `auto_link=false`. Fact key: `facts[].ref` or `hash(text)` → `doc#…` (≤200 facts/triplets).

**`update_node`** — `node_id`; opt fields + `versioning` (default `VERSIONING_DEFAULT`).
**`delete_node`** — hard delete (+ FactVersion cascade).
**`mark_outdated`** — `fact_id`, opt `reason`.

**`create_relation`** / **`delete_relation`** — `from_id`, `to_id`, `relation_type` (delete: type optional).
**`create_triplet`** / **`search_triplets`** — entities merge by `name_norm`; opt `metadata` on create (reserved keys coalesce on match).
**`create_summary_fact`** — `fact_ids`, `summary_text`.

### Reads

**`get_node`** — `node_id`; opt `as_of` (unix ms, needs versioning snapshots).
**`get_node_change_history`** — `node_id`.
**`search`** — `query`; opt `limit` (cap `MAX_SEARCH_LIMIT`), `node_types`, `status`, `similarity_threshold`, `include_outdated`, `include_ttl` (default false: hide facts that have `ttl_days`; true: also still-living temporary facts), `search_type` (`pre_filter`|`post_filter`), `metadata_filter` (`project`/`created_by`/`type`/`tags`/`confidence_min`), `compact` (snippets + token budget). Rank is hybrid (`score`): cosine + identifier match + recency. `contradiction_pairs` lists hits that already have a `CONTRADICTS` edge. Always returns `suggested_next`, `do_not`, `budget`. Bumps access counters.
**`find_similar`** — `fact_id`.
**`get_context`** — `node_id`; opt `depth`, `max_nodes`, `offset`, `include_outdated`, `include_ttl`, `relation_priority`, `exclude_relation_types`. Budgeted walk (`offset=0`) fills with `CONTRADICTS`, then `FOLLOWS_FROM`, then other allowlist edges; `MENTIONS` last. Default cap 20 (hard 50). Neighbors with `ttl_days` are omitted unless `include_ttl=true`.
**`recall_context`** — shortcut search+expand (small graphs). Opt `depth`, `limit`, `max_nodes`, `include_outdated`, `include_ttl`, `include_paths`, `metadata_filter`, `compact`, `relation_priority`, `exclude_relation_types`, time-aware ranking weights. Same neighbor order and TTL filter as `get_context`. Always returns `suggested_next` / `do_not` / `budget`.
**`get_trace`** — `from_id`, `to_id`; opt `max_depth`, `directed` (default true).
**`get_brief`** — warm-up, not search and not a degree ranking: `about` if a fact with `source.ref` = `ABOUT_SOURCE_REF` (default `about`) exists, else null. Recent active facts with no TTL, by time. Open `CONTRADICTS` between those durable facts. Stale facts, stats. Facts with `ttl_days` are omitted.
**`get_stats`** / **`health_check`** — Fact/Entity counts; component flags + `healthy`.

## Admin (HTTP; not MCP by default)

See [admin.md](./admin.md): `/admin/health`, `/admin/ensure-indexes`, export/import (incl. `FactVersion` when `include_versions=true`), delete/prune owners, `/metrics`, `/internal/graph-size`.
Set `MCP_EXPOSE_ADMIN_TOOLS=true` to also expose `test_connection`, `ensure_vector_indexes`, `export_owner`, `import_owner` as MCP tools.
