# Configuration

Settings load from the environment and from `.env`. Defaults live in `graph_memory_mcp/config.py`. The full list is `env.example`.

## Owners

`OWNER_SCOPE` decides who picks `owner_id` on `/mcp`.

| Mode | Owner | Client sends |
|------|--------|----------------|
| `client` (default) | Tool argument `owner_id` | `owner_id` on every call |
| `header` | `X-Owner-Id` | The header, from your gateway. The tool argument is ignored. |
| `token` | Owner stored for the API key | `Authorization: Bearer <key>`. The tool argument is ignored. |

`client` is the simple install. `header` is for a gateway you run, and for a hosted service in front of this process. `token` is the multi-user mode that stays in this process: one config line, no second server.

Jobs are not HTTP requests. They keep the owner they were given in every mode.

### Token keys

```bash
uv run graph-memory-mcp keys create --owner alice
uv run graph-memory-mcp keys list
uv run graph-memory-mcp keys revoke k_0123abcd
```

`create` prints the raw key once. The file (`API_KEYS_FILE`, default `keys.json`, relative to the process working directory) stores:

```json
{
  "keys": [
    {
      "id": "k_0123abcd",
      "owner": "alice",
      "hash": "<sha256 hex>",
      "created_at": "2026-10-22T18:00:00+00:00",
      "revoked": false
    }
  ]
}
```

A request with no key, an unknown key, or a revoked key gets HTTP 401 and does not run the tool. The owner id format is the same as everywhere else: letters, digits, `-`, `_`, `@`.

The server refuses to start in `token` mode when `ADMIN_TOKEN` is empty, or when the keys file is missing or not valid JSON. `/admin` takes the owner from the path or body. In `token` mode those routes always require `ADMIN_TOKEN`. In `client` and `header` they stay open when the token is empty.

## `/internal/graph-size`

The route has no `owner_id` query parameter.

| `OWNER_SCOPE` | Credential | Owner |
|---------------|------------|--------|
| `client` | `Authorization: Bearer $ADMIN_TOKEN` | `X-Owner-Id` |
| `header` | none | `X-Owner-Id`. A gateway keeps calling it without `ADMIN_TOKEN`. |
| `token` | `Authorization: Bearer <api key>` | The key's owner. `X-Owner-Id` is ignored. |

In `client`, a missing admin token is HTTP 401 and a missing `X-Owner-Id` is HTTP 400. In `header`, a missing `X-Owner-Id` is HTTP 400. In `token`, a missing or unknown key is HTTP 401.

## `/metrics`

`/metrics` has no auth in any mode. It publishes handler, cache, and job counters, plus totals summed across owners (node count by label, number of owner graphs). It does not name an owner or return that owner's records.
