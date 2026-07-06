# Comparison with other MCP memory / graph projects

The table below compares **MCP Graph Memory** (this repo) with common alternatives in the MCP ecosystem.

Legend:
- **✅** built-in / first-class
- **🟡** possible but not the primary design
- **❌** not provided

## Positioning in one line

**Code maps → [Graphify](https://graphify.net/); agent memory → Graph Memory MCP.**

Graphify builds a **static map of a repository** (AST + docs) so coding assistants query structure instead of grepping files. Graph Memory MCP stores **living facts and relations** that agents write during work — decisions, root causes, shared lab knowledge — across sessions with governance (versioning, dedup, `owner_id`).

They complement each other; Graphify can even push extracted graphs to FalkorDB, while this server holds operational agent memory.

## High-level comparison

| Project | Storage model | Graph model | Semantic search | Temporal / episodic | Ops features (status/version/dedup) | Deployment footprint | Our advantage | Our disadvantage |
|---|---|---:|---:|---:|---:|---|---|---|
| **MCP Graph Memory (this repo)** | FalkorDB graph + embeddings | Facts + Entity edges (triplets) | ✅ (Fact/Entity embeddings, vector index) | 🟡 (timestamps/status; no explicit episodic model) | ✅ (status, change history, dedup jobs, aliasing) | Medium (FalkorDB + optional embeddings deps) | Tight coupling of **facts + graph + ops** in one server; **`recall_context`** hybrid recall; practical “agent-ready” tools | Less mature ecosystem for graph analytics vs Neo4j; embeddings require extra deps |
| [Graphify](https://github.com/safishamsi/graphify) | NetworkX snapshot → optional FalkorDB/Neo4j push | Code/docs AST + LLM-extracted concepts | 🟡 (query via graph topology + report; not vector memory) | ❌ (rebuild on commit/`--update`) | ❌ (no fact lifecycle) | Low–Medium (CLI/skill; optional DB push) | Best-in-class **repo code map**; 70× token savings on codebase questions; multi-modal ingestion | Not agent **write memory**; snapshot not shared decisions; no multi-tenant `owner_id` governance |
| Graphiti (Zep) | KG framework (often Neo4j/Postgres) | Rich KG w/ episodes/entities | ✅ | ✅ | ✅ (strong focus on production memory) | **High** (requires Temporal, Postgres/Neo4j, LLM extraction pipeline). Cloud is **Paid**. | Simpler, smaller codebase; **Free** (MIT); easier to add **custom business logic** (Python handlers) | Graphiti is stronger in **episodic/temporal memory** and "magic" extraction from chat logs |
| Neo4j `mcp-neo4j-memory` | Neo4j | Strong property graph | ✅ (depending on setup) | 🟡 | 🟡 | Medium–High (Neo4j, Aura options) | Lightweight, OSS-friendly FalkorDB stack | Neo4j ecosystem is stronger in tooling and analytics; Cypher + algorithms are very mature |
| FalkorDB-MCPServer (official) | FalkorDB | Graph DB access (generic) | 🟡 | ❌ | ❌ | Low–Medium | We provide **opinionated memory primitives** (facts, recall, context, dedup) | Generic DB MCP is more flexible for arbitrary graph apps |
| Qdrant MCP | Qdrant vector DB | ❌ | ✅ | ❌ | 🟡 | Medium | We provide **graph context** and explicit relations | Qdrant is often simpler/faster to operate for pure vector memory |
| Chroma MCP | Chroma vector DB | ❌ | ✅ | ❌ | 🟡 | Low–Medium | Graph features (triplets, subgraphs) | Chroma is easiest for local “just a vector DB” use cases |
| Weaviate MCP | Weaviate | ❌ (graph-like schema only) | ✅ (hybrid) | ❌ | 🟡 | Medium–High | More explicit KG primitives | Weaviate has strong hybrid search and production features |

## Notes on where we win / lose

- **We win when** you need an **agent-oriented memory API** (remember/recall/context/triplets) plus operational controls (status, dedup, archival). Primary recall: **`search` → `get_context` → `get_trace`**; optional **`recall_context`** shortcut on small graphs.
- **We lose when** you need **deep graph analytics** (community detection, PageRank, etc.), a **full episodic/temporal** memory framework out of the box, or a **codebase map from source files** (use Graphify for that).
- **Use both when** agents need repo structure (Graphify) and durable cross-session facts (Graph Memory MCP).
