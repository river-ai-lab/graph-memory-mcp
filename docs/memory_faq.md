# Memory FAQ

## Recall

A task starts with two reads. You decide what to call after that:

1. `get_brief(owner_id)` — project state: `about` if an agent stored `source.ref=about`, recent facts **without** TTL, open `CONTRADICTS`, and `stale_count`. Not the task, and not a ranking by how many edges a node has. Do not pass `include_stale` here.
2. `search(query=<task>, compact=true)` — the task. `suggested_next` hints at a possible next call; you decide what to do.

`search` / `get_context` / `recall_context` hide facts that have `ttl_days` until `include_ttl=true` (still living) or `include_outdated=true` (also outdated, archived, expired). If two hits already have a `CONTRADICTS` edge, they come back in `contradiction_pairs` and `suggested_next` leads with `get_trace` / `mark_outdated`.

`get_context` fills its node budget (default 20, hard cap 50) with `CONTRADICTS`, then `FOLLOWS_FROM`, then other allowlist edges; `MENTIONS` last. `relation_priority` overrides that order. `exclude_relation_types` drops those edges.

`recall_context` is a shortcut on small graphs, not the default path.

- **X ↔ Y?** → `get_trace(from_id, to_id)` (`directed=false` if empty).

## Write

One durable sentence per Fact. Do not put metric tables or dumps in `text`. A number that is the fact itself stays in the sentence.

`create_node(check_duplicates=true)` refuses a near-paraphrase before write (`memory_duplicate`, similarity ≥ `CREATE_DUPLICATE_BLOCK_THRESHOLD`, default 0.92) and returns `diff_hint`. Do not write a third wording. Update the existing node, or `mark_outdated` + `create_node`. Pass `check_duplicates=false` only when the fact is similar by distance but different. Text longer than `LONG_TEXT_WARN_CHARS` (600) is warned in `warnings` and still stored.

The server never sets `ttl_days` and does not infer it from `metadata.type`. A decision or durable outcome has no TTL. A run, pod, launch, or debug note passes `ttl_days` (typically 14–30). After `expires_at`, default search hides the fact. With `JOBS_ENABLED=true`, the archive job sets `status=archived` even if the fact has relations.

`auto_link` defaults to false. Pass `auto_link=true` on a Fact to add `MENTIONS` to similar Entities. An edge you mean is `create_relation` or `links`.

There is no `supersede_node`. A changed opinion is `mark_outdated` + `create_node`.

## Forget

No `forget_topic`. `search` → filter → `mark_outdated` (Facts) or `delete_node` / `delete_relation`. Tag at write time if you expect bulk cleanup.

## Fact vs Entity

- **Fact** — declarative `text`. **Entity** — named thing. Practical labels, not ontology. Link with `MENTIONS` / `RELATED_TO`.

## Metadata

Searchable substance lives in `text`. Reserved keys (typed, filterable via `metadata_filter`): `project`, `created_by`, `tags`, `type`, `confidence`. Other keys are free-form.

## Indexes

Fact + Entity vector indexes: created on the first write for an owner, cached per owner. Also on `search` / `find_similar` / Fact `auto_link` when still missing, or `AUTO_CREATE_INDEXES=true`, or `POST /admin/ensure-indexes`. Recreate definitions only if embedding **dimension** changes; model or prefix change → re-embed corpus. `EMBEDDING_BACKEND=onnx` and `torch` share vectors for the same model and prefixes.

## Isolation

Each `owner_id` is its own ArcadeDB database, or its own FalkorDB graph when `GRAPH_BACKEND=falkordb`. Same `owner_id` is shared memory. Soft split inside owner: `metadata.project`. Always pass `owner_id` explicitly (server default: `DEFAULT_OWNER_ID`, usually `"default"`).

`OWNER_SCOPE=client` (default, trusted network) uses that argument. `OWNER_SCOPE=header` runs on `127.0.0.1` behind a reverse proxy: the proxy sets `X-Owner-Id` and sends `ADMIN_TOKEN` when that token is set, and the tool argument is ignored. `OWNER_SCOPE=token` requires a Bearer API key. `owner_id` must be one of the key's projects; an empty argument uses the first project. The tool schema is the same, and `client` mode needs the value. See [configuration.md](./configuration.md).

## Lifecycle

`active` (default search, and only facts with no TTL) · `outdated` (soft-delete Fact) · `archived` (TTL expiry or stale job). `include_ttl=true` adds still-living temporary facts. `include_outdated` / `status` show non-active.

## Agent vs Explorer

Agents → MCP tools. Explorer → human read-only GUI over MCP.

Policy: [memory_policies_for_LLM.md](./memory_policies_for_LLM.md).
