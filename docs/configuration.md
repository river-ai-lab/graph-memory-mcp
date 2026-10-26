# Configuration

Settings load from the environment and from `.env`. Defaults live in `graph_memory_mcp/config.py`. The full list is `env.example`.

## Owners

`OWNER_SCOPE` decides who picks `owner_id` on `/mcp`.

| Mode | Owner | Client sends |
|------|--------|----------------|
| `client` (default) | Tool argument `owner_id` | `owner_id` on every call. Attribution is `metadata.created_by` / `metadata.updated_by`. |
| `header` | `X-Owner-Id` | The header, from your gateway. The tool argument is ignored. The gateway sends `Authorization: Bearer $ADMIN_TOKEN` when that token is set. Attribution is `metadata.created_by` / `metadata.updated_by`. |
| `token` | A project listed on the API key | `Authorization: Bearer <key>`. `owner_id` must be in the key's `projects`; omit it to use the first. `created_by` / `updated_by` are the key name. |

`client` is the simple install. `header` runs on `127.0.0.1` behind a gateway you control. `token` is the multi-user mode that stays in this process: one config line, no second server.

### Client

`/mcp` has no authentication in `client` mode, and `ADMIN_TOKEN` does not change that. A non-loopback bind (`0.0.0.0`, `::`, a LAN IP) refuses to start: anyone who can reach the port could read, write, and delete any owner's memory. Bind `127.0.0.1` (also `::1` or `localhost`) or use `OWNER_SCOPE=token`. `ALLOW_INSECURE_CLIENT=1` logs a warning and starts anyway, for a trusted network or a container whose port is published only on the host's loopback (`-p 127.0.0.1:8000:8000`).

### Header

Bind the server to `127.0.0.1` (also `::1` or `localhost`). The gateway is the only client: it sets `X-Owner-Id` and sends `Authorization: Bearer $ADMIN_TOKEN`.

`/mcp` returns HTTP 401 when `ADMIN_TOKEN` is set and the bearer is missing or wrong. With no token, `/mcp` still takes `X-Owner-Id`.

If `OWNER_SCOPE=header`, `ADMIN_TOKEN` is unset, and the bind host is not loopback, the process refuses to start. Anyone on the network could impersonate any owner via `X-Owner-Id`. Set `ADMIN_TOKEN` or bind `127.0.0.1`. `ALLOW_INSECURE_HEADER=1` logs a warning and starts anyway. Loopback without a token starts normally.

Jobs are not HTTP requests. They keep the owner they were given in every mode.

### Token keys

```bash
uv run graph-memory-mcp keys create --name alice --projects p1,p2
uv run graph-memory-mcp keys list
uv run graph-memory-mcp keys set-projects k_0123abcd p1,p3
uv run graph-memory-mcp keys revoke k_0123abcd
```

`create` prints the raw key once. `list` shows name, projects, and created time, never the key. `revoke` marks a key revoked by id. The file (`API_KEYS_FILE`, default `keys.json`, relative to the process working directory) stores:

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

`graph-memory-mcp --auth` starts that token entry (`server_auth.py`) even when `OWNER_SCOPE` is unset. Like any `OWNER_SCOPE=token` server, it refuses to start without `ADMIN_TOKEN`. Tool schemas omit `owner_id`. The server uses the key's first project. `created_by` is not a tool argument; token mode sets it from the key name. The default, `--simple`, and `--extended` processes keep `owner_id` in the schema. `graph-memory-explorer --auth` with `GRAPH_MEMORY_API_KEY` or `--token` calls that server. The memory name shows the key's first project and cannot be edited.

A request with no key, an unknown key, or a revoked key gets HTTP 401 and does not run the tool. An `owner_id` that is not in the key's projects is HTTP 403 or a tool error (`memory_forbidden`). `name` and each project use the same format as `owner_id`: letters, digits, `-`, `_`, `@`.

The server sets `created_at` / `updated_at` on every write, including `mark_outdated`. The source document time is `source.source_updated_at` (the flat `source_updated_at` argument on `--simple`), stored separately from that clock. Older `source.updated_at` is still accepted and read back as `source_updated_at`. In `client` and `header`, `created_by` / `updated_by` come from `metadata.created_by` and `metadata.updated_by` when those keys are present (relation writes use the same keys on `properties`). Missing keys leave the fields empty. `metadata.created_by` stays in the stored JSON, and an update that includes it copies it onto `n.created_by`, as before. In token mode both fields are the key's `name`, and client-supplied `created_by` / `updated_by` / `created_at` / `updated_at` are ignored for those properties. `/admin` import keeps `created_*` / `updated_*` from the dump and fills them with the server clock only when they are missing. The MCP `import_owner` tool, when exposed, strips those fields. That call is a streamable HTTP POST, and the SDK rejects a body larger than 4 MiB. `/admin/import` is a separate route and is not under that limit.

The server refuses to start in `token` mode when `ADMIN_TOKEN` is empty, or when the keys file is missing or not valid JSON. `/admin` takes the owner from the path or body. In `token` mode those routes always require `ADMIN_TOKEN`. In `client` and `header` they stay open when the token is empty. Header mode's own startup check is above: a non-loopback bind without `ADMIN_TOKEN` does not start.

## Backends

ArcadeDB 26.10 or newer is required; `docker-compose.yml` pins `arcadedata/arcadedb:26.10.2`. ArcadeDB 25.10.1 fails at startup with `Index type 'LSM_VECTOR' is not supported`.

## `/internal/graph-size`

The route has no `owner_id` query parameter.

| `OWNER_SCOPE` | Credential | Owner |
|---------------|------------|--------|
| `client` | `Authorization: Bearer $ADMIN_TOKEN` | `X-Owner-Id` |
| `header` | `Authorization: Bearer $ADMIN_TOKEN` | `X-Owner-Id` |
| `token` | `Authorization: Bearer <api key>` | `X-Owner-Id` if it is in the key's projects; otherwise the first project. A foreign project is HTTP 403. |

In `client` and `header`, a missing admin token is HTTP 401 and a missing `X-Owner-Id` is HTTP 400. In `token`, a missing or unknown key is HTTP 401.

## `/metrics`

`/metrics` has no auth in any mode. It publishes handler, cache, and job counters, plus totals summed across owners (node count by label, number of owner graphs). It does not name an owner or return that owner's records.

## Embeddings

`EMBEDDING_BACKEND=onnx` (default) downloads fp32 `onnx/model.onnx` and `tokenizer.json` from `EMBEDDING_MODEL` (default `intfloat/multilingual-e5-base`) and runs them with ONNX Runtime. Mean / CLS pooling follows `1_Pooling/config.json`. Vectors are L2-normalized. `EMBEDDING_QUERY_PREFIX` and `EMBEDDING_PASSAGE_PREFIX` default to empty. `env.example` sets `query: ` and `passage: ` for this e5 model.

Quantized ONNX files are not loaded. `EMBEDDING_BACKEND=torch` uses sentence-transformers and requires `uv sync --extra torch`. Changing the model or the prefixes still requires re-embedding the corpus. Switching `onnx` and `torch` for the same model and prefixes does not.
