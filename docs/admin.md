# Admin HTTP

Same process as `/mcp`. Auth: `ADMIN_TOKEN` → `Authorization: Bearer …` (open if unset).

| Route | Method | Purpose |
|-------|--------|---------|
| `/admin/health` | GET | FalkorDB, embeddings, indexes (≤20 owners), cache |
| `/admin/ensure-indexes` | POST | vector/range indexes per owner graph |
| `/admin/export/{owner_id}` | GET | nodes+relations; `?include_versions=&limit=&offset=&section=nodes\|relations` |
| `/admin/import` | POST | `{owner_id, nodes, relations?, regenerate_embeddings?}` merge by `uid` (Fact/Entity/FactVersion) |
| `/admin/owners/{owner_id}` | DELETE | drop owner graph |
| `/admin/prune-empty-owners` | POST | drop empty owner graphs |
| `/metrics` | GET | Prometheus (handlers, cache, jobs, node/owner gauges) |

```bash
curl -s localhost:8000/admin/health | jq .healthy
curl -s -X POST localhost:8000/admin/ensure-indexes
curl -s "localhost:8000/admin/export/team_a?limit=500&section=nodes"
# curl -s -H "Authorization: Bearer $ADMIN_TOKEN" localhost:8000/admin/health
```

Backups: [README](../README.md). Re-expose as MCP: `MCP_EXPOSE_ADMIN_TOOLS=true`.
