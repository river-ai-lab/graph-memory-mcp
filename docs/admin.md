# Admin HTTP

Same process as `/mcp`. Auth: `ADMIN_TOKEN` → `Authorization: Bearer …` (open if unset).

| Route | Method | Purpose |
|-------|--------|---------|
| `/admin/health` | GET | graph backend, embeddings, indexes (≤20 owners), cache |
| `/admin/ensure-indexes` | POST | vector/range indexes per owner graph |
| `/admin/export/{owner_id}` | GET | nodes+relations; `?include_versions=&limit=&offset=&section=nodes\|relations` |
| `/admin/import` | POST | `{owner_id, nodes, relations?, regenerate_embeddings?}` merge by `uid` (Fact/Entity/FactVersion) |
| `/admin/owners/{owner_id}` | DELETE | drop owner graph |
| `/admin/prune-empty-owners` | POST | drop empty owner graphs |
| `/metrics` | GET | Prometheus (handlers, cache, jobs, node/owner gauges) |
| `/internal/graph-size` | GET | Owner graph size. Closed: `ADMIN_TOKEN` plus `X-Owner-Id`, or the API key when `OWNER_SCOPE=token`. |

```bash
curl -s localhost:8000/admin/health | jq .healthy
curl -s -X POST localhost:8000/admin/ensure-indexes
curl -s "localhost:8000/admin/export/team_a?limit=500&section=nodes"
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" localhost:8000/admin/health
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" -H "X-Owner-Id: team_a" localhost:8000/internal/graph-size
```

`/admin/*` takes `owner_id` from the path or JSON body in every `OWNER_SCOPE` mode. Auth is `ADMIN_TOKEN` when set, and the route is open when it is empty. Do not publish `/admin` or `/internal` on a public edge. In `token` mode set `ADMIN_TOKEN`: the API keys do not cover `/admin`.

`/internal/graph-size` returns `{owner_id, nodes, node_count, relation_count, bytes}`. `bytes` is Redis `MEMORY USAGE` of that owner's graph key, or `null` if it cannot be read. There is no `owner_id` query parameter. RPM and request counts are not counted here.

In `client` and `header`, the route requires `ADMIN_TOKEN`. The owner is `X-Owner-Id`; a missing header is HTTP 400. In `token`, the route requires the API key and uses that key's owner. A missing credential is HTTP 401. An empty `ADMIN_TOKEN` does not leave this route open.

`OWNER_SCOPE=header` applies to `/mcp`: the tool argument `owner_id` is dropped and `X-Owner-Id` is required. `OWNER_SCOPE=client` (default) keeps the tool argument. `OWNER_SCOPE=token` drops the argument and uses the Bearer key. See [Owners](../README.md#owners) and [configuration](./configuration.md).

Backups: [README](../README.md). Re-expose as MCP: `MCP_EXPOSE_ADMIN_TOOLS=true`.
