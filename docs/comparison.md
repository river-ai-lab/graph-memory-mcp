# Comparison

**Code maps → [Graphify](https://graphify.net/); agent memory → this repo.**

| Project | Model | Semantic | Ops (status/dedup) | Footprint | Notes |
|---------|-------|----------|--------------------|-----------|-------|
| **This repo** | FalkorDB graph + embeddings | ✅ | ✅ | Medium | Agent tools + graph-per-owner |
| [Graphify](https://github.com/safishamsi/graphify) | Repo AST/docs snapshot | 🟡 | ❌ | Low–Med | Code map, not write-memory |
| Graphiti (Zep) | Rich KG / episodes | ✅ | ✅ | High (paid cloud) | Stronger episodic extraction |
| Neo4j mcp-memory | Neo4j | ✅ | 🟡 | Med–High | Better analytics ecosystem |
| FalkorDB-MCPServer | Generic graph MCP | 🟡 | ❌ | Low–Med | DB access, not memory API |
| Qdrant / Chroma / Weaviate MCP | Vector DB | ✅ | 🟡 | Low–Med | No first-class graph memory |

**Win:** agent remember/recall/context + lifecycle. **Lose:** deep graph analytics, full episodic frameworks, pure-vector simplicity.
