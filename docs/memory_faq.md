# Memory FAQ

## Recall

- **About X?** → `search(query="X")` → `get_context` on best hits. `recall_context` only on small/sparse graphs.
- **X ↔ Y?** → `search` both → `get_trace(from_id, to_id)` (`directed=false` if empty).

## Forget

No `forget_topic`. `search` → filter → `mark_outdated` (Facts) or `delete_node` / `delete_relation`. Tag at write time if you expect bulk cleanup.

## Fact vs Entity

- **Fact** — declarative `text`. **Entity** — named thing. Practical labels, not ontology. Link with `MENTIONS` / `RELATED_TO`.

## Metadata

Searchable substance lives in `text`. Reserved keys (typed, filterable via `metadata_filter`): `project`, `created_by`, `tags`, `type`, `confidence`. Other keys are free-form.

## Indexes

Fact + Entity vector indexes: auto on first `search` / `find_similar` / Fact `auto_link`, or `AUTO_CREATE_INDEXES=true`, or `POST /admin/ensure-indexes`. Recreate definitions only if embedding **dimension** changes; model/prefix change → re-embed corpus.

## Isolation

Each `owner_id` = own FalkorDB graph. Same `owner_id` → shared memory. Soft split inside owner: `metadata.project`. Always pass `owner_id` explicitly.

## Lifecycle

`active` (default search) · `outdated` (soft-delete Fact) · `archived` (TTL/stale job). Use `include_outdated` / `status` to see non-active.

## Agent vs Explorer

Agents → MCP tools. Explorer → human read-only GUI over MCP.

Policy: [memory_policies_for_LLM.md](./memory_policies_for_LLM.md).
