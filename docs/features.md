# MCP Graph Memory — API Contract

**Graph-based long-term memory system** for multi-agent and dialog systems via MCP (Model Context Protocol). Built on FalkorDB graph database with vector search capabilities.

This document is the **normative contract** (tool signatures, response shapes, error codes).

See also:
- `docs/background_jobs.md` (optional background jobs)
- `README.md` (install, FalkorDB, CLI including `--simple`)

## Data Model

### Common Attributes (Fact & Entity)

All nodes share these attributes:
- `id`: unique identifier (string)
- `owner_id`: multi-tenant isolation (string, default: "default")
- `metadata`: arbitrary JSON (dict)
- `created_at`: creation timestamp (int, milliseconds)
- `last_dedup_at`: last deduplication check (int, milliseconds, optional)
- `ttl_days`: relative TTL in days (float, optional) — calculates `expires_at` if not set
- `expires_at`: absolute expiration timestamp (int, milliseconds, optional) — takes precedence over `ttl_days` if both set
- `embedding`: vector representation (list[float], not returned via MCP)
- `source`: optional provenance object: `{ref, type, uri, content_hash, updated_at, version}`
- `status`: lifecycle status (string: "active" | "outdated" | "archived", default: "active")

### Fact
Primary memory unit for detailed information, definitions, reasoning, descriptions.

**Fact-specific attributes:**
- `text`: fact text (string, required)


### Entity
Named concept (person, organization, technology, etc.). **Not a strict ontology** — a practical label distinct from Fact; agents may choose either when storing durable knowledge.

**Entity-specific attributes:**
- `type`: entity type (string, optional, e.g., "PERSON", "ORGANIZATION")

### Edge
Typed relationship between nodes.

**Recommended types:**
- General: `RELATED_TO` (default when unsure)
- Reference: `MENTIONS` (one node refers to / is about another — any node pair)
- Semantic: `SUMMARIZES`, `FOLLOWS_FROM`, `CONTRADICTS` (use only when the type matters)
- Triplets: predicate from `create_triplet` (e.g. `RUNS_ON`, `USES`)
- System: `EXTRACTED_FROM` (triplet ↔ fact), `SIMILAR_TO` (reserved for jobs/manual use — **not** used by Fact auto_link)

**Relation policy (server config):**

| Variable | Default | Description |
|----------|---------|-------------|
| `RELATION_POLICY_ENFORCE` | `warn` | `off` \| `warn` \| `enforce` |
| `RELATION_ALLOWED_TYPES` | see `config.py` | Comma-separated allowlist checked on `create_relation`, `create_node.links`, `create_triplet` |

- **`off`**: format validation only (alphanumeric + `_`)
- **`warn`**: disallowed types still create the edge; response includes `warning`
- **`enforce`**: disallowed types return `memory_relation_policy_error`

`create_node` with `links` returns `link_errors` / `link_warnings` when inline relations fail policy (node is still created).

**Auto-linking:** `create_node(..., auto_link=true)` on Facts creates `MENTIONS` edges to semantically similar **Entity** nodes (Entity vector index; threshold `AUTO_LINKING_SEMANTIC_THRESHOLD`, default 0.75). Does not link Fact→Fact. Use `create_relation` or `links` for other pairs.

**Vector indexes:** Created automatically when missing on first `search`, `find_similar`, or auto_link; optional `AUTO_CREATE_INDEXES=true` at startup; or call `ensure_vector_indexes`.

Agent guidance: see [memory_policies_for_LLM.md](../graph_memory_mcp/resources/memory_policies_for_LLM.md). Operational FAQ: [memory_faq.md](./memory_faq.md).

**Properties:**
- `metadata`: edge metadata (dict, optional)

### Alias
Alternative name for Entity (internal, not exposed via MCP).

---

## Input Validation

All inputs are validated to ensure data quality and security. Validation limits are configurable via environment variables or `config.py`.

### Validation Rules

| Field | Rule | Default Limit | Error Code |
|-------|------|---------------|------------|
| `text` | Maximum length | 10,000 characters | `memory_validation_error` |
| `metadata` | Maximum size | 100KB (100,000 bytes) | `memory_validation_error` |
| `ttl_days` | Range | 0 < ttl_days ≤ 3650 | `memory_validation_error` |
| `owner_id` | Format | Alphanumeric + `-_@` | `memory_validation_error` |
| `relation_type` | Format | Alphanumeric + `_` | `memory_validation_error` |
| `source.version` | Range | Integer ≥ 1 | `memory_validation_error` |

### Configuration

Set validation limits in `.env` or `config.py`:

```bash
# .env
MAX_TEXT_LENGTH=10000
MAX_METADATA_SIZE=100000
MIN_TTL_DAYS=0.0
MAX_TTL_DAYS=3650.0
```

### Error Responses

When validation fails, the response includes:

```json
{
  "success": false,
  "error": "Text too long (max 10000 chars)",
  "code": "memory_validation_error"
}
```

---

## Caching

Query caching improves performance by caching expensive operations.

### Cache Types

| Cache | Type | Default Size | Default TTL | Purpose |
|-------|------|--------------|-------------|---------|
| Embeddings | LRU | 1000 items | N/A | Cache embedding API calls |
| Search | TTL | 100 items | 60s | Cache search results |

### Configuration

Set cache limits in `.env` or `config.py`:

```bash
# .env
CACHE_EMBEDDINGS_ENABLED=true
CACHE_EMBEDDINGS_MAXSIZE=1000
CACHE_SEARCH_ENABLED=true
CACHE_SEARCH_MAXSIZE=100
CACHE_SEARCH_TTL=60
```

### Cache Invalidation

- **Automatic**: Search cache is invalidated on all mutations (`create_node`, `update_node`, `delete_node`, `create_relation`, `create_triplet`)
- **Manual**: Not currently supported

### Monitoring

Cache statistics are available in `health_check`:

```json
{
  "cache": {
    "embeddings": {
      "enabled": true,
      "size": 42,
      "maxsize": 1000
    },
    "search": {
      "enabled": true,
      "size": 5,
      "maxsize": 100,
      "ttl": 60
    }
  }
}
```

---

## Simple server profile

`GraphMemorySimpleMCP` (`graph_memory_mcp.server_simple`) and `graph-memory-mcp --simple` expose the **same tool names and handler behavior** as the default server, with these MCP differences:

| Area | Default server | Simple profile |
|------|----------------|----------------|
| Provenance | `source: dict` on `create_node` / `update_node` / `upsert_node` | Flat fields: `ref`, `provenance_type`, `uri`, `content_hash`, `updated_at`, `version` (mapped to the same `source` object internally) |
| `upsert_node` | `source.ref` required (via `source` dict) | Same behavior; **`ref` required** as a flat field |

All other tools (search, triplets, graph traversal, admin, jobs via config, etc.) match the default server.

---

## Tools

#### create_node
**Required:**
- `text: str`

**Optional:**
- `node_type: str = "Fact"` — "Fact" or "Entity"
- `owner_id: str = "default"`
- `metadata: dict | None = None`
- `source: dict | None = None` — optional provenance object with keys `ref`, `type`, `uri`, `content_hash`, `updated_at`, `version`
- `status: str | None = None` — "active" | "outdated" | "archived" (default: "active")
- `ttl_days: float | None = None`
- `entity_type: str | None = None` (Entities only)
- `auto_link: bool = True` (Facts only)
- `semantic_threshold: float | None = None` (Facts only)
- `links: list[dict] | None = None` — inline edges after create. Each item:
  - `to_id` or `node_id` (target node id)
  - `relation_type` (or `type`)
  - optional `properties` or `metadata` (edge properties)

**Response:** `{"success": true, "node": {...}}`
May also include:
- `possible_duplicates: [{node_id, text, similarity}]` — top similar active same-owner nodes above `DUPLICATE_SIMILARITY_THRESHOLD`; a server-side backstop for the "search before create" policy
- `link_errors` (policy/validation failures per link) and `link_warnings` (policy `warn` mode). The node is still created when inline links fail.

**Errors:** `memory_validation_error`, `memory_service_error`

> **Node IDs**: all tools accept and return a stable opaque `node_id` (`uid` property, UUID hex). It never changes and is never reused after deletion. Legacy nodes get a `uid` backfilled automatically at server startup.

#### ensure_vector_indexes
**Required:** (none)

**Optional:** (none)

**Response:** `{"success": true, "indexes": {"Fact": bool, "Entity": bool}, "dimension": int}`
**Errors:** `memory_service_error`

#### upsert_node
**Required:**
- `text: str`
- `source: dict` — must include `source.ref`

**Optional:**
- `node_type: str = "Fact"` — "Fact" or "Entity"
- `owner_id: str = "default"`
- `metadata: dict | None = None`
- `description: str | None = None`
- `status: str | None = None` — "active" | "outdated" | "archived"
- `ttl_days: float | None = None`
- `entity_type: str | None = None` (Entities only)
- `versioning: bool = False` — when true, stores a snapshot before update and auto-increments `source.version` if omitted
- `auto_link: bool = True` (Facts only)
- `semantic_threshold: float | None = None` (Facts only)
- `links: list[dict] | None = None` — inline edges after create **or update** (same shape as `create_node.links`)

**Response:** `{"success": true, "node": {...}, "operation": "created" | "updated"}`
May also include `link_errors` / `link_warnings` when inline `links` fail policy (node is still created or updated).
**Errors:** `memory_validation_error`, `memory_service_error`

#### ingest_knowledge
Persist agent-extracted knowledge from one document/conversation in a single call. The **agent extracts** (facts, triplets); the server writes reliably and idempotently.

**Required:**
- `document: dict` — `{ref (required), title?, uri?, type?}`; a source Entity node is upserted by `ref`

**Optional:**
- `facts: list[dict]` — `{text (required), metadata?, ttl_days?, description?}`; each fact is upserted with `source.ref = "{document.ref}#{i}"` and linked `EXTRACTED_FROM` → document
- `triplets: list[dict]` — `{subject, predicate, object}`; entities merge by normalized name
- `owner_id: str = "default"`
- `auto_link: bool = false`

Re-ingesting the same `document.ref` **updates facts in place** (same node ids) instead of duplicating. Limits: ≤200 facts, ≤200 triplets per call.

**Response:** `{"success": true, "document_id", "document_operation", "facts": [{node_id, ref, operation, possible_duplicates?}], "triplets": [...], "fact_count", "triplet_count", "link_errors"?}`
**Errors:** `memory_validation_error`, `memory_service_error`

#### create_nodes
Bulk ingest: up to 200 nodes of one type in a single query with batched embeddings. No `auto_link` / `links` / `possible_duplicates` — link explicitly afterwards.

**Required:**
- `items: list[dict]` — each `{text, description?, metadata?, status?, ttl_days?}`

**Optional:**
- `node_type: str = "Fact"`
- `owner_id: str = "default"`

**Response:** `{"success": true, "nodes": [{node_id, text}], "count": int}`
**Errors:** `memory_validation_error`, `memory_service_error`

#### export_owner / import_owner
Backup / migration of an owner scope. Export returns JSON-serializable `nodes` (`{label, properties}` incl. embeddings by default) and `relations` (`{from_id, relation_type, to_id, properties}`) — write list items as lines for JSONL. Import merges nodes by `uid` (idempotent); embeddings come from the payload or are recomputed when missing / `regenerate_embeddings=true`.

**export_owner:** `owner_id`, `include_embeddings: bool = true`, `include_versions: bool = false`; pagination for large owners: `limit`, `offset`, `section: "nodes" | "relations"` — response then carries `has_more` / `next_offset` (page nodes first, then relations)
**import_owner:** `owner_id` (required), `nodes` (required), `relations?`, `regenerate_embeddings: bool = false`; nodes/relations are merged in UNWIND batches of 200 (grouped by label / relation type)

**Errors:** `memory_service_error`

#### get_node
**Required:**
- `node_id: str`

**Optional:**
- `owner_id: str = "default"`
- `as_of: int | None = None` — unix ms; returns the node state at that time using `FactVersion` snapshots (reliable only for updates made with `versioning=true`). Response then includes `as_of` and, when a snapshot applied, `node.snapshot_timestamp`.

**Response:** `{"success": true, "node": {...}}`
**Errors:** `memory_not_found` (also when the node did not exist at `as_of`), `memory_service_error`

#### update_node
**Required:**
- `node_id: str`

**Optional:**
- `owner_id: str = "default"`
- `text: str | None = None`
- `metadata: dict | None = None`
- `source: dict | None = None` — provenance object with keys `ref`, `type`, `uri`, `content_hash`, `updated_at`, `version`
- `status: str | None = None` — "active" | "outdated" | "archived"
- `ttl_days: float | None = None`
- `entity_type: str | None = None` (Entities only)
- `versioning: bool | None = None` — stores a snapshot before update and auto-increments `source.version`; when omitted, falls back to config `VERSIONING_DEFAULT` (default false)

**Response:** `{"success": true, "node": {...}}`
**Errors:** `memory_validation_error`, `memory_not_found`, `memory_service_error`

#### delete_node
**Required:**
- `node_id: str`

**Optional:**
- `owner_id: str = "default"`

**Response:** `{"success": true}`
**Errors:** `memory_not_found`, `memory_service_error`

#### get_node_change_history
**Required:**
- `node_id: str`

**Optional:**
- `owner_id: str = "default"`

**Response:** `{"success": true, "versions": [...], "count": int}`
**Errors:** `memory_not_found`, `memory_service_error`


#### search

Semantic similarity over Facts and Entities. See [memory_policies_for_LLM.md](../graph_memory_mcp/resources/memory_policies_for_LLM.md) § “How to use search”. Two modes via `search_type`: **`pre_filter`** (filter by owner first — recommended for large / multi-tenant graphs) and **`post_filter`** (global ANN then filter — fine for small graphs). Server default: config `SEARCH_TYPE` (env), overridable per call. For `post_filter`, ANN candidate pool size: `POST_FILTER_ANN_K_MIN` / `POST_FILTER_ANN_K_MAX` (env).

**Required:**
- `query: str`

**Optional:**
- `owner_id: str = "default"`
- `limit: int | None = None` (default from config: 10)
- `node_types: list[str] | None = None` — ["Fact"], ["Entity"], or ["Fact", "Entity"]
- `status: str | None = None` — "active" | "outdated" | "archived"
- `similarity_threshold: float | None = None`
- `include_outdated: bool = False`
- `search_type: str | None = None` — `pre_filter` | `post_filter`; falls back to config `SEARCH_TYPE` when omitted
- `metadata_filter: dict | None = None` — native (in-DB) filter over promoted metadata keys. Supported: `project` / `created_by` / `type` (equality), `tags` (str or list — every tag must be present in `metadata.tags`), `confidence_min` (float, `metadata.confidence >= x`). `limit` is capped by `MAX_SEARCH_LIMIT` (default 100).

**Response:** `{"success": true, "results": [...], "facts": [...], "entities": [...]}`
**Errors:** `memory_validation_error` (unknown filter keys), `memory_service_error`

> **Reserved metadata keys** — typed, promoted to flat node properties at write time, filterable, indexed (`project` has a range index): `project` (soft partition inside an owner), `created_by` (attribution, `"user:<id>"` / `"agent:<id>"`), `tags`, `type`, `confidence`. Wrong types are rejected with `memory_validation_error`; all other metadata keys are free-form. Filters run inside the DB before vector scoring in `pre_filter` — no client-side filtering. Successful `search` / `recall_context` also bump `access_count` / `last_accessed_at` on returned nodes (see `get_brief.stale_facts`).
>
> Scoping model: `owner_id` = hard isolation (own graph) → `metadata.project` = filter inside owner → `metadata.created_by` = attribution. See [memory_policies_for_LLM.md](../graph_memory_mcp/resources/memory_policies_for_LLM.md) § Scoping.

#### find_similar
**Required:**
- `fact_id: str`

**Optional:**
- `owner_id: str = "default"`
- `similarity_threshold: float | None = None` (default from config)
- `limit: int = 5`

**Response:** `{"success": true, "similar_facts": [...]}`
**Errors:** `memory_service_error`

#### mark_outdated
**Required:**
- `fact_id: str`

**Optional:**
- `owner_id: str = "default"`
- `reason: str | None = None`

**Response:** `{"success": true, "node": {...}}`
**Errors:** `memory_not_found`, `memory_service_error`

#### create_triplet
**Required:**
- `subject: str`
- `predicate: str`
- `object_value: str`

**Optional:**
- `owner_id: str = "default"`
- `metadata: dict | None = None`
- `fact_id: str | None = None`

**Response:** `{"success": true, "triplet": {...}}`
**Errors:** `memory_validation_error`, `memory_relation_policy_error`, `memory_service_error`

#### search_triplets
**Required:** (none)

**Optional:**
- `subject: str | None = None`
- `predicate: str | None = None`
- `object_value: str | None = None`
- `owner_id: str = "default"`
- `limit: int = 10`

**Response:** `{"success": true, "triplets": [...]}`
**Errors:** `memory_service_error`

#### create_relation
**Required:**
- `from_id: str`
- `to_id: str`
- `relation_type: str`

**Optional:**
- `owner_id: str = "default"`
- `properties: dict | None = None`

**Response:** `{"success": true, "relation_type": str}` — may include `warning` when `RELATION_POLICY_ENFORCE=warn` and type is outside allowlist.

**Errors:** `memory_validation_error`, `memory_relation_policy_error` (enforce mode), `memory_service_error`

#### delete_relation
**Required:**
- `from_id: str`
- `to_id: str`

**Optional:**
- `owner_id: str = "default"`
- `relation_type: str | None = None` (if specified, only removes relations of this type)

**Response:** `{"success": true}`
**Errors:** `memory_service_error`

#### get_context
**Required:**
- `node_id: str`

**Optional:**
- `owner_id: str = "default"`
- `depth: int = 1`
- `max_nodes: int = 20` (default from config: `subgraph_default_max_nodes`) — also page size when paginating
- `offset: int = 0` — when `> 0`, skip nodes (stable `ORDER BY id`) and return `has_more`

**Response:** `{"success": true, "nodes": [...], "edges": [...], "depth": int, "max_nodes": int}`

When `offset > 0`, the response also includes:
- `offset: int`
- `has_more: bool` — true when the page is full (`len(nodes) >= max_nodes`)

**Errors:** `memory_service_error`

#### recall_context

**Optional shortcut** — same semantics as `search` → multi-seed expand → trim. Primary workflow remains `search` → `get_context` → `get_trace` (see `memory_policies_for_LLM.md`). Prefer this tool on small/sparse `owner_id` graphs only.

**Required:**
- `query: str`

**Optional:**
- `owner_id: str = "default"`
- `depth: int = 2` (config: `RECALL_CONTEXT_DEFAULT_DEPTH`, capped by `SUBGRAPH_MAX_DEPTH`)
- `limit: int = 5` — semantic seed count (config: `RECALL_CONTEXT_SEED_LIMIT`)
- `max_nodes: int = 20` — cap on expanded subgraph nodes
- `similarity_threshold: float | None = None`
- `include_outdated: bool = false`
- `search_type: str | None = None` — `pre_filter` | `post_filter` (server default when omitted)
- `include_paths: bool = false` — undirected shortest path between top two seeds when available
- `metadata_filter: dict | None = None` — same semantics as `search` (applies to seed selection)

**Response:**
```json
{
  "success": true,
  "query": "...",
  "seeds": [...],
  "nodes": [{"node_id", "node_type", "text", "score", "min_hop"}],
  "edges": [...],
  "paths": [{"from_id", "to_id", "nodes", "relations"}],
  "depth": 2,
  "max_nodes": 20,
  "seed_limit": 5
}
```

Nodes are ranked by `score = seed_similarity × RECALL_CONTEXT_HOP_DECAY^min_hop` (default decay `0.7`), then multiplied by time-aware factors: recency `(1-w) + w·0.5^(age_days/half_life)` (`RECALL_RECENCY_WEIGHT`=0.2, `RECALL_RECENCY_HALF_LIFE_DAYS`=30) and usage `(1-w) + w·log-scaled(access_count)` (`RECALL_USAGE_WEIGHT`=0.1). Set weights to `0` to disable.

**Errors:** `memory_validation_error`, `memory_service_error`

#### get_trace
**Required:**
- `from_id: str`
- `to_id: str`

**Optional:**
- `owner_id: str = "default"`
- `max_depth: int = 5`
- `directed: bool = true` — set `false` for an undirected shortest path (same semantics as `get_context` / `recall_context` expansion)

**Response:** `{"success": true, "nodes": [...], "relations": [...], "message"?: str}`

By default uses a **directed** shortest path `(from)-[*]->(to)` — unlike `get_context`, which walks **undirected** hops. No directed path does not mean nodes are unrelated; retry with `directed=false`.

If no path is found, `nodes` and `relations` are returned as empty arrays.
**Errors:** `memory_service_error`

#### create_summary_fact
**Required:**
- `fact_ids: list[str]`
- `summary_text: str`

**Optional:**
- `owner_id: str = "default"`
- `metadata: dict | None = None`

**Response:** `{"success": true, "summary": {...}}`
**Errors:** `memory_validation_error`, `memory_service_error`

#### test_connection
**Required:** (none)

**Optional:** (none)

**Response:** `{"success": true, "ready": bool}`
**Errors:** `memory_service_error`

#### get_stats
**Required:** (none)

**Optional:**
- `owner_id: str = "default"`

**Response:** `{"success": true, "stats": {...}}`
**Errors:** `memory_service_error`

#### health_check
**Required:** (none)

**Optional:** (none)

**Response:** `{"success": true, "falkordb": bool, "embeddings": bool, "vector_index": bool, "healthy": bool, "cache": {...}}`
Per-component flags report each component individually; `healthy` is the aggregate.
**Errors:** (none)

#### get_brief
Session warm-up in one call.

**Required:** (none)

**Optional:**
- `owner_id: str = "default"`
- `limit: int = 10` — top facts count (max 50)

**Response:** `{"success": true, "top_facts": [{node_id, text, degree, created_at}], "contradictions": [{from_id, from_text, to_id, to_text}], "stale_facts": [{node_id, text, last_accessed_at, access_count}], "stats": {...}}`
Top facts are active facts ranked by connectivity (relation count), then recency. `contradictions` lists `CONTRADICTS` pairs within the owner scope. `stale_facts` are active facts not recalled for `STALE_FACTS_DAYS` (default 30) — candidates for archive/review. Recall usage is tracked automatically: `search` and `recall_context` bump `access_count` / `last_accessed_at` on returned nodes.
**Errors:** `memory_service_error`

#### /metrics (HTTP, not an MCP tool)
Prometheus endpoint on the same HTTP server (`GET /metrics`): handler latency histograms (`graph_memory_handler_seconds`), invocation counters by success, cache hit/miss counters (`graph_memory_cache_ops_total`), and node counts by label (`graph_memory_nodes`).

#### /admin/* (HTTP, operator endpoints)
Admin operations are separated from the agent-facing MCP surface and live on plain HTTP routes (curl-friendly). Optional bearer auth via `ADMIN_TOKEN` (open when unset — trusted env).

| Route | Method | Purpose |
|-------|--------|---------|
| `/admin/health` | GET | component health (FalkorDB, embeddings, vector index, cache) |
| `/admin/ensure-indexes` | POST | create missing vector/uid indexes, report status |
| `/admin/export/{owner_id}` | GET | export owner (`?include_embeddings=`, `?include_versions=`) |
| `/admin/import` | POST | import payload `{owner_id, nodes, relations?, regenerate_embeddings?}` |

`test_connection`, `ensure_vector_indexes`, `export_owner`, `import_owner` are **not** MCP tools by default; set `MCP_EXPOSE_ADMIN_TOOLS=true` to also expose them via MCP (e.g. for an admin agent that prefers MCP).

### Response Format

**Success:**
```json
{"success": true, ...}
```

**Error:**
```json
{"success": false, "error": "error message", "code": "error_code"}
```

### Error Codes

- `memory_validation_error`: invalid input parameters
- `memory_not_found`: node not found
- `memory_relation_policy_error`: relation type blocked (`RELATION_POLICY_ENFORCE=enforce`) or inline `links` / triplet predicate rejected
- `memory_service_error`: general service error
- `connection_error`: database connection failure
- `falkordb_error`: FalkorDB operation error
