# Agent Memory Directives

**Role**: You are an autonomous agent or sub-agent with access to the **Graph Memory MCP server**.
**Purpose**: This memory is a **long-term knowledge base**, not a chat log. It persists across sessions and may be shared with other agents through agreed `owner_id` scopes.

## Core Principles

1. **Store durable knowledge**: Save stable facts, decisions, constraints, and relationships that will matter later.
2. **Keep signal high**: Do not write noise, scratchpad thoughts, raw conversation, or transient execution state.
3. **Respect isolation**: Memory is logically partitioned by `owner_id`. Always write into the correct scope.
4. **Prefer explicit facts**: Store clear declarative facts, not vague summaries when a precise fact can be stored.
5. **Recall before write**: At task start and before `create_node`, recall with the correct `owner_id` — usually `search`, then `get_context` / `get_trace` as needed (see below).

## 1. What to Store

Store information with strategic value for future work or agent coordination.

- **World State**: persistent environmental facts, system topology, service locations, repo conventions.
- **User Alignment**: preferences, constraints, priorities, and standing decisions.
- **Tool/Workflow Knowledge**: proven procedures that should be reused later.
- **Entity Relations**: dependencies, ownership, compatibility, and other structural links.
- **Summarized Outcomes**: validated conclusions from research or implementation work.

## 2. What Not to Store

- **Chat Logs**: never store raw dialogue such as "user asked..." or "I replied...".
- **Ephemeral State**: never store temporary execution notes such as "currently debugging..." or "processing file X".
- **Secrets or PII**: never store passwords, API keys, tokens, secrets, or personal data.
- **Intermediate Reasoning**: do not store chain-of-thought, scratchpad notes, or speculative reasoning.
- **Low-Confidence Guesses**: do not store uncertain claims as facts unless explicitly labeled in metadata.

## 3. Operational Rules for This Server

### Always Set `owner_id`

Always pass `owner_id` explicitly on reads and writes.

- Do not rely on the server default.
- If you omit `owner_id`, writes go to `default`, which may put data into the wrong memory scope.
- When updating or replacing a fact, use the same `owner_id` as the original node.

### Valid `owner_id` Format

This server accepts only alphanumeric characters plus `_`, `-`, and `@`.

Recommended conventions:

- **Private agent memory**: `agent_<agent_id>`
- **Shared team memory**: `team_<team_id>`
- **User-specific memory**: `user_<user_id>`

Examples of valid values:

- `agent_worker_7`
- `team_platform`
- `user_42`
- `team-alpha`
- `agent@planner`

Avoid values with `:` or spaces, such as `agent:123` or `team:core`.

### How to use `search`

Semantic search finds Facts and Entities **similar in meaning** to your query text, scoped by **`owner_id`**.

**Always pass:**

| Parameter | Rule |
|-----------|------|
| `query` | Natural-language question or keywords (e.g. `"Redis hosting"`, `"user prefers dark mode"`) |
| `owner_id` | Same scope you use for `create_node` / `get_node` (required — see above) |

**Optional — `search_type` (you can omit it):**

The server has a default (`SEARCH_TYPE` in config, typically `pre_filter`). **Do not pass `search_type` unless your operator tells you to override the default** or you need a one-off different mode. When omitted, the server default applies automatically.

| Value | How it works | When to override |
|-------|----------------|------------------|
| **`pre_filter`** | Filter by `owner_id` (and status/TTL) **first**, then rank by vector similarity inside that set. | Large graph or many `owner_id`s — complete tenant results (default on most deployments). |
| **`post_filter`** | **Global** ANN over the whole graph, then keep rows matching `owner_id` / status. | Small graph, few tenants — faster ANN; may miss hits as the graph grows. |

**Example (usual — only required params; `search_type` omitted):**

```json
{
  "query": "where is production Redis hosted",
  "owner_id": "team_platform"
}
```

**Example (only if you must override the server default):**

```json
{
  "query": "where is production Redis hosted",
  "owner_id": "team_platform",
  "search_type": "post_filter"
}
```

**Other optional parameters:**

| Parameter | When |
|-----------|------|
| `search_type` | Override server default (`pre_filter` \| `post_filter`); **optional** — omit unless instructed |
| `include_outdated: true` | Look for facts marked obsolete (e.g. after `mark_outdated`) |
| `node_types: ["Fact"]` or `["Entity"]` | Only one kind of node |
| `limit` | More or fewer hits than default |
| `similarity_threshold` | Results too noisy or too sparse |
| `status: "outdated"` | Outdated nodes only |

### Recall workflow (primary)

**Default:** compose explicit steps — predictable, paginated, and safe on larger or denser subgraphs.

```text
search(query)                    → semantic hits (node_id + similarity)
get_context(node_id, depth=...)  → neighbors + edges around one anchor
get_trace(from_id, to_id)        → shortest path when you know two node IDs
```

| Situation | Steps |
|-----------|--------|
| "What do we know about X?" | `search(query="X")` → `get_context` on the best `node_id`(s) |
| "Find everything about Z" | `search(query="Z", limit=50)` → `get_context` on top hits |
| Subgraph around one known node | `get_context(node_id=..., depth=..., offset=...)` only |
| Flat list, no graph hop | `search(query=...)` only |
| "How are X and Y related?" | `search` for X and Y (or one combined query) → `get_trace(from_id=..., to_id=...)` between chosen IDs |

**`get_context`** expands **one** anchor (undirected hops: neighbors in either direction). It returns `nodes` and `edges` in a radius; it does **not** compute a path between two arbitrary nodes.

**`get_trace`** finds a **directed** shortest path `(from)-[*]->(to)` — edge direction matters. A pair visible in `get_context` may still return no path in `get_trace` if links only go the other way. Default `get_context` depth is **1** (config `SUBGRAPH_DEFAULT_DEPTH`); increase `depth` when one hop is not enough.

**`get_context` pagination:** pass `offset` with `max_nodes` as page size when a hub has many neighbors (`has_more` in the response). Stable `ORDER BY id` applies only when `offset > 0`; the first page (`offset=0`) is not sorted by node id.

**Example — open recall:**

```json
{ "query": "FalkorDB vector index setup", "owner_id": "riverlab" }
```

Then:

```json
{ "node_id": "<best_hit_id>", "owner_id": "riverlab", "depth": 2, "max_nodes": 20 }
```

**Example — path between two facts:**

```json
{ "from_id": "<id_for_X>", "to_id": "<id_for_Y>", "owner_id": "riverlab", "max_depth": 5 }
```

### `recall_context` (optional shortcut)

**Hybrid recall** in one MCP call: `search` → multi-seed BFS → ranked `nodes` → optional path between the **top two seeds only**.

Use when the graph is **small or moderate** for your `owner_id` and you want fewer round-trips. **Do not treat it as the only recall API.**

| Prefer `search` + `get_context` + `get_trace` when | `recall_context` is OK when |
|------------------------------------------------------|-----------------------------|
| Dense hubs (many edges per node) | Lab-scale memory, sparse links |
| You need pagination (`offset`) | Quick session warm-up |
| You need a path between **specific** node IDs you chose | Approximate context from a query text is enough |
| Latency or cost matters | One call is worth the extra DB work |

**Cost / stability:** one call runs vector search, variable-length graph expansion from up to 5 seeds, edge load, and optionally `get_trace`. Expansion is capped (`max_nodes` ≤ 50, `depth` ≤ 3) but can still be heavy if many nodes sit within `depth` hops of multiple seeds. Prefer **`depth=1`**, **`max_nodes=10`**, **`include_paths=false`** when unsure.

| Situation | Tool |
|-----------|------|
| Shortcut for "what do we know about X?" | `recall_context(query="X", depth=1, include_paths=false)` |
| Shortcut hint for X↔Y (not exact IDs) | `recall_context(query="X Y", include_paths=true)` — check `paths`; confirm with `get_trace` if it matters |
| Exact path between known IDs | **`get_trace`** (not `recall_context`) |

**Parameters** (same `query` / `owner_id` as `search`; optional `depth`, `limit`, `max_nodes`, `similarity_threshold`, `include_outdated`, `search_type`, `include_paths`).

**Response:** `seeds` (search hits), ranked `nodes` (`score`, `min_hop`), `edges`, optional `paths` (top-2 seeds only).

**Not for codebase maps:** static repo structure (AST, call graphs) belongs in tools like [Graphify](https://graphify.net/). Graph Memory holds **living facts** agents write.

### Search Before Create

Before writing a new fact:

1. **`search(query=..., owner_id=...)`** — then **`get_context`** on promising hits if you need neighborhood context.
2. Or **`recall_context`** only as a shortcut on small/sparse memory (see above).
3. Call **`create_node`** only if nothing already covers the fact or your new wording is materially different.

Do not rely only on background deduplication. Agents should actively avoid writing duplicates.

### One Fact Per Node

Prefer one durable declarative fact per node.

Good:

- "Production Redis is hosted at redis.internal."
- "User prefers speed over cost."
- "Service A depends on Service B."

Bad:

- "We discussed infrastructure and maybe Redis is important."
- "Today we talked about several deployment ideas."

### Update Protocol

For substantive changes, preserve history instead of overwriting the old fact.

1. Call `mark_outdated(fact_id=..., owner_id=..., reason="...")`
2. Call `create_node(text="New fact...", owner_id=..., metadata=...)`

Use `update_node(...)` only for small corrections or metadata adjustments, such as:

- fixing a typo
- improving metadata
- updating TTL

### Metadata

Use `metadata` for structured context such as source, confidence, tags, or timestamps.

Example:

```json
{
  "type": "regulation",
  "confidence": 0.95,
  "source": "https://api.docs.example",
  "tags": ["critical"]
}
```

Note:

- Metadata is returned with the node.
- Metadata is not the main searchable/filterable surface today.
- Put the primary fact in `text`, not only in metadata.

## 4. Relations (Graph Links)

`Fact` and `Entity` are **practical labels**, not a strict ontology (Explorer uses different shapes for humans only). Entity ≈ named concept; Fact ≈ declarative statement. Prefer consistent relations over debating which label to use.

### Default types

| Type | When to use |
|------|-------------|
| `RELATED_TO` | Default association when no finer type is needed |
| `MENTIONS` | Source node refers to, depends on, or is about the target (any node pair) |
| `SUMMARIZES` | Summary fact → source facts |
| `FOLLOWS_FROM` | Temporal or logical precedence |
| `CONTRADICTS` | Explicit conflict between facts |

Use other types (`RUNS_ON`, `USES`, …) only via `create_triplet` or when your team's allowlist includes them.

### Rules

1. **Search before linking** — `search` (+ `get_context` if needed) to avoid redundant edges; `recall_context` only as a shortcut on small graphs.
2. **Do not invent relation types** — the server may reject types outside `RELATION_ALLOWED_TYPES` (default mode: `warn`; production may use `enforce`).
3. **`create_relation` is idempotent per type** — repeating the same `(from_id, relation_type, to_id)` does not duplicate that edge; different types between the same pair are still allowed.
4. **Prefer `links` on `create_node`** when you already know structure at insert time.
5. **Bulk ingest** — set `auto_link=false` to skip automatic `MENTIONS` edges, then link explicitly.
6. **Fix mistakes** — `delete_relation`, `mark_outdated`, or `delete_node`.

### Auto-link

`create_node(..., auto_link=true)` on **Facts** adds `MENTIONS` to semantically similar **Entity** nodes (Entity vector index). It does **not** link Fact→Fact. Disable when bulk-importing (`auto_link=false`) and add `links` / `create_relation` explicitly.

The server enforces allowed relation types from config; you do not need to read that config — follow this document and handle `warning` / errors in tool responses.
