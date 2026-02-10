# Graph Memory MCP

[![Tests](https://github.com/YOUR_USERNAME/graph-memory-mcp/workflows/Tests/badge.svg)](https://github.com/YOUR_USERNAME/graph-memory-mcp/actions)
[![PyPI version](https://badge.fury.io/py/graph-memory-mcp.svg)](https://badge.fury.io/py/graph-memory-mcp)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Graph Memory MCP** is a **semantic, persistent knowledge graph memory** for **LLM-based and multi-agent systems**, exposed via the **Model Context Protocol (MCP)**.

It provides **long-term, shared memory** where agents can store facts, entities, and relations, retrieve context semantically, and build on knowledge across sessions.

> Designed as **agent-ready infrastructure**, not just a database wrapper.

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

## What it provides

- **Fact storage** with embeddings (semantic search)
- **Entity & triplet graph** (subject–predicate–object)
- **Context subgraph extraction** for agent context building
- **Fact versioning & soft-deletion** (outdated knowledge)
- **Automatic entity linking**
- **Multi-tenant isolation** via `owner_id`
- **Background jobs** (deduplication, archival)
- **MCP-native API** (FastMCP)

Backed by **FalkorDB** (pluggable storage layer).

---

**Key advantage**: Tight coupling of **facts + graph + ops** in one lightweight server with practical "agent-ready" tools. No need to orchestrate separate vector DB + graph DB + deduplication services.


---

## Install

```bash
pip install -e ".[dev,embeddings]"
```

## Run (HTTP)

```bash
graph-memory-mcp --host 127.0.0.1 --port 8000
```

## Configuration

Settings are loaded from environment variables and optional `.env` file.

You can start from `env.example` (copy it to `.env`).

Key defaults live in `graph_memory_mcp/config.py` within the `MCPServerConfig` class, including:


## Running FalkorDB

FalkorDB is required for the MCP Graph Memory server. You can run it using Docker:

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

### Creating Vector Indexes

For fast semantic search, create vector indexes once after setting up a fresh database:

```bash
python -m graph_memory_mcp.graph_memory.create_vector_index
```

This script creates **two separate vector indexes**:
- Fact embedding index (for `search` / `find_similar`)
- Entity embedding index (required for Fact→Entity auto-linking via `MENTIONS_ENTITY`)

**Note:** FalkorDB automatically maintains these indexes when nodes are created/updated/deleted—no manual reindexing needed. The script only needs to be run once per database or when changing embedding model dimensions.

## Multi-Agent Usage

MCP Graph Memory is designed for **multi-agent systems** where multiple agents need to:
- Share knowledge while maintaining isolation
- Build on each other's discoveries
- Access long-term memory across sessions

### Example: Multi-Agent Setup

Use `owner_id` to isolate knowledge between agents/tenants. For example:

- Agent A writes to `owner_id="team:shared"`
- Agent B searches within `owner_id="team:shared"` (shared) or `owner_id="agent:codegen"` (isolated)

### Owner Isolation

Use `owner_id` to:
- **Isolate agents**: Each agent/team has its own `owner_id`
- **Share knowledge**: Use the same `owner_id` for shared knowledge base
- **Cross-reference**: Query across owners when needed (with proper permissions)

All MCP tools support `owner_id` parameter (defaults to `"default"`).

See [`docs/use-cases.md`](docs/use-cases.md) for comprehensive multi-agent usage guide.

## Development

```bash
pytest
```

## Smoke Test (Quick Verification)

Quick test without heavy ML dependencies to verify basic functionality:

### Prerequisites

  ```bash
  # Create a fact
  curl -X POST http://127.0.0.1:8000/mcp/tools/create_node \
    -H "Content-Type: application/json" \
    -d '{"text": "Python is a programming language", "source": "test", "node_type": "Fact"}'

  # Search facts
  curl -X POST http://127.0.0.1:8000/mcp/tools/search \
    -H "Content-Type: application/json" \
    -d '{"query": "Python", "limit": 5}'

  # Get stats
  curl -X POST http://127.0.0.1:8000/mcp/tools/get_stats \
    -H "Content-Type: application/json" \
    -d '{}'

  # Working with Triplets
  curl -X POST http://127.0.0.1:8000/mcp/tools/create_triplet \
    -H "Content-Type: application/json" \
    -d '{
      "subject": "Elon Musk",
      "predicate": "FOUNDED",
      "object_value": "SpaceX",
      "metadata": {"year": 2002}
    }'

  curl -X POST http://127.0.0.1:8000/mcp/tools/search_triplets \
    -H "Content-Type: application/json" \
    -d '{
      "subject": "Elon Musk",
      "limit": 10
    }'
  ```

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
See [`comparison.md`](comparison.md) for detailed comparison with alternatives.

> **Note:** Some test code was generated with LLM assistance and may require further review and refinement.
