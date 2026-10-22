# Configuration

Settings load from the environment and from `.env`. Defaults live in `graph_memory_mcp/config.py`. The full list is `env.example`.

## Owners

`OWNER_SCOPE` decides who picks `owner_id` on `/mcp`.

| Mode | Owner | Client sends |
|------|--------|----------------|
| `client` (default) | Tool argument `owner_id` | `owner_id` on every call. Attribution is `metadata.created_by` / `metadata.updated_by`. |
| `header` | `X-Owner-Id` | The header, from your gateway. The tool argument is ignored. Attribution is `metadata.created_by` / `metadata.updated_by`. |
| `token` | A project listed on the API key | `Authorization: Bearer <key>`. `owner_id` must be in the key's `projects`; omit it to use the first. `created_by` / `updated_by` are the key name. |

`client` is the simple install. `header` is for a gateway you run, and for a hosted service in front of this process. `token` is the multi-user mode that stays in this process: one config line, no second server.

Jobs are not HTTP requests. They keep the owner they were given in every mode.

### Token keys

```bash
uv run graph-memory-mcp keys create --name alice --projects p1,p2
uv run graph-memory-mcp keys list
uv run graph-memory-mcp keys set-projects k_0123abcd p1,p3
uv run graph-memory-mcp keys revoke k_0123abcd
```

`create` prints the raw key once. `list` shows name, projects, and created time, never the key. The file (`API_KEYS_FILE`, default `keys.json`, relative to the process working directory) stores:

```json
{
  "keys": [
    {
      "id": "k_0123abcd",
      "hash": "<sha256 hex>",
      "name": "alice",
      "projects": ["p1", "p2"],
      "created_at": "2026-10-22T18:00:00+00:00",
      "revoked": false
    }
  ]
}
```

A file that still has `"owner": "alice"` (no `projects`) is read as `name=alice`, `projects=["alice"]`.

A request with no key, an unknown key, or a revoked key gets HTTP 401 and does not run the tool. An `owner_id` that is not in the key's projects is HTTP 403 or a tool error (`memory_forbidden`). `name` and each project use the same format as `owner_id`: letters, digits, `-`, `_`, `@`.

The server sets `created_at` / `updated_at` on every write, including `mark_outdated`. In `client` and `header`, `created_by` / `updated_by` come from `metadata.created_by` and `metadata.updated_by` when those keys are present (relation writes use the same keys on `properties`). Missing keys leave the fields empty. `metadata.created_by` stays in the stored JSON, and an update that includes it copies it onto `n.created_by`, as before. In token mode both fields are the key's `name`, and client-supplied `created_by` / `updated_by` / `created_at` / `updated_at` are ignored for those properties. `/admin` import keeps `created_*` / `updated_*` from the dump and fills them with the server clock only when they are missing. The MCP `import_owner` tool, when exposed, strips those fields.

The server refuses to start in `token` mode when `ADMIN_TOKEN` is empty, or when the keys file is missing or not valid JSON. `/admin` takes the owner from the path or body. In `token` mode those routes always require `ADMIN_TOKEN`. In `client` and `header` they stay open when the token is empty.

## `/internal/graph-size`

The route has no `owner_id` query parameter.

| `OWNER_SCOPE` | Credential | Owner |
|---------------|------------|--------|
| `client` | `Authorization: Bearer $ADMIN_TOKEN` | `X-Owner-Id` |
| `header` | none | `X-Owner-Id`. A gateway keeps calling it without `ADMIN_TOKEN`. |
| `token` | `Authorization: Bearer <api key>` | `X-Owner-Id` if it is in the key's projects; otherwise the first project. A foreign project is HTTP 403. |

In `client`, a missing admin token is HTTP 401 and a missing `X-Owner-Id` is HTTP 400. In `header`, a missing `X-Owner-Id` is HTTP 400. In `token`, a missing or unknown key is HTTP 401.

## `/metrics`

`/metrics` has no auth in any mode. It publishes handler, cache, and job counters, plus totals summed across owners (node count by label, number of owner graphs). It does not name an owner or return that owner's records.
