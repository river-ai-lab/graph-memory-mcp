<div align="center">

<img src="assets/logo.svg" alt="Graph Memory MCP logo" width="96">

<h1>Graph Memory MCP</h1>

<p><em>Semantic, persistent knowledge graph memory for LLM agents via MCP</em></p>

[![Status](https://img.shields.io/badge/status-active%20development-informational)]()
[![PyPI version](https://badge.fury.io/py/graph-memory-mcp.svg)](https://badge.fury.io/py/graph-memory-mcp)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

</div>

Agents store facts, entities, and the edges between them here, and read them back in a later session. The text in the graph is the text the agent wrote. One `owner_id` is one graph.

## Agent policies

Any LLM agent that reads or writes Graph Memory — single-agent or multi-agent — should load the memory ritual from client rules / `AGENTS.md` and keep [`docs/memory_policies_for_LLM.md`](docs/memory_policies_for_LLM.md) (or the shorter [`docs/memory_policy_cheatsheet.md`](docs/memory_policy_cheatsheet.md)) in context **at the start of each session**. That defines what to store, `owner_id` rules, and how to link facts; without it, memory tends to get noisy or mis-scoped. The same full policy is optionally exposed as MCP resource `graph-memory://agent-policies` (clients rarely auto-fetch it — prefer rules).

## What it provides

- **Fact storage** with embeddings (semantic search; hybrid rank: cosine + identifier match + recency)
- **`get_brief`** — project anchor and recent durable facts, separate from search
- **Entity and triplet graph** (subject–predicate–object)
- **Context subgraph** (`get_context`) and paths (`get_trace`)
- **`recall_context`** — one-call search and expand on small graphs
- **Fact versioning and soft-deletion.** Facts with `ttl_days` stay out of default search until `include_ttl=true`
- **Fact auto-linking** — `auto_link=true` on a Fact adds `MENTIONS` to similar Entity nodes (default is false)
- **Near-duplicate writes** refused before insert (`memory_duplicate`); a different fact uses `check_duplicates=false`
- **Multi-tenant isolation** via `owner_id`
- **Background jobs** (deduplication, archival)
- **MCP-native API** (FastMCP)

Backed by **FalkorDB** by default. `GRAPH_BACKEND=arcadedb` uses ArcadeDB with the same tools.

## Install

```bash
uv sync
# or: pip install -e ".[dev,embeddings]"
```

`uv sync` installs runtime deps plus the **dev** group (`pre-commit`, `pytest`, …). Hooks are not global — run them via the project venv:

```bash
uv run pre-commit run --all-files
uv run pre-commit install   # optional: git hooks
```

PyTorch is installed from the **CPU-only** index by default (no NVIDIA/CUDA wheels on Linux). Configured in `pyproject.toml` via `[tool.uv.sources]`.

> [!TIP]
> Check the [examples](examples) directory for code snippets demonstrating various usage patterns (embedded, HTTP, and MCP configuration).

## Run (Development)

### HTTP server

```bash
graph-memory-mcp --host 127.0.0.1 --port 8000
```

Streamable HTTP MCP is at `http://127.0.0.1:8000/mcp`. Tools are MCP calls, not REST paths under `/mcp`.

### Server profiles

Three processes, one handler layer. Tool names match. A client picks one and stays on it.

| | Start | Writes |
|--|--------|--------|
| Default | `graph-memory-mcp` | Nested `source` |
| Simple | `graph-memory-mcp --simple` | Flat provenance (`ref`, `provenance_type`, …). `upsert_node` requires `ref` |
| Extended | `graph-memory-mcp --extended` | Same as default, plus `description`, `shared_with_ids`, `collection_id`, and node types `Collection`, `User`, `Project` |

```bash
graph-memory-mcp --simple --host 127.0.0.1 --port 8000
graph-memory-mcp --extended --host 127.0.0.1 --port 8000
```

See [Server profiles](./docs/features.md#server-profiles).

### Graph Explorer (local GUI)

Read-only web UI to inspect nodes, semantic search, similar facts, and graph context. Proxies read-only MCP tools to a **separately running** Graph Memory server.

```bash
# Terminal 1 — MCP server (FalkorDB must be running; uses .env)
uv run graph-memory-mcp --host 127.0.0.1 --port 8000

# Terminal 2 — Explorer GUI only
uv run graph-memory-explorer --host 127.0.0.1 --port 8088
# optional: --mcp-url http://127.0.0.1:8000/mcp  (or GRAPH_MEMORY_MCP_URL)
```

Open http://127.0.0.1:8088 — enter `owner_id` and a `node_id`, run search, expand neighbors with **+** on hover or **+10 neighbors** in the detail panel.

## Configuration

Settings are loaded from environment variables and optional `.env` file.

You can start from `env.example` (copy it to `.env`).

Key defaults live in `graph_memory_mcp/config.py` within the `MCPServerConfig` class, including:

- `RELATION_POLICY_ENFORCE` — `off` | `warn` (default) | `enforce`
- `RELATION_ALLOWED_TYPES` — comma-separated allowlist for new edges
- `OWNER_SCOPE` — `client` (default) | `header`. See [Owner isolation](#owner-isolation).
- `JOBS_ENABLED` — off by default. On runs archive and dedup. `JOBS_OWNER_IDS` limits them to those owners; empty means every owner. See [background jobs](docs/background_jobs.md).
- Agent link guidance: `docs/memory_policies_for_LLM.md`

## Running the databases

Docker Compose starts both databases. It does not start the MCP server. The code default for `FALKORDB_PASSWORD` is empty, so copy `env.example` before connecting.

```bash
cp env.example .env   # first time only
docker compose up -d
```

| | Port | Credentials in `env.example` |
|--|------|------------------------------|
| FalkorDB | 6379, UI at http://localhost:3000 | password `falkordb123` |
| ArcadeDB | 2480 | user `root`, password `playwithdata` |

FalkorDB is the default backend and is required for the default test run. `./scripts/falkordb-up.sh` starts only FalkorDB. ArcadeDB tests: `uv run pytest -m arcade`.

<details>
<summary>Manual <code>docker run</code> (alternative)</summary>

### With Password Authentication

```bash
docker run -p 6379:6379 -p 3000:3000 -it --rm \
  -v ./data:/var/lib/falkordb/data \
  -e REDIS_ARGS="--requirepass falkordb123" \
  falkordb/falkordb
```

**Note:** Replace `falkordb123` with your desired password and make sure to set the same password in your `.env` file:

```bash
FALKORDB_PASSWORD=falkordb123
```

### Without Password (Development Only)

```bash
docker run -p 6379:6379 -p 3000:3000 -it --rm \
  -v ./data:/var/lib/falkordb/data \
  falkordb/falkordb
```

After starting FalkorDB, you can access the web interface at `http://localhost:3000`.

</details>

### Vector Indexes

The server uses **two vector indexes** (Fact and Entity):

| Index | Used by |
|-------|---------|
| Fact | `search`, `find_similar` |
| Entity | Fact `auto_link` → `MENTIONS` |

**Creation (pick one):**

- **Automatic** — indexes are created on first `search`, `find_similar`, or Fact `auto_link` if missing.
- **Startup** — `AUTO_CREATE_INDEXES=true` in `.env`.
- **Admin** — `POST /admin/ensure-indexes` (or MCP `ensure_vector_indexes` when `MCP_EXPOSE_ADMIN_TOOLS=true`).

FalkorDB keeps index data in sync when nodes change; you only need to recreate index **definitions** after changing embedding model **dimension**.

> [!WARNING]
> **Changing `EMBEDDING_MODEL` invalidates the stored corpus.** Old node embeddings were produced by the old model — new queries will not match them meaningfully. The full procedure is: (1) switch the model, (2) recreate vector index definitions if the dimension changed, (3) **re-embed every node** (currently manual: iterate nodes and `update_node` with the same text, or export/import with `regenerate_embeddings=true`). The same applies to changing prompt/prefix conventions of the same model.

### Embedding prefixes

Some models are trained with prompt prefixes. The default `intfloat/multilingual-e5-base` expects `"query: "` for search queries and `"passage: "` for stored texts. The code default for both prefixes is empty; `env.example` sets them for e5. Enabling prefixes on an existing corpus counts as a model change — re-embed the corpus (see warning above).

## Persistence & Backups

`docker-compose.yml` enables **AOF persistence** (`--appendonly yes --appendfsync everysec`) — a container crash loses at most ~1 second of writes. For point-in-time backups:

```bash
./scripts/backup.sh            # BGSAVE + copy dump.rdb to ./backups (keeps last 14)
# cron example (hourly): 0 * * * * cd /path/to/repo && ./scripts/backup.sh
```

Logical per-owner backups (portable across instances/models): `GET /admin/export/{owner_id}` — supports `?limit=&offset=&section=nodes|relations` for large owners; restore with `POST /admin/import`.

## Multi-Agent Usage

MCP Graph Memory is designed for **multi-agent systems** where multiple agents need to:
- Share knowledge while maintaining isolation
- Build on each other's discoveries
- Access long-term memory across sessions

### Example: Multi-Agent Setup

Use `owner_id` to isolate knowledge between agents/tenants. Values must be alphanumeric plus `-`, `_`, and `@` (see [`docs/memory_policies_for_LLM.md`](docs/memory_policies_for_LLM.md)). For example:

- Agent A writes to `owner_id="team_platform"`
- Agent B searches within `owner_id="team_platform"` (shared) or `owner_id="agent_codegen"` (isolated)

### Owner Isolation

On FalkorDB, isolation is physical: every `owner_id` lives in its own graph (`{FALKORDB_GRAPH}_{owner_id}`) with its own vector indexes. Use `owner_id` to:
- **Isolate agents**: Each agent/team has its own `owner_id` (= its own graph)
- **Share knowledge**: Use the same `owner_id` for shared knowledge base

Who picks that owner is `OWNER_SCOPE` (default `client`):

| | `OWNER_SCOPE=client` | `OWNER_SCOPE=header` |
|---|---|---|
| When | Local or company deploy on a trusted network. No API keys. | Process behind the SaaS gateway |
| Owner | Tool argument `owner_id`. Empty falls back to `DEFAULT_OWNER_ID` (usually `"default"`). | `X-Owner-Id` on the HTTP request. The tool argument is ignored. |
| Missing owner | Server default | Call is rejected. It does not fall back to `DEFAULT_OWNER_ID`. |

Tool names and arguments stay the same in both modes. Agents should still pass `owner_id` explicitly: in `client` that value is the graph; in `header` the gateway's header wins, so a client cannot name someone else's graph.

`/admin/*` always takes the owner from the path or body (operator, optional `ADMIN_TOKEN`). It is not published on the SaaS edge. Background jobs keep the owner they were started with; they do not read `X-Owner-Id`.

Storage quota for the gateway: `GET /internal/graph-size` with `X-Owner-Id` (no owner query parameter). Response: `node_count`, `relation_count`, `nodes`, and `bytes` (Redis memory of that graph key, or `null`). Request rate and request counts are the gateway's job. Details: [`docs/admin.md`](docs/admin.md). Keys, Stripe, and plans are not in this repository.

See [`docs/memory_policies_for_LLM.md`](docs/memory_policies_for_LLM.md) and [`docs/memory_faq.md`](docs/memory_faq.md) for operational guidance.

## ArcadeDB

Optional second graph backend. Leave `GRAPH_BACKEND` unset (or `falkordb`) to keep FalkorDB. Set `GRAPH_BACKEND=arcadedb` and the `ARCADE_*` variables in `.env`. Each `owner_id` gets its own database, `{ARCADE_DATABASE}_{owner_id}`, with its own vertices, edges, and HNSW indexes. The embedding is a property on the vertex. Search inside that database uses `vector.neighbors`.

## Development

The default test run requires FalkorDB (see [Running the databases](#running-the-databases)). ArcadeDB tests are marked `arcade` and use the Compose server on port 2480:

```bash
./scripts/test.sh
# or: docker compose up -d && uv run pytest -q
# ArcadeDB: uv run pytest -m arcade
```

Pre-commit (dev group installed by `uv sync`):

```bash
uv run pre-commit run --all-files
```

## Smoke Test (Quick Verification)

The server uses **Streamable HTTP MCP** at `http://127.0.0.1:8000/mcp`. Tools are invoked with MCP `call_tool` — there is no REST API at `/mcp/tools/...`.

**Terminal 1** — start the server (FalkorDB must be running):

```bash
graph-memory-mcp --host 127.0.0.1 --port 8000
```

**Terminal 2** — run the HTTP MCP client example:

```bash
uv run python examples/http_client_usage.py
```

That script calls `health_check`, `create_node`, and `search` over Streamable HTTP. See [examples/](examples/) for embedded usage and MCP client configuration.

## Where it fits

This server is the store. The agent writes the fact, the `owner_id`, the TTL, and the edge. Search returns what was stored. Embeddings are the only model call inside the server.

[Mem0](https://docs.mem0.ai/) reads a conversation and extracts what to remember for a user. [Graphiti](https://github.com/getzep/graphiti) (the library behind Zep) ingests episodes and keeps a bi-temporal graph: a new fact invalidates the old one, and the old one stays queryable by time.

| Case | Graph Memory MCP | Mem0 | Graphiti |
|------|------|------|----------|
| The agent already has the sentence | `create_node` stores that sentence | An extraction model may split, rewrite, or drop it | An episode pipeline turns it into entities and edges |
| "Remember this chat" and nobody chose the facts | The server does not read a transcript | `add` extracts memories | `add` extracts a temporal graph |
| A decision changed | `mark_outdated` plus a new fact, or an explicit `CONTRADICTS` edge | The extraction model updates or deletes the memory | The old edge is invalidated; history stays |
| A debug note that should disappear | `ttl_days`; default search hides it | No TTL on the memory | Validity windows, not a debug TTL |
| Two agents, one project | Same `owner_id` | `user_id` / `agent_id` / `run_id` | `group_id` |
| No extraction model | Writes do not call an LLM | Every `add` calls an LLM | Several LLM calls per episode |

[`docs/comparison.md`](docs/comparison.md).
