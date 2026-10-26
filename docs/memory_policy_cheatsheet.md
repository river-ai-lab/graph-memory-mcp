# Graph Memory — Cheat Sheet

Constants from your operator (apply, never invent): `<OWNER_ID>` required — pass on every call; `<PROJECT>` optional — `metadata={"project": ...}` on writes, `metadata_filter={"project": ...}` on reads; `<AGENT_ID>` optional — `metadata.created_by` (and `metadata.updated_by` when the editor differs). Example: [`AGENTS_example.md`](./AGENTS_example.md).

`client`/`header`: pass `owner_id`; put attribution in `metadata.created_by` and `metadata.updated_by`. `token`: pass `owner_id` only to pick among the key's projects; the server sets `created_by` / `updated_by` from the key name.

## Rules

Generated from [`memory_policies_for_LLM.md`](./memory_policies_for_LLM.md); edit the rules there.

<!-- BEGIN GENERATED rules (scripts/gen_policy.py) -->
1. Graph Memory is a long-term knowledge graph, not a chat log.
2. Session start: `get_brief` (project state, not the task), then `search(query=<task>, compact=true)`. `suggested_next` is a hint.
3. Search before `create_node`.
4. One durable declarative fact per node; no metric tables or dumps in `text`.
5. Never store chat logs, scratchpad reasoning, secrets/PII, transient execution state, or unlabeled guesses.
6. Substantive change: `mark_outdated` + `create_node`. Typos or metadata: `update_node`.
7. On `memory_duplicate` or `possible_duplicates`, do not write another paraphrase; update or `mark_outdated` instead.
8. After meaningful work, before the final reply: GROW (Ground → Record → Orient? → Write); skip if nothing durable.
9. Temporary note → `ttl_days` (14–30); decisions and durable outcomes have no TTL.
10. If a tool schema has no `owner_id`, the server sets it from the API key. Do not pass it.
11. Write back what you had to find: if `search` missed and you found the answer, store it phrased close to the question, with its source in `metadata`.
12. Default reads hide TTL and outdated facts; pass `include_ttl=true` or `include_outdated=true` to see them.
13. Use the allowed relation types; do not invent new ones.
14. `source_updated_at` is the source document time in Unix milliseconds, not the server-managed `updated_at`.
<!-- END GENERATED rules -->

## Situation → tool

| Situation | Call |
|-----------|------|
| "What do we know about X?" | `search(query="X", compact=true)` |
| Path between two known IDs | `get_trace(from_id, to_id)` (directed; retry `directed=false`) |
| Quick one-call recall | `recall_context(query, depth=1, compact=true)` |
| Store a fact | `create_node(text, owner_id, metadata)`; temporary → also `ttl_days` |
| Sync from an external system | `upsert_node(text, source={"ref": <stable key>})` |
| Document/conversation → knowledge | extract → `ingest_knowledge(document={"ref": ...}, facts=[{text, ref?, ...}, ...], triplets=[...])` — prefer `facts[].ref`; re-ingest updates in place |
| Link nodes | `create_relation(from_id, to_id, relation_type)` — default allowlist: `RELATED_TO`, `MENTIONS`, `SUMMARIZES`, `FOLLOWS_FROM`, `CONTRADICTS`, `EXTRACTED_FROM`, `SIMILAR_TO`, `NEXT_STEP`, `EXPOSES`, `CROSS_REF`, `RUNS_ON`, `USES`, `SERVED_BY` |

Full policy: [`memory_policies_for_LLM.md`](./memory_policies_for_LLM.md). Put these operator constants in your own AGENTS.md ([`AGENTS_example.md`](./AGENTS_example.md)); prefer that over MCP `resources/read`.
