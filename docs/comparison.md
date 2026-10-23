# Comparison

This document compares Graph Memory MCP against current versions of similar agent memory systems as of October 2026. Sources are cited with access dates.

## Summary

| System | Self-hosted | LLM on server for writes | Graph exposed/traversable by agent | Explicit outdating of facts | Write-time dedup | Per-owner isolation | Compact recall | License |
|--------|-------------|--------------------------|-------------------------------------|------------------------------|------------------|---------------------|----------------|---------|
| **Graph Memory MCP** | ✅ | ❌ | ✅ | ✅ (`mark_outdated`) | ✅ (embeddings, 0.92) | ✅ (physical) | ✅ (token budget) | MIT |
| **Mem0 OSS v3** | ✅ | Optional (default on) | ❌ (removed) | ❌ | Partial (exact hash only) | Logical (`user_id`) | — | Apache 2.0 |
| **Mem0 Platform** | ❌ (managed) | Optional (default on) | Partial (ranking only, not exposed) | ❌ | Partial (exact hash only) | Logical | — | Proprietary |
| **Graphiti** | ✅ | ✅ (extraction) | ✅ | ✅ (`invalid_at`) | ✅ (LLM-based) | Logical (`group_id`) | — | Apache 2.0 |
| **Letta** | ✅ | — | ❌ (memory blocks) | — | — | — | — | MIT |
| **Cognee** | ✅ | ✅ (extraction) | ✅ | — | — | — | — | Apache 2.0 |
| **Supermemory** | ✅ | — | ✅ (embedded graph) | — | — | — | — | MIT |
| **agentmemory** | ✅ (SQLite) | ❌ (local embeddings) | Partial (ranking stage) | — | — | — | — | — |
| **TencentDB** | ✅ (SQLite) | ✅ (distillation) | ✅ (Code-Graph) | — | — | — | — | — |
| **tigerless** | ✅ (Markdown) | — | ❌ | — | — | — | — | — |
| **basic-memory** | ✅ (Markdown) | — | ✅ (Markdown graph) | — | — | — | — | MIT |
| **@mcp/server-memory** | ✅ (JSONL) | ❌ | ✅ (entities/relations) | ❌ | ❌ | — | — | MIT |

Details and sources for each cell are in the sections below.

## Where Graph Memory is stronger

- **Traversable graph in open source**: agents read edges with `get_context` and `get_trace`. Mem0 OSS has no graph (removed in v3). Mem0 Platform has a built-in graph used for ranking, but the `relations` field is not returned. File-based memories (tigerless) have no graph; agentmemory uses its graph only for ranking.
- **Current facts win**: `mark_outdated` hides superseded facts from default search. `get_node(as_of)` supports time-point queries when versioning is enabled. Search by time range (`as_of` for `search`) is not yet implemented. Mem0 keeps old and new facts and ranks the newer one higher, so contradictions accumulate. Vector-only systems have no outdated marking.
- **Contradictions surfaced**: `CONTRADICTS` edges appear in `contradiction_pairs` on search results. Other systems do not explicitly track contradictions as a relationship type (Graphiti tracks validity windows, not contradictions).
- **Write-time deduplication without LLM**: near-duplicates refused at insert using embeddings only (threshold 0.92), no extraction cost, deterministic and offline. Mem0 skips exact text by hash but stores near-duplicates. Graphiti and Cognee create new edges from LLM extraction. No system in this comparison runs an LLM call at write time solely for deduplication.
- **Physical per-owner isolation**: each `owner_id` is its own ArcadeDB database or FalkorDB graph, no query-time filtering risks. Mem0 uses logical filtering with `user_id`, `agent_id`, `run_id`, `app_id` in one store. Graphiti uses `group_id`. File-based memories (tigerless, basic-memory) use directories per owner.
- **Token-budgeted compact search**: `search(..., compact=true)` returns snippets under a configurable budget (default 800 tokens). We are unaware of another system in this comparison offering token-budgeted compaction, but this is not comprehensively verified.
- **Server-side over HTTP MCP**: multiple clients (Claude Desktop, Cursor, custom tools) share one memory store without embedding the database. File-based memories require the client to run locally. Managed platforms (Mem0 Platform, Zep) are server-side but proprietary.
- **Self-hosted by design**: runs entirely on your infrastructure (Docker + FalkorDB/ArcadeDB), data never leaves it, embeddings computed locally (ONNX Runtime by default), no external API keys or third-party calls required. Contrast: Mem0 graph features only in Platform; Zep is a managed service (with a BYOC option); self-hosting means running Graphiti plus your own graph database.

**Design principle**: The agent using the memory already knows what to write and how to structure it. The server does not run its own LLM to extract or rewrite facts; it enforces memory hygiene (dedup on write, outdated facts, contradictions, versions, isolation, token budget). Benefits: predictable, cheap, no hidden model calls, no double extraction. Tradeoff: if you want automatic extraction from raw chat transcripts, LLM-extraction systems (Mem0, Graphiti, Cognee) fit better.

## Detailed comparison

### Mem0

**Checked**: October 15, 2026
**OSS package**: `mem0ai` 2.2.1 (v3 algorithm and API)
**Sources**: [OSS v2 to v3 migration](https://docs.mem0.ai/migration/oss-v2-to-v3), [Platform vs OSS](https://docs.mem0.ai/platform/platform-vs-oss), [Graph Memory (Platform)](https://docs.mem0.ai/platform/features/graph-memory), [GitHub releases](https://github.com/mem0ai/mem0/releases)

**What Mem0 does**: Automatic extraction from conversations (on by default with `infer=True`; `infer=False` stores raw messages). Hybrid retrieval (semantic + BM25 keyword + entity matching). Platform offers Graph Memory (built-in, always-on, used for ranking), Memory Decay, Temporal Reasoning, and Dream (background consolidation). OSS supports local deployment with your own vector store, LLM, and embedder (27 vector stores, 17 LLM providers, 11 embedders documented).

**Graph in OSS**: Removed in v3. The `enable_graph` flag, `graph_store` config, and all external graph drivers (Neo4j, Memgraph, Kuzu, Apache AGE, Neptune) were dropped. OSS still extracts entities and uses them to boost ranking, but there is no queryable graph and no `relations` field returned. Graph memory is a Mem0 Platform exclusive feature; the graph is built-in and connections feed into the ranking score, but the graph itself is not exposed to agents.

**Memory updates**: Add-only in v3 (one LLM call per `add` by default). The old fact and new fact both stay; search ranks the newer one higher. No explicit outdated mark. No `CONTRADICTS` relation. Temporal Reasoning (Platform only) boosts memories whose event dates match a query timestamp.

**Deduplication**: Exact text is skipped by hash. Near-duplicates are stored. `infer=False` also stores exact duplicates (the extraction LLM call is skipped).

**Use Mem0 when**: You want automatic extraction from chat transcripts, or you prefer the managed Platform service with a dashboard and built-in features (Graph Memory, Decay, Temporal Reasoning, Dream).

### Graphiti (Zep)

**Checked**: October 20, 2026
**Version**: v0.31.2 (released October 20, 2026)
**Sources**: [GitHub repository](https://github.com/getzep/graphiti), [MCP server README](https://github.com/getzep/graphiti/blob/main/mcp_server/README.md), [Zep platform page](https://www.getzep.com/platform/graphiti/)

**What Graphiti does**: Open-source temporal knowledge-graph framework for AI agents. Incrementally builds graphs from conversations and data, tracks fact validity over time with `valid_at` / `invalid_at` timestamps (bi-temporal history), preserves provenance to source episodes, and supports hybrid retrieval (semantic + keyword + graph traversal). Agents can query "what was true at time T." Requires a model with reliable structured output (documented requirement).

Graphiti is the framework; Zep is the managed platform built on it. Zep's managed context-graph platform uses its own storage (no third-party graph database required). Graphiti OSS requires a backend (FalkorDB, Neo4j, and others).

**Graph**: Fully traversable in both Graphiti and Zep. Agents read edges and walk the graph.

**Memory updates**: A new fact invalidates the old one by setting `invalid_at`. The old fact stays queryable by time. This is different from Graph Memory MCP's `mark_outdated` (which hides the fact from default search) and different from Mem0's add-only approach (which keeps both facts and ranks by recency).

**Deduplication**: Graphiti deduplicates paraphrased facts at write time via LLM call (dedupe_edges prompt). Graph Memory MCP deduplicates with embeddings only (no LLM call).

**Use Graphiti when**: You need bi-temporal history (queryable "what was true at time T") and you are comfortable with the extraction pipeline's LLM calls. Use Zep Platform when you want Zep's managed context-graph platform with pre-configured retrieval, sub-200ms performance, and enterprise features.

### Letta (formerly MemGPT)

**Checked**: October 20, 2026
**Sources**: [GitHub repository](https://github.com/letta-ai/letta-code) (main codebase; letta-ai/letta is retired V1 server), [Memory Blocks blog post](https://www.letta.com/blog/memory-blocks/), [Why Memory Isn't a Plugin](https://www.letta.com/blog/why-memory-isnt-a-plugin/)

**What Letta does**: Stateful agent runtime (not a pluggable memory service) with persistent, self-managed memory. Memory blocks are editable in-context sections (persona, user, custom knowledge) always visible to the agent. Archival memory and conversation search are retrieved on-demand via tools. Shared memory blocks let multiple agents collaborate on the same knowledge.

**Not a graph memory system**: Letta is an agent harness with built-in memory, not a standalone memory layer. Memory is managed by the harness through prompts, tools, and file edits (MemFS), not a queryable graph.

**Memory updates**: Agents edit memory blocks directly or via tools. The harness manages context window and persistence. Background agents consolidate conversations into memory (dreaming).

**Use Letta when**: You want an integrated agent runtime and memory system in one platform, with features like MemFS, memory blocks, and background agent-driven consolidation. Letta is a full framework, not a pluggable MCP memory server.

### Cognee

**Checked**: October 20, 2026
**Version**: v1.6.5 (October 16, 2026)
**Sources**: [GitHub repository](https://github.com/topoteretes/cognee), [Architecture docs](https://docs.cognee.ai/core-concepts/architecture)

**What Cognee does**: Open-source AI memory platform that ingests documents, code, and conversations into a self-hosted knowledge graph (entities and relationships) plus vector and relational stores. Supports multiple retrieval modes: semantic (vector), graph (Cypher), hybrid (vector + graph), temporal, and deterministic code-graph operations. Recent features include Google Drive and Gmail OAuth connectors, keyless workflows (local models, no cloud LLM key required), and chunked visualization streaming for large graphs.

**Graph**: Fully present and queryable. `SearchType.GRAPH_COMPLETION` expands semantic seeds into graph context. `SearchType.CYPHER` and `SearchType.NATURAL_LANGUAGE` query the graph directly. Agents walk relationships.

**Memory updates**: Ingestion pipeline processes new documents. No explicit `mark_outdated` or bi-temporal `valid_at` / `invalid_at`. Updates and contradictions are not explicitly tracked the way Graph Memory MCP or Graphiti do.

**Use Cognee when**: You want to ingest documents and external data sources (Google Drive and Gmail, plus more connectors in cognee-integrations) into a knowledge graph with rich retrieval modes, or you need code-graph operations for architecture analysis and code understanding.

### Supermemory

**Checked**: October 20, 2026
**Sources**: [LongMemEval-S report](https://supermemory.ai/research/longmembench/), [Research page](https://supermemory.ai/research/)

**What Supermemory does**: Memory engine for agents with reported benchmark scores of 97% overall Recall@20 on LongMemEval-S (500 questions, 115k tokens). Reports 100% on knowledge updates and 95%+ on temporal reasoning, single-session, and multi-session categories. Open-source (MIT), self-hostable, embedded graph engine with relations between memories (updates/extends/derives). Cloud and enterprise tiers available.

**Reported benchmark**: 97% overall (GPT-4o judge, Recall@20 with aggregation on LongMemEval-S). Note that benchmark results are not directly comparable unless dataset revision, retrieval settings, judge model, and answering model all match. See their [published methodology](https://supermemory.ai/research/longmembench/) for reproducibility details.

**Graph**: Embedded graph engine with relations between memories (updates/extends/derives).

**Use Supermemory when**: You want a solution with published strong benchmark performance on LongMemEval-S. Note that benchmarks measure retrieval and answering on a specific dataset, not production reliability, permissions, deletion, or cost.

### Other projects

#### rohitg00/agentmemory

**Checked**: October 20, 2026
**Version**: 29.7k stars, created February 2026
**Sources**: [GitHub repository](https://github.com/rohitg00/agentmemory)

Persistent memory for coding agents with automatic hooks, **SQLite storage** backend, hybrid BM25/vector/graph retrieval, and MCP support. **Reports 95.2% R@5 on public LongMemEval-S** (Recall@5 metric). The graph is used in the ranking stage. Local embeddings (all-MiniLM-L6-v2) available, no API key required. Targets coding-agent use cases with reproducer harness for LongMemEval and a custom corpus. Self-reported comparison includes benchmarks against Mem0, Letta, and others.

#### tigerless-labs/agent-memory

**Checked**: October 20, 2026
**Version**: 4.1k stars, created September 1, 2026
**Sources**: [Landing page](https://tigerless.ai/labs/agent-memory)

Long-term memory runtime using plain Markdown as the source of truth, local ranked retrieval, and session-boundary distillation. Files remain readable by the agent with `ls` and `grep`. Targets Claude Code, Codex CLI, and Muse Code. Early release (v0.1.0, created Sep 1, 2026).

#### TencentCloud/TencentDB-Agent-Memory

**Checked**: October 20, 2026
**Version**: 29.6k stars, v2.0.2 (October 9, 2026), v2.0.3-beta.1 prerelease, created April 2026
**Sources**: [GitHub repository](https://github.com/TencentCloud/TencentDB-Agent-Memory)

Team-level memory hub with four asset types: Chat Memory (L0-L3 distillation), Skills, LLM-Wiki, and Code-Graph. Memory is shared across agents and frameworks through a proxy and management panel. Targets team memory accumulation and handoff between agents. Includes governance and review workflows. SQLite + sqlite-vec storage by default, Markdown files for upper layers.

#### @modelcontextprotocol/server-memory

**Checked**: October 19, 2026
**Version**: 2.0.0
**Sources**: [npm package](https://www.npmjs.com/package/@modelcontextprotocol/server-memory), [GitHub README](https://github.com/modelcontextprotocol/servers/blob/main/src/memory/README.md)

Official MCP reference server for knowledge-graph memory. Persists entities, relations, and observations locally as JSONL. Nine tools: `create_entities`, `create_relations`, `add_observations`, `delete_entities`, `delete_observations`, `delete_relations`, `read_graph`, `search_nodes`, `open_nodes`. One subscribable resource (`memory://knowledge-graph`). No deduplication, no versioning, no TTL, no outdated marking. Suitable for single-user local storage where a JSON file is sufficient.

#### basic-memory

**Sources**: [GitHub repository](https://github.com/basicmachines-co/basic-memory)

Local MCP server for Markdown-based knowledge graphs. Tools: `write_note`, `search_notes`, `build_context`, `memory://` URLs. Markdown files as source of truth plus a local search index (Postgres option available).

#### Neo4j memory MCP

**Sources**: [GitHub repository](https://github.com/neo4j-contrib/mcp-neo4j/tree/main/servers/mcp-neo4j-memory)

MCP server backed by Neo4j. Entity, relation, observation, and search tools. Requires a running Neo4j instance.

## When to choose something else

- **Mem0 Platform**: You want a managed service with automatic extraction, built-in Graph Memory, Decay, Temporal Reasoning, Dream, and a dashboard. You are willing to trade graph traversal and explicit contradiction marking for convenience.

- **Graphiti / Zep**: You need bi-temporal history with queryable `valid_at` / `invalid_at` windows, or you want Zep's managed context-graph platform with enterprise features (SLAs, support, security).

- **Letta**: You want an integrated agent runtime and memory system with memory blocks, MemFS (git-backed memory), sleep-time compute (background agents), and programmatic context management. This is a full framework, not a memory plugin.

- **Cognee**: You want to ingest and index external data sources (Google Drive and Gmail, plus more connectors in cognee-integrations) into a knowledge graph, or you need code-graph operations for architecture analysis.

- **@modelcontextprotocol/server-memory**: Single local user, JSONL file is sufficient, no database needed, and you do not need deduplication, versioning, or TTL.

- **rohitg00/agentmemory**: Lightweight personal coding-agent memory with automatic hooks, local embeddings (no API key), and SQLite backend.

- **tigerless-labs/agent-memory**: Inspectable Markdown-backed memory with session distillation for Claude Code and Codex.

- **TencentDB-Agent-Memory**: Team memory hub with governance, review workflows, and shared assets across frameworks.

## Where others are stronger

1. **Automatic extraction**: Mem0 and Graphiti extract facts from conversations by default. Graph Memory MCP requires agents to write facts explicitly with `create_node` or `ingest_knowledge`.

2. **Bi-temporal history**: Graphiti tracks `valid_at` / `invalid_at` and supports "what was true at time T" queries. Graph Memory MCP uses `mark_outdated` and `CONTRADICTS`, which are simpler; point-in-time reads exist only for `get_node(as_of)`, not for `search`.

3. **Install size and dependencies**: Graph Memory MCP requires Python 3.11+, ONNX Runtime, and FalkorDB or ArcadeDB. PyTorch is optional (`uv sync --extra torch`). Mem0 OSS has similar dependencies. Letta and Cognee have heavier installs due to their broader feature sets. @modelcontextprotocol/server-memory is a Node.js package with minimal dependencies.

4. **Managed platform**: Mem0 Platform and Zep offer fully managed services with dashboards, APIs, and enterprise features (SLAs, support, SOC 2, HIPAA, BYOC). Graph Memory MCP is self-hosted only.

5. **Benchmarks**: Supermemory reports 97% on LongMemEval-S (self-reported, GPT-4o judge, Recall@20 with aggregation). rohitg00/agentmemory reports 95.2% R@5 (self-reported). Graph Memory MCP has no published benchmark results. Benchmarks measure retrieval on one dataset; they do not cover production reliability, permissions, deletion, or cost.

6. **UI and tooling**: Zep, Mem0 Platform, and TencentDB-Agent-Memory offer dashboards and management panels. Graph Memory MCP has a local Graph Explorer (read-only web UI) but no admin dashboard.

## What Graph Memory MCP does not do

- **No built-in authentication or authorization** — deploy behind a reverse proxy if needed
- **No automatic transcript ingestion** — agents write facts explicitly
- **No bi-temporal edges** — use `mark_outdated` and `CONTRADICTS`, not `valid_at` / `invalid_at` time windows
- **No managed service** — self-hosted only
- **No LLM-based extraction pipeline** — agents write the text that is stored

## Sources and access dates

- **Mem0**: Checked October 15, 2026. [OSS v2 to v3 migration](https://docs.mem0.ai/migration/oss-v2-to-v3), [Platform vs OSS](https://docs.mem0.ai/platform/platform-vs-oss), [Graph Memory (Platform)](https://docs.mem0.ai/platform/features/graph-memory), [GitHub releases](https://github.com/mem0ai/mem0/releases)
- **Graphiti**: Checked October 20, 2026. [GitHub repository](https://github.com/getzep/graphiti), [v0.31.2 release](https://github.com/getzep/graphiti/releases/tag/v0.31.2)
- **Letta**: Checked October 20, 2026. [GitHub repository](https://github.com/letta-ai/letta-code), [Blog posts](https://www.letta.com/blog/)
- **Cognee**: Checked October 20, 2026. [GitHub repository](https://github.com/topoteretes/cognee), [v1.6.5 release](https://github.com/topoteretes/cognee/releases/tag/v1.6.5)
- **Supermemory**: Checked October 20, 2026. [LongMemEval-S report](https://supermemory.ai/research/longmembench/)
- **Other projects**: Checked October 20, 2026. GitHub repositories and landing pages as linked above.
