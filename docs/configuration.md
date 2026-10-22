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

Set `ADMIN_TOKEN` when the port is reachable by more than one party. `/admin` uses that token and is open when the token is empty. That is a separate door from the API keys.

## `/internal/graph-size`

The route has no `owner_id` query parameter.

| `OWNER_SCOPE` | Credential | Owner |
|---------------|------------|--------|
| `client`, `header` | `Authorization: Bearer $ADMIN_TOKEN` | `X-Owner-Id` |
| `token` | `Authorization: Bearer <api key>` | The key's owner. `X-Owner-Id` is ignored. |

A missing credential is HTTP 401. In `client` and `header`, a missing `X-Owner-Id` is HTTP 400. An empty `ADMIN_TOKEN` does not leave the route open.
