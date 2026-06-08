<div align="center">

<img src="assets/logo.svg" alt="Graph Memory MCP logo" width="96">

<h1>Graph Memory MCP</h1>

<p><em>Semantic, persistent knowledge graph memory for LLM agents via MCP</em></p>

[![Status](https://img.shields.io/badge/status-active%20development-informational)]()
[![PyPI version](https://badge.fury.io/py/graph-memory-mcp.svg)](https://badge.fury.io/py/graph-memory-mcp)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

</div>

It provides **long-term, shared memory** where agents can store facts, entities, and relations, retrieve context semantically, and build on knowledge across sessions.

> Designed as **agent-ready infrastructure**, not just a database wrapper.

---

## Why MCP-first?

This system treats memory as an agent-accessible capability rather than an application API.
MCP provides a stable contract for tool discovery, invocation, and evolution across agents,
while HTTP remains a low-level transport detail.

### Minimal MCP Flow

```text
LLM / Agent
   │
   │ MCP tool call (e.g., create_node, search)
   ▼
Graph Memory MCP
   │
   ├─ Semantic Search (Embeddings)
   ├─ Graph Traversal (Triplets)
   └─ Memory Governance (Dedup, Archival)
```

## Agent policies

Any LLM agent that reads or writes Graph Memory — single-agent or multi-agent — should have [`docs/memory_policies_for_LLM.md`](docs/memory_policies_for_LLM.md) in context **at the start of each session**. It defines what to store, `owner_id` rules, and how to link facts; without it, memory tends to get noisy or mis-scoped.

---

## Why Graph Memory MCP?

Modern agents need more than ephemeral context windows.

Graph Memory MCP is built for systems that require:

- **Long-term memory** that persists across agent runs
- **Graph structure** to model relationships between facts and entities
- **Semantic recall** over large knowledge bases
- **Operational controls** suitable for production
- **Multi-tenant isolation** for safe multi-agent deployments

**Key idea**: combine **facts + graph + semantics + ops** in one lightweight MCP-native service.

---

## What it provides (currently - limited functionality)

- **Fact storage** with embeddings (semantic search)
- **Entity & triplet graph** (subject–predicate–object)
- **Context subgraph extraction** for agent context building
- **Fact versioning & soft-deletion** (outdated knowledge)
- **Fact auto-linking** — new Facts can auto-create `MENTIONS` edges to similar Entity nodes (`auto_link=true` by default)
- **Multi-tenant isolation** via `owner_id`
- **Background jobs** (deduplication, archival)
- **MCP-native API** (FastMCP)

Backed by **FalkorDB** (pluggable storage layer).

---

**Key advantage**: Tight coupling of **facts + graph + ops** in one lightweight server with practical "agent-ready" tools. No need to orchestrate separate vector DB + graph DB + deduplication services.


---

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

### HTTP Server (Debug/Control)
To run with a persistent HTTP endpoint for manual debugging via `curl`:

```bash
graph-memory-mcp --host 127.0.0.1 --port 8000
```

### Simple server profile (home / personal)

Same handlers and graph behavior as the default server, but MCP tools use **flat provenance fields** (`ref`, `provenance_type`, `uri`, …) instead of a nested `source` object (including `upsert_node`, where `ref` is required).

```bash
graph-memory-mcp --simple --host 127.0.0.1 --port 8000
```

See [Simple server profile](./docs/features.md#simple-server-profile) in the API contract.

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
- Agent link guidance: `docs/memory_policies_for_LLM.md`

## Running FalkorDB

FalkorDB is required for the MCP Graph Memory server and for **all tests**. Recommended: Docker Compose (matches `env.example`):

```bash
cp env.example .env   # first time only
docker compose up -d  # or: ./scripts/falkordb-up.sh
```

Web UI: http://localhost:3000 — Redis port `6379`, password `falkordb123` (see `.env`).

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
- **MCP tool** — `ensure_vector_indexes` (idempotent).

FalkorDB keeps index data in sync when nodes change; you only need to recreate index **definitions** after changing embedding model **dimension**.

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

Use `owner_id` to:
- **Isolate agents**: Each agent/team has its own `owner_id`
- **Share knowledge**: Use the same `owner_id` for shared knowledge base
- **Cross-reference**: Query across owners when needed (with proper permissions)

All MCP tools support `owner_id` parameter (defaults to `"default"`). Agents should pass `owner_id` explicitly rather than relying on the default.

See [`docs/memory_policies_for_LLM.md`](docs/memory_policies_for_LLM.md) and [`docs/memory_faq.md`](docs/memory_faq.md) for operational guidance.

## Development

Tests require FalkorDB (see [Running FalkorDB](#running-falkordb)):

```bash
./scripts/test.sh
# or: docker compose up -d && uv run pytest -q
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

That script calls `ensure_vector_indexes`, `create_node`, and `search` over Streamable HTTP. See [examples/](examples/) for embedded usage and MCP client configuration.

## Why Choose MCP Graph Memory?

### ✅ Best For

- **Multi-agent systems with persistent memory**
- **Agent-oriented memory APIs**
- **Semantic + relational knowledge**
- **Lightweight, MCP-native deployments**
- **Production setups needing ops & control**

### ❌ Not Best For

- **Deep graph analytics** (PageRank, community detection) → Use Neo4j
- **Episodic/temporal memory framework** → Use Graphiti (Zep)
- **Pure vector search only** → Use Qdrant/Chroma

### Positioning

Graph Memory MCP sits between:
- Vector databases (too flat)
- Full graph analytics platforms (too heavy)

It provides practical, agent-ready memory infrastructure.
See [`docs/comparison.md`](docs/comparison.md) for detailed comparison with alternatives.

> **Note:** Some test code was generated with LLM assistance and may require further review and refinement.
