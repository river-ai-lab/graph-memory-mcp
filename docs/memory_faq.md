# Long-term Memory FAQ

## Search vs. Summary?

- **“What do we know about Y?”**: Use `search(query="Y")` followed by `create_summary_fact` if you assume synthesis.
- **“Find all about Z”**: Use `search(query="Z", limit=50)` + `get_context` for raw retrieval.

## Deleting Knowledge ("Forget")

There is no single `forget_topic(X)` tool. Use a deliberate workflow:

1. **`search(query="X", owner_id=...)`** — semantic recall (Facts and Entities).
2. **`get_context(node_id=..., depth=2)`** on promising hits — expand the subgraph.
3. **Filter** by `metadata.tags`, `metadata.entities`, or your own naming conventions (metadata is not a separate search API today).
4. **`mark_outdated(fact_id=..., owner_id=..., reason="...")`** — soft-delete for **Facts** only (hidden from default search).
5. **`delete_node`** — hard removal (Facts or Entities; compliance, mistakes, test data). Entities have no soft-delete.
6. **`delete_relation`** — remove specific edges between nodes (optional `relation_type`).

**Why “only X” is hard:** embeddings overlap (e.g. “Redis” vs “cache layer”), and graphs share nodes. Tag facts at write time (`metadata.tags`, `metadata.entities`) if you expect bulk forget later. Shared team facts should stay immutable unless correcting an error.

## Fact vs. Entity

- **Fact**: declarative statement (`text`).
- **Entity**: named concept (person, service, technology).

This is a **practical UI distinction**, not a strict ontology. Agents may store the same idea as either label; use consistent `owner_id` and relations (`MENTIONS`, `RELATED_TO`) rather than debating labels.

## Metadata — why not “searchable metadata”?

Primary recall is **`text` embeddings** plus **graph traversal**. `metadata` holds tags, provenance, confidence — returned with nodes, useful for filtering in agent logic, but there is no dedicated metadata-query tool in v1. Put the searchable substance in `text`.

## Vector indexes (FalkorDB)

- Two indexes: **Fact** (`search`, `find_similar`) and **Entity** (Fact **auto_link**).
- **Automatic:** missing indexes are created on first `search`, `find_similar`, or Fact `auto_link` (idempotent).
- **Startup:** set `AUTO_CREATE_INDEXES=true` to create them when the MCP server starts.
- **Manual:** MCP tool `ensure_vector_indexes` (same logic).
- FalkorDB **maintains** index contents when nodes change; you only redefine indexes when the embedding **model dimension** changes.

## Explorer vs. MCP

- **Agents** use MCP tools (`stdio` or HTTP) — this is the production interface.
- **Explorer** (`graph-memory-explorer`) is a **human debugging GUI** over read-only MCP calls; agents do not need it.

## Fact Lifecycle & Status

- **`active`**: Default. Visible in default search.
- **`outdated`**: Soft-deleted (Facts). Hidden from default search; use `search(..., include_outdated=True)` or `status="outdated"` to include.
- **`archived`**: Set by optional background job when TTL expires (same graph, not separate storage). Hidden from default search like `outdated`.

Agent write/update rules: [memory_policies_for_LLM.md](./memory_policies_for_LLM.md).

## Metadata Schema

Recommended optional fields in `metadata` (not validated by the server):

- `type`: Category (e.g., "incident", "terminology").
- `entities`: List of key names (["Redis", "Auth"]).
- `tags`: Filters (["infra", "prod"]).
- `valid_until`: "YYYY-MM-DD" for expiry.

## Do we save everything?

**No.** Only explicit savings or final decisions.

- **Save**: "The server IP is 10.0.0.1", "User prefers concise answers".
- **Ignore**: "Hello", "Let me think", "Did that work?".

## Is memory shared?

- **Physically**: One database.
- **Logically**: Partitioned by `owner_id`.
- **Rule**: Always set `owner_id` to respect boundaries (private vs team).
