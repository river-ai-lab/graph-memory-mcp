# Agent Memory Policy

You have access to **Graph Memory MCP** — a long-term knowledge base shared across sessions and agents. It is **not a chat log**.

## Core rules

1. **Recall before write**: at task start and before `create_node` — `search` first.
2. **One durable declarative fact per node.** Good: "Production Redis is at redis.internal". Bad: "we discussed infrastructure".
3. **Never store**: chat logs, scratchpad reasoning, secrets/PII, transient execution state, low-confidence guesses (unless labeled in metadata).
4. **Update protocol**: substantive change → `mark_outdated(fact_id, reason)` + `create_node(new text)`. Typos/metadata → `update_node`.
5. **Heed `possible_duplicates`** in write responses: duplicate → link or update instead; conflict → add `CONTRADICTS` or `mark_outdated` the stale fact.
6. **GROW after meaningful work** — before the final reply: Ground → Record → Orient (if recurring) → Write. Do not defer to “end of session”.

## After meaningful work (GROW)

Before the final user reply — not at “end of session” — run this binary checklist:

1. **Ground** — name one durable change (decision, root cause, architecture). If none → stop; do not write.
2. **Record** — `search` first → `create_node`, or `mark_outdated` + `create_node` if a prior fact is wrong.
3. **Orient** — only if the work can recur: `tags=["pattern"]` and/or a relation; skip otherwise.
4. **Write** — set `metadata.project` and `metadata.created_by` on writes.

Do not invent noise to satisfy the checklist.

## Scoping (operator sets these constants in your rules — apply, never invent)

| Constant | Meaning | Usage |
|----------|---------|-------|
| `<OWNER_ID>` (required) | Hard isolation boundary — a company, team, or person; everyone inside sees everything | Pass `owner_id` explicitly on **every** call. Format: alphanumeric + `-` `_` `@` |
| `<PROJECT>` (optional) | Soft partition inside the owner | Writes: `metadata={"project": "<PROJECT>"}`. Reads: `metadata_filter={"project": "<PROJECT>"}`; omit the filter for cross-project recall |
| `<AGENT_ID>` (optional) | Attribution | Writes: `metadata={"created_by": "<AGENT_ID>"}` (e.g. `"agent:codegen"`, `"user:ivan"`) |

**Reserved metadata keys** (typed, filterable, indexed): `project`, `created_by`, `tags` (list of strings), `type`, `confidence` (float). Wrong types are rejected. All other metadata keys are free-form and always allowed. Put the searchable substance in `text`, not in metadata.

## Recall: situation → tool

| Situation | Call |
|-----------|------|
| Session start | `get_brief(owner_id)` — top facts, contradictions, stale facts, stats |
| "What do we know about X?" | `search(query="X", compact=true)` → follow `suggested_next` (usually `get_context` on best hits) |
| Relation between two known IDs | `get_trace(from_id, to_id)` — directed; retry `directed=false` if empty |
| Quick one-call recall | `recall_context(query, depth=1, compact=true)` — search + expansion; shortcut, not the primary API |

`search` / `get_context` / `recall_context`: active-only by default (`include_outdated=true` for outdated/expired/archived neighbors too); `similarity_threshold` and `limit` tune noise; omit `search_type` (server default). Prefer `compact=true` on `search` / `recall_context` when exploring — responses include `snippet`s under a token budget plus `suggested_next` / `do_not`. If `budget.truncated`, follow `suggested_next` (expand 1–3 ids); do not broaden the same query. Returned text/snippets count as already read.

## Write: situation → tool

| Situation | Call |
|-----------|------|
| Store one fact | `search` first → `create_node(text, owner_id, metadata)` |
| Sync from an external system | `upsert_node(text, source={"ref": <stable key>})` — idempotent |
| Many facts at once | `create_nodes(items=[...])` (bulk, no auto_link) |
| Read a document/conversation | extract → **one** `ingest_knowledge(document={"ref": ...}, facts=[{text, ref?, metadata?}, …], triplets=[…])`; prefer `facts[].ref` (else key=`hash(text)`); same ref updates in place |
| Link two nodes | `create_relation(from_id, to_id, relation_type)` |
| Subject–predicate–object | `create_triplet(..., metadata={project, created_by, …})` — entities dedupe by normalized name; metadata on both entities |

## Relations

Allowed types (default): `RELATED_TO` (generic), `MENTIONS`, `SUMMARIZES`, `FOLLOWS_FROM`, `CONTRADICTS`, plus team allowlist (`RUNS_ON`, `USES`, …). Do not invent types — the server may warn or reject. `create_relation` is idempotent per type. `auto_link=true` (default on single `create_node`) adds `MENTIONS` from Facts to similar Entities; disable for bulk.

## Versioning & time

Updates with `versioning=true` (or server default `VERSIONING_DEFAULT`) snapshot the previous state: `get_node_change_history(node_id)` lists versions, `get_node(node_id, as_of=<unix ms>)` reads the state at a point in time.
