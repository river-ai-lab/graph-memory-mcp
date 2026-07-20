<div align="center">

<img src="assets/logo.svg" alt="Graph Memory MCP logo" width="96">

<h1>Graph Memory MCP</h1>

<p><em>Long-term graph memory for LLM agents via MCP (FalkorDB + embeddings)</em></p>

[![PyPI version](https://badge.fury.io/py/graph-memory-mcp.svg)](https://badge.fury.io/py/graph-memory-mcp)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

</div>

Facts, entities, relations, semantic search, and ops in one MCP server. Isolation is **graph-per-owner**.

## Agent rules (required)

Put the memory ritual in client rules / `AGENTS.md`. Keep [`docs/memory_policy_cheatsheet.md`](docs/memory_policy_cheatsheet.md) or [`docs/memory_policies_for_LLM.md`](docs/memory_policies_for_LLM.md) in session context. Do not rely on MCP `resources/read`.

## What it does

- Fact / Entity nodes + typed edges; stable `node_id` (`uid`)
- Semantic `search`, subgraph `get_context`, path `get_trace`, shortcut `recall_context`
- Writes: `create_node` / `upsert_node` / `create_nodes` / `ingest_knowledge` (agent extracts, server persists)
- Scoping: `owner_id` (hard, own graph) → `metadata.project` → `metadata.created_by`
- Soft lifecycle (`active` / `outdated` / `archived`), optional versioning + `as_of`
- Admin HTTP `/admin/*`, Prometheus `/metrics`; optional background dedup / archive
- Clone + `uv` (not required as a pip library)

API contract: [`docs/features.md`](docs/features.md). Index: [`docs/__index.md`](docs/__index.md).

## Quick start

```bash
cp env.example .env
uv sync
./scripts/falkordb-up.sh          # docker compose; Redis :6379, UI :3000
uv run graph-memory-mcp --host 127.0.0.1 --port 8000
# smoke: uv run python examples/http_client_usage.py
# tests:  ./scripts/test.sh
```

Optional GUI: `uv run graph-memory-explorer` (read-only; MCP server must already run).  
Flat provenance fields: `graph-memory-mcp --simple` (see features.md).

## Config & storage

- Env / `.env` from `env.example`; knobs in `graph_memory_mcp/config.py`
- Each `owner_id` → FalkorDB graph `{FALKORDB_GRAPH}_{owner_id}` (no auto-migration from old shared graph)
- Vector indexes (Fact / Entity): auto on first search/auto_link, or `AUTO_CREATE_INDEXES=true`, or `POST /admin/ensure-indexes`
- e5 prefixes: `EMBEDDING_QUERY_PREFIX` / `EMBEDDING_PASSAGE_PREFIX` (empty by default; enabling on existing data needs re-embed — export/import with `regenerate_embeddings=true`)
- Persistence: AOF in compose; `./scripts/backup.sh`; logical export `GET /admin/export/{owner_id}`

## Docs

| Doc | Role |
|-----|------|
| [cheatsheet](docs/memory_policy_cheatsheet.md) / [policy](docs/memory_policies_for_LLM.md) | Agents |
| [features.md](docs/features.md) | Tool contract |
| [admin.md](docs/admin.md) | `/admin/*`, `/metrics` |
| [memory_faq.md](docs/memory_faq.md) | Short ops FAQ |
| [roadmap.md](docs/roadmap.md) | Unfinished work |
| [comparison.md](docs/comparison.md) | vs other memory stacks |

## Not for

Deep graph analytics (Neo4j), full episodic frameworks (Graphiti/Zep), pure vector DB only (Qdrant/Chroma). Code maps → [Graphify](https://graphify.net/); agent memory → this repo.
