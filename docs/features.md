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
Named entity (person, organization, technology, etc.).

**Entity-specific attributes:**
- `type`: entity type (string, optional, e.g., "PERSON", "ORGANIZATION")

### Edge
Typed relationship between nodes.

**Types:**
- Fact-Fact: `SIMILAR_TO`, `RELATED_TO`, `SUMMARIZES`, `FOLLOWS_FROM`, `CONTRADICTS`
- Fact-Entity: `MENTIONS_ENTITY`, `DESCRIBES`, `REFERENCES`
- Entity-Entity: predicate from triplets (subject-predicate-object)

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
| Provenance | `source: dict` on `create_node` / `update_node` | Flat fields: `ref`, `provenance_type`, `uri`, `content_hash`, `updated_at`, `version` (mapped to the same `source` object internally) |
| `upsert_node` | Available (`source.ref` required) | **Not registered** — use the default server for sync-by-ref |

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
- `links: list[dict] | None = None` — list of `{"node_id": str, "node_type": str, "relation_type": str}`

**Response:** `{"success": true, "node": {...}}`
**Errors:** `memory_validation_error`, `memory_service_error`

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
- `links: list[dict] | None = None`

**Response:** `{"success": true, "node": {...}, "operation": "created" | "updated"}`
**Errors:** `memory_validation_error`, `memory_service_error`

#### get_node
**Required:**
- `node_id: str`

**Optional:**
- `owner_id: str = "default"`

**Response:** `{"success": true, "node": {...}}`
**Errors:** `memory_not_found`, `memory_service_error`

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
- `versioning: bool = False` — stores a snapshot before update and auto-increments `source.version` if omitted

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
**Required:**
- `query: str`

**Optional:**
- `owner_id: str = "default"`
- `limit: int | None = None` (default from config: 10)
- `node_types: list[str] | None = None` — ["Fact"], ["Entity"], or ["Fact", "Entity"]
- `status: str | None = None` — "active" | "outdated" | "archived"
- `similarity_threshold: float | None = None`
- `include_outdated: bool = False`

**Response:** `{"success": true, "results": [...], "facts": [...], "entities": [...]}`
**Errors:** `memory_service_error`

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
**Errors:** `memory_validation_error`, `memory_service_error`

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

**Response:** `{"success": true, "relation_type": str}`
**Errors:** `memory_validation_error`, `memory_service_error`

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
- `max_nodes: int = 20` (default from config: `subgraph_default_max_nodes`)

**Response:** `{"success": true, "nodes": [...], "edges": [...], "depth": int, "max_nodes": int}`
**Errors:** `memory_service_error`

#### get_trace
**Required:**
- `from_id: str`
- `to_id: str`

**Optional:**
- `owner_id: str = "default"`
- `max_depth: int = 5`

**Response:** `{"success": true, "nodes": [...], "relations": [...], "message"?: str}`
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

**Response:** `{"success": true, "falkordb": bool, "embeddings": bool, "vector_index": bool, "cache": {...}}`
**Errors:** (none)

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
- `memory_service_error`: general service error
- `connection_error`: database connection failure
- `falkordb_error`: FalkorDB operation error
