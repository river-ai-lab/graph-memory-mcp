# API contract

Normative tool signatures. Jobs: [background_jobs.md](./background_jobs.md). Agents: [memory_policies_for_LLM.md](./memory_policies_for_LLM.md). Admin: [admin.md](./admin.md).

**Storage:** one FalkorDB graph per `owner_id` (`{FALKORDB_GRAPH}_{owner_id}`). **IDs:** tools use stable `node_id` (= `uid`, UUID hex); legacy nodes backfilled at startup.

## Data model

**Common:** `node_id`, `owner_id`, `metadata`, `created_at`, `status` (`active`|`outdated`|`archived`), optional `ttl_days`/`expires_at`, `source` `{ref,type,uri,content_hash,updated_at,version}`, `embedding` (not returned via MCP).

**Fact** — `text`. **Entity** — optional `type`. Practical labels, not ontology.

**Reserved metadata** (typed, promoted, filterable): `project`, `created_by`, `tags`, `type`, `confidence`. Other keys free-form.

**Edges:** `RELATED_TO`, `MENTIONS`, `SUMMARIZES`, `FOLLOWS_FROM`, `CONTRADICTS`, triplet predicates, `EXTRACTED_FROM`. Policy: `RELATION_POLICY_ENFORCE` (`off`|`warn`|`enforce`), `RELATION_ALLOWED_TYPES`. Fact `auto_link` → `MENTIONS` to similar Entities.

**Indexes:** Fact + Entity vectors — auto on first search/auto_link, `AUTO_CREATE_INDEXES=true`, or `POST /admin/ensure-indexes`.

## Validation

| Field | Rule | Default |
|-------|------|---------|
| `text` | max length | 10_000 |
| `metadata` | max bytes | 100_000 |
| `ttl_days` | range | (0, 3650] |
| `owner_id` | `[A-Za-z0-9_@-]+` | |
| `relation_type` | `[A-Za-z0-9_]+` | |

Errors: `{success:false, error, code}` — `memory_validation_error`, `memory_not_found`, `memory_relation_policy_error`, `memory_service_error`, `connection_error`, `falkordb_error`.

## Cache

LRU embeddings + TTL search (defaults in `env.example`). Search cache cleared on mutations. In-process only (multi-instance → see roadmap). Stats in `health_check` / `/metrics`.

## `--simple` profile

Same tools/handlers; provenance is flat (`ref`, `provenance_type`, …) instead of nested `source`. `upsert_node` requires `ref`.

## Agent tools

Defaults: `owner_id` from `DEFAULT_OWNER_ID` (env, default `"default"`). Pass `owner_id` explicitly in agent rules.

### Writes

**`create_node`** — `text`; opt: `node_type`, `owner_id`, `metadata`, `description`, `status`, `ttl_days`, `source`, `entity_type`, `auto_link`, `semantic_threshold`, `links[{to_id,relation_type,properties?}]`.
→ `{success, node, possible_duplicates?, link_errors?, link_warnings?}`

**`upsert_node`** — `text`, `source.ref`; same opts + `versioning`. Redis-locked per `(owner_id,node_type,ref)`. → `{success, node, operation}`

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
**`search`** — `query`; opt `limit` (cap `MAX_SEARCH_LIMIT`), `node_types`, `status`, `similarity_threshold`, `include_outdated`, `search_type` (`pre_filter`|`post_filter`), `metadata_filter` (`project`/`created_by`/`type`/`tags`/`confidence_min`). Bumps access counters.
**`find_similar`** — `fact_id`.
**`get_context`** — `node_id`; opt `depth`, `max_nodes`, `offset`, `include_outdated` (default false — skip outdated/expired neighbors). Iterative BFS when `offset=0`.
**`recall_context`** — shortcut search+expand (small graphs). Opt `depth`, `limit`, `max_nodes`, `include_outdated`, `include_paths`, `metadata_filter`, time-aware ranking weights.
**`get_trace`** — `from_id`, `to_id`; opt `max_depth`, `directed` (default true).
**`get_brief`** — warm-up: top facts, `CONTRADICTS`, stale facts, stats.
**`get_stats`** / **`health_check`** — Fact/Entity counts; component flags + `healthy`.

## Admin (HTTP; not MCP by default)

See [admin.md](./admin.md): `/admin/health`, `/admin/ensure-indexes`, export/import (incl. `FactVersion` when `include_versions=true`), delete/prune owners, `/metrics`.
Set `MCP_EXPOSE_ADMIN_TOOLS=true` to also expose `test_connection`, `ensure_vector_indexes`, `export_owner`, `import_owner` as MCP tools.
