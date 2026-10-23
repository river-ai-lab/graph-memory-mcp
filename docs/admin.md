# Admin HTTP

Same process as `/mcp`. In `client` and `header`, `ADMIN_TOKEN` is `Authorization: Bearer …` and the routes are open when it is unset. In `token`, the server does not start without it.

| Route | Method | Purpose |
|-------|--------|---------|
| `/admin/health` | GET | graph backend, embeddings, indexes (≤20 owners), cache |
| `/admin/ensure-indexes` | POST | vector/range indexes per owner graph |
| `/admin/export/{owner_id}` | GET | nodes+relations; `?include_versions=&limit=&offset=&section=nodes\|relations` |
| `/admin/import` | POST | `{owner_id, nodes, relations?, regenerate_embeddings?}` merge by `uid` (Fact/Entity/FactVersion) |
| `/admin/owners/{owner_id}` | DELETE | drop owner graph |
| `/admin/prune-empty-owners` | POST | drop empty owner graphs |
| `/metrics` | GET | Prometheus. Open in every mode. Totals only: no owner name and no owner records. |
| `/internal/graph-size` | GET | Owner graph size. `client` and `header`: `ADMIN_TOKEN` plus `X-Owner-Id`. `token`: the API key. |

```bash
curl -s localhost:8000/admin/health | jq .healthy
curl -s -X POST localhost:8000/admin/ensure-indexes
curl -s "localhost:8000/admin/export/team_a?limit=500&section=nodes"
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" localhost:8000/admin/health
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" -H "X-Owner-Id: team_a" localhost:8000/internal/graph-size
```

`/admin/*` takes `owner_id` from the path or JSON body in every `OWNER_SCOPE` mode. In `client` and `header`, auth is `ADMIN_TOKEN` when set, and the route is open when it is empty. In `token` mode the server does not start without `ADMIN_TOKEN`, and these routes return 401 without it: the API key does not cover `/admin`. Do not publish `/admin` or `/internal` on a public edge.

`/metrics` is unauthenticated in every mode. Counters cover handlers, cache, and jobs. Node counts are summed by label across owners, and one gauge is the number of owner graphs. The scrape does not include an owner id or that owner's records.

`/internal/graph-size` returns `{owner_id, nodes, node_count, relation_count, bytes}`. `bytes` is Redis `MEMORY USAGE` of that owner's graph key, or `null` if it cannot be read. There is no `owner_id` query parameter. RPM and request counts are not counted here.

In `client` and `header`, the route requires `ADMIN_TOKEN` and `X-Owner-Id`. A missing token is HTTP 401. A missing header is HTTP 400. In `token`, the route requires the API key; `X-Owner-Id` must be one of the key's projects, or the first project is used. A missing key is HTTP 401. A foreign project is HTTP 403.

`OWNER_SCOPE=header` applies to `/mcp`: the tool argument `owner_id` is dropped and `X-Owner-Id` is required. Run it on `127.0.0.1` behind a gateway. The gateway sends `Authorization: Bearer $ADMIN_TOKEN`; a missing or wrong bearer is HTTP 401 when that token is set. A non-loopback bind without `ADMIN_TOKEN` refuses to start (`ALLOW_INSECURE_HEADER=1` warns and starts). `OWNER_SCOPE=client` (default) keeps the tool argument. `OWNER_SCOPE=token` requires a Bearer key; `owner_id` must be one of the key's projects. See [Owners](../README.md#owners), [team-setup](./team-setup.md), and [configuration](./configuration.md).

Backups: [README](../README.md). Re-expose as MCP: `MCP_EXPOSE_ADMIN_TOOLS=true`.
