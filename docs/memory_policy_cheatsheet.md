# Graph Memory — Cheat Sheet

Constants from your operator (apply, never invent): `<OWNER_ID>` required — pass on every call; `<PROJECT>` optional — `metadata={"project": ...}` on writes, `metadata_filter={"project": ...}` on reads; `<AGENT_ID>` optional — `metadata.created_by` (and `metadata.updated_by` when the editor differs). Example: [`AGENTS_example.md`](./AGENTS_example.md).

`client`/`header`: pass `owner_id`; put attribution in `metadata.created_by` and `metadata.updated_by`. `token`: pass `owner_id` only to pick among the key's projects; the server sets `created_by` / `updated_by` from the key name.

Node `updated_at` is the server clock. The source document time is `source_updated_at` (`source.source_updated_at`, or the flat argument on `--simple`).

## Rules

1. `search` before `create_node`; one durable fact per node; no chat logs / secrets / scratchpad; no metric tables in `text`.
2. Fact became wrong → `mark_outdated` + `create_node`. Typo/metadata → `update_node`.
3. `memory_duplicate` or `possible_duplicates`: do not write a third paraphrase. Update, `mark_outdated` + `create_node`, or `check_duplicates=false` only if the fact is different.
4. After meaningful work — GROW before final reply (Ground → Record → Orient? → Write); skip if nothing durable.
5. Temporary note → `ttl_days` (14–30). Decision or durable outcome → no TTL. Server never sets TTL from `type`. Do not store a pod lifecycle. Default search and brief hide facts that have a TTL; `include_ttl=true` shows ones that have not expired.
6. Write back what you had to find:
   - If `search` returned nothing useful and you later found/figured out/did the answer (code, docs, user, debugging), write it as a Fact phrased close to the original question so the same query finds it next time
   - Put the source in `metadata` (file, URL, `"source": "user"`)
   - If it contradicts an existing fact, `mark_outdated` the old one and link new `FOLLOWS_FROM` old instead of creating a duplicate
   - Don't store things cheap to re-read (file contents, transient values)

## Situation → tool

| Situation | Call |
|-----------|------|
| After meaningful work | GROW: Ground → Record → Orient? → Write (`project`+`created_by`); skip if nothing durable |
| Session start | `get_brief(owner_id)` (about + recent facts without TTL + `CONTRADICTS` + `stale_count`; not the task; no `include_stale`) → `search(query=<task>, compact=true)`. `suggested_next` hints at a possible next call; you decide. |
| "What do we know about X?" | `search(query="X", compact=true)`. `suggested_next` is a hint; choose the next call yourself. |
| Opinion changed | `mark_outdated` + `create_node` (no separate supersede tool) |
| Path between two known IDs | `get_trace(from_id, to_id)` (directed; retry `directed=false`) |
| Quick one-call recall | `recall_context(query, depth=1, compact=true)` |
| Store a fact | `create_node(text, owner_id, metadata)`; temporary → also `ttl_days` |
| Document/conversation → knowledge | extract → `ingest_knowledge(document={"ref": ...}, facts=[{text, ref?, ...}, ...], triplets=[...])` — prefer `facts[].ref`; re-ingest updates in place |
| Link nodes | `create_relation(from_id, to_id, relation_type)` — default allowlist: `RELATED_TO`, `MENTIONS`, `SUMMARIZES`, `FOLLOWS_FROM`, `CONTRADICTS`, `EXTRACTED_FROM`, `SIMILAR_TO`, `NEXT_STEP`, `EXPOSES`, `CROSS_REF`, `RUNS_ON`, `USES`, `SERVED_BY` |

Full policy: [`memory_policies_for_LLM.md`](./memory_policies_for_LLM.md). Put these operator constants in your own AGENTS.md ([`AGENTS_example.md`](./AGENTS_example.md)); prefer that over MCP `resources/read`.
