# Roadmap

Agents: [memory_policies_for_LLM.md](./memory_policies_for_LLM.md). Ops: [admin.md](./admin.md).

## Done

- HTTP auth: `OWNER_SCOPE=token` (Bearer API key; `owner_id` must be one of the key's projects, empty uses the first) and `OWNER_SCOPE=header` (`X-Owner-Id`, `ADMIN_TOKEN` when the bind is not loopback)

## Next

- **Search `as_of` timestamp**: Search by time range (currently only `get_node(as_of)` supported)
- **Doctor command**: Health check, index rebuild, corpus re-embedding workflow
- Undirected `get_trace` — bidirectional BFS (path scan is costly on dense graphs)
- Auto `search_type` by owner size (`pre_filter` vs `post_filter` ANN)
- Re-embed script — before prod with stable data (model/prefix changes)
- Pub/sub cache invalidation across instances
- HA — FalkorDB replica + Sentinel (backups already cover durability)

## Later

- Owner groups / cheap cross-owner reads (today: one graph per `owner_id`)
- BM25 + vector hybrid (FalkorDB full-text or external index)
- External ANN (e.g. Qdrant) when one owner grows past ~10⁵ embeddings
- Pluggable storage (`StorageBackend` → Neo4j / Memgraph; Dgraph last)
- Richer versioning (`change_reason`, `changed_by`); `as_of` for relations
- Append-only access events (vs mutable `last_accessed_at`)
- JSONL stream export
