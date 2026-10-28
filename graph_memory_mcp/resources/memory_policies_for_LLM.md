# Agent Memory Policy

<!-- rule:not-a-chat-log scope:common summary:"Graph Memory is a long-term knowledge graph, not a chat log." -->
You have access to **Graph Memory MCP** — a long-term knowledge base shared across sessions and agents. It is **not a chat log**.

## Core rules

<!-- rule:start-reads scope:common summary:"Session start: `get_brief` (project state, not the task), then `search(query=<task>, compact=true)`. `suggested_next` is a hint." -->
<!-- rule:search-first scope:common tools:create_node,create_nodes summary:"Search before `create_node`." -->
1. **Start with two reads.** `get_brief(owner_id)` is project state: `about` if present, recent facts without TTL, open `CONTRADICTS`, and `stale_count`. It is not the task. Do not pass `include_stale`. Then `search(query=<task>, compact=true)`. `suggested_next` lists possible next calls; you decide which, if any, to take. Before `create_node`, `search` first.
<!-- rule:one-fact scope:common tools:create_node,create_nodes summary:"One durable declarative fact per node; no metric tables or dumps in `text`." -->
2. **One durable declarative fact per node.** Good: "Production Redis is at redis.internal". Bad: "we discussed infrastructure". Do not put metric tables or dumps (including APE tables) in `text`. A number that is the fact itself stays in the sentence.
<!-- rule:never-store scope:common summary:"Never store chat logs, scratchpad reasoning, secrets/PII, transient execution state, or unlabeled guesses." -->
3. **Never store**: chat logs, scratchpad reasoning, secrets/PII, transient execution state, low-confidence guesses (unless labeled in metadata).
<!-- rule:update-protocol scope:common tools:update_node,mark_outdated summary:"Substantive change: `mark_outdated` + `create_node`. Typos or metadata: `update_node`." -->
4. **Update protocol**: substantive change → `mark_outdated(fact_id, reason)` + `create_node(new text)`. Typos/metadata → `update_node`.
<!-- rule:no-paraphrase tools:create_node summary:"On `memory_duplicate` or `possible_duplicates`, do not write another paraphrase; update or `mark_outdated` instead." -->
5. **No third paraphrase.** `create_node` returns `memory_duplicate` before write when a near-copy already exists. Update that node or `mark_outdated` it. Pass `check_duplicates=false` only when the new fact is different. A `possible_duplicates` list on a successful write is the same stop: do not create another wording of it.
<!-- rule:grow scope:common summary:"After meaningful work, before the final reply: GROW (Ground → Record → Orient? → Write); skip if nothing durable." -->
6. **GROW after meaningful work** — before the final reply: Ground → Record → Orient (if recurring) → Write. Do not defer to “end of session”.
<!-- rule:ttl tools:create_node summary:"Temporary note → `ttl_days` (14–30); decisions and durable outcomes have no TTL." -->
7. **Temporary facts carry `ttl_days`.** The server never sets it and does not infer it from `metadata.type`. A decision or durable outcome has no TTL. A run, pod, launch, or debug note uses `ttl_days` (typically 14–30). Do not store a pod lifecycle; store the decision and the outcome. A wrong prior fact is `mark_outdated` + `create_node`.
<!-- rule:owner-from-key summary:"If a tool schema has no `owner_id`, the server sets it from the API key. Do not pass it." -->
8. **If a tool schema has no `owner_id`,** the server sets it from the API key. Do not pass it.

<!-- rule:write-back scope:common summary:"Write back what you had to find: if `search` missed and you found the answer, store it phrased close to the question, with its source in `metadata`." -->
9. **Write back what you had to find.** If `search` returned nothing useful and you later found the answer (code, docs, user, debugging), store it as a Fact phrased close to the original question so the same query finds it next time. Put the source in `metadata` (file, URL, `"source": "user"`). If it contradicts an existing fact, `mark_outdated` the old one and link the new one `FOLLOWS_FROM` the old. Do not store things that are cheap to re-read (file contents, transient values).

## After meaningful work (GROW)

Before the final user reply — not at “end of session” — run this binary checklist:

1. **Ground** — name one durable change (decision, root cause, architecture). If none → stop; do not write.
2. **Record** — `search` first → `create_node`, or `mark_outdated` + `create_node` if a prior fact is wrong.
3. **Orient** — only if the work can recur: `tags=["pattern"]` and/or a relation; skip otherwise.
4. **Write** — set `metadata.project` and `metadata.created_by` on writes.

Do not invent noise to satisfy the checklist.

## Scoping (operator sets these constants in your rules — apply, never invent)

Example AGENTS.md block with these constants: [`AGENTS_example.md`](./AGENTS_example.md). Put these operator constants in your own AGENTS.md.

| Constant | Meaning | Usage |
|----------|---------|-------|
| `<OWNER_ID>` (required) | Hard isolation boundary — a company, team, or person; everyone inside sees everything | Pass `owner_id` explicitly on **every** call. Format: alphanumeric + `-` `_` `@`. On a trusted server this value selects the graph. When `OWNER_SCOPE=header`, the server uses the `X-Owner-Id` HTTP header instead. When `OWNER_SCOPE=token`, `owner_id` must be one of the API key's projects; omit it to use the first project. |

**Owner scope.** `client` (default) and `header`: pass `owner_id` (or rely on `X-Owner-Id`). Put attribution in `metadata.created_by` and, when the editor differs, `metadata.updated_by`. `token`: the server sets `created_by` / `updated_by` from the key name; pass `owner_id` only to pick among the key's projects.
| `<PROJECT>` (optional) | Soft partition inside the owner | Writes: `metadata={"project": "<PROJECT>"}`. Reads: `metadata_filter={"project": "<PROJECT>"}`; omit the filter for cross-project recall |
| `<AGENT_ID>` (optional) | Attribution | Writes: `metadata={"created_by": "<AGENT_ID>"}` (e.g. `"agent:codegen"`, `"user:ivan"`). Set `metadata.updated_by` when the editor differs. |

**Reserved metadata keys** (typed, filterable, indexed): `project`, `created_by`, `tags` (list of strings), `type`, `confidence` (float). Wrong types are rejected. All other metadata keys are free-form and always allowed. Put the searchable substance in `text`, not in metadata.

## Recall: situation → tool

| Situation | Call |
|-----------|------|
| Session start | `get_brief(owner_id)` (state, not the task; no `include_stale`) → `search(query=<task>, compact=true)`. `suggested_next` hints at a possible next call; you decide. Keep `about` via `upsert_node(..., source.ref="about")`. |
| "What do we know about X?" | `search(query="X", compact=true)`. `suggested_next` is a hint; choose the next call yourself. |
| Relation between two known IDs | `get_trace(from_id, to_id)` — directed; retry `directed=false` if empty |
| Quick one-call recall | `recall_context(query, depth=1, compact=true)` — search + expansion; shortcut, not the primary API |

<!-- rule:hidden-by-default tools:search,get_context,recall_context summary:"Default reads hide TTL and outdated facts; pass `include_ttl=true` or `include_outdated=true` to see them." -->
`search` / `get_context` / `recall_context`: active durable facts by default. A fact with `ttl_days` is omitted until `include_ttl=true` (still living) or `include_outdated=true` (also outdated, archived, expired). `get_brief` never returns TTL facts. `similarity_threshold` and `limit` tune noise; omit `search_type` (server default). Prefer `compact=true` on `search` / `recall_context` when exploring — responses include `snippet`s under a token budget plus `suggested_next` / `do_not`. `suggested_next` is a hint. If `budget.truncated`, the full text is a `get_node` away. Returned text/snippets count as already read.

## Write: situation → tool

| Situation | Call |
|-----------|------|
| Store one fact | `search` first → `create_node`. On `memory_duplicate`, do not paraphrase again. |
| Sync from an external system | `upsert_node(text, source={"ref": <stable key>})` — idempotent |
| Many facts at once | `create_nodes(items=[...])` (bulk, no auto_link) |
| Read a document/conversation | extract → **one** `ingest_knowledge(document={"ref": ...}, facts=[{text, ref?, metadata?}, …], triplets=[…])`; prefer `facts[].ref` (else key=`hash(text)`); same ref updates in place |
| Link two nodes | `create_relation(from_id, to_id, relation_type)` |
| Subject–predicate–object | `create_triplet(..., metadata={project, created_by, …})` — entities dedupe by normalized name; metadata on both entities |

## Relations

<!-- rule:relation-types tools:create_relation summary:"Use the allowed relation types; do not invent new ones." -->
Allowed types (default): `RELATED_TO` (generic), `MENTIONS`, `SUMMARIZES`, `FOLLOWS_FROM`, `CONTRADICTS`, `EXTRACTED_FROM`, `SIMILAR_TO`, `NEXT_STEP`, `EXPOSES`, `CROSS_REF`, `RUNS_ON`, `USES`, `SERVED_BY`. Do not invent types — the server may warn or reject. `create_relation` is idempotent per type. `auto_link` defaults to false. Pass `auto_link=true` only when a Fact should gain `MENTIONS` to similar Entities. Prefer `create_relation` or `links` for an edge you mean. `get_context` fills its node budget with `CONTRADICTS` and `FOLLOWS_FROM` before `MENTIONS`.

## Versioning & time

Updates with `versioning=true` (or server default `VERSIONING_DEFAULT`) snapshot the previous state: `get_node_change_history(node_id)` lists versions, `get_node(node_id, as_of=<unix ms>)` reads the state at a point in time.

<!-- rule:source-time scope:common summary:"`source_updated_at` is the source document time in Unix milliseconds, not the server-managed `updated_at`." -->
The server sets `created_at` and `updated_at`. The source document time is `source.source_updated_at` (Unix milliseconds), or the flat `source_updated_at` argument on `--simple`. Do not send `updated_at` to set either clock. Older `source.updated_at` is still accepted and returned as `source_updated_at`.
