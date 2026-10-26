# AGENTS.md example

Put these operator constants in your own AGENTS.md. The memory policy lives in [memory_policies_for_LLM.md](./memory_policies_for_LLM.md) and [memory_policy_cheatsheet.md](./memory_policy_cheatsheet.md).

| Constant | Example value | Usage |
|----------|---------------|-------|
| `owner_id` | `"acme"` | Pass on every call in `client` mode. `header`: the server uses `X-Owner-Id`. `token`: must be one of the API key's projects; omit it to use the first project. In token mode with `graph-memory-mcp --auth`, the schema has no `owner_id`; it is not needed. |
| `project` | `"my-project"` | Writes: `metadata.project`. Reads: `metadata_filter={"project": "my-project"}` (omit for cross-project recall). |
| `created_by` | `"agent:codegen"` / `"user:alice"` | `client` and `header`: `metadata.created_by` (and `metadata.updated_by` when the editor differs). `token`: the server sets both from the key name. |
| `node_type` | `"Fact"` or `"Entity"` | Fact = one statement; Entity = a named thing. `--extended` also accepts `Collection`, `User`, and `Project`. |
| `text` | one clear declarative statement | Substance goes in `text`, not in metadata. |
| `metadata` | reserved: `project`, `created_by`, `tags`, `type`, `confidence` | Wrong types are rejected; other keys are free-form. |
| `query` | a question or keywords | Required in `search` together with `owner_id`. |
