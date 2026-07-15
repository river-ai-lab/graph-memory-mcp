# Admin HTTP API

Operator endpoints on the same server as `/mcp` — separate from agent-facing MCP tools. Auth: optional `ADMIN_TOKEN` env → send `Authorization: Bearer <token>`; open when unset (trusted env).

| Route | Method | Purpose |
|-------|--------|---------|
| `/admin/health` | GET | Component health: FalkorDB, embeddings, vector indexes (per owner, capped 20), cache stats |
| `/admin/ensure-indexes` | POST | Create missing vector/range indexes in every owner graph; per-owner status |
| `/admin/export/{owner_id}` | GET | Export owner (nodes + relations, embeddings included). Pagination: `?limit=&offset=&section=nodes\|relations` → `has_more`/`next_offset` |
| `/admin/import` | POST | Import payload `{owner_id, nodes, relations?, regenerate_embeddings?}`; merges by `uid`, idempotent |
| `/admin/owners/{owner_id}` | DELETE | **Irreversibly** delete an owner's graph |
| `/admin/prune-empty-owners` | POST | Delete owner graphs with zero nodes (test/deleted leftovers) |
| `/metrics` | GET | Prometheus: handler latency/success, cache hit/miss, job runs/duration, node counts (refreshed ≤1/min), owner graph count |

## Examples

```bash
curl -s localhost:8000/admin/health | jq .healthy
curl -s -X POST localhost:8000/admin/ensure-indexes
curl -s "localhost:8000/admin/export/team_a?limit=500&section=nodes" > nodes-page1.json
curl -s -X POST localhost:8000/admin/import -H 'Content-Type: application/json' \
     -d '{"owner_id": "team_a_copy", "nodes": [...]}'
curl -s -X DELETE localhost:8000/admin/owners/old_tenant
curl -s -X POST localhost:8000/admin/prune-empty-owners
# with auth:
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" localhost:8000/admin/health
```

Backups (RDB snapshots, AOF): see [README § Persistence & Backups](../README.md#persistence--backups). To re-expose these operations as MCP tools (e.g. for an admin agent): `MCP_EXPOSE_ADMIN_TOOLS=true`.
