# Comparison

Closest products: [Mem0](https://docs.mem0.ai/) and [Graphiti](https://github.com/getzep/graphiti) (open source, from Zep). Sources below, 11 October 2026.

Graph Memory MCP stores the sentence an agent wrote. Mem0 extracts memories from a conversation. Graphiti turns episodes into a temporal graph and invalidates edges that stopped being true. Graphiti's quick start runs on FalkorDB. The database is not the difference.


|                      | Graph Memory MCP                                                  | Mem0                                                                                                                    | Graphiti                                                              |
| -------------------- | ----------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| Unit                 | Fact, entity, relation                                            | Extracted memory                                                                                                        | Episode, then entities and edges                                      |
| Who chooses the text | The agent, in `create_node`                                       | Extraction model on `memory.add`                                                                                        | Extraction model on episode ingest                                    |
| Transcript in        | No                                                                | Yes                                                                                                                     | Yes                                                                   |
| Near-duplicate write | Refused (`memory_duplicate`)                                      | Model may merge, rewrite, or drop                                                                                       | New edges. The written sentence is provenance                         |
| A fact changed       | `mark_outdated` and a new fact, or an explicit `CONTRADICTS` edge | Extraction updates or deletes the memory. Edit history is separate                                                      | Old edge gets `invalid_at` and stays queryable by time                |
| Expiry               | `ttl_days`. Default search hides it until `include_ttl=true`      | None                                                                                                                    | `valid_at` / `invalid_at`: when the fact was true                     |
| Scope                | `owner_id`, one graph each                                        | `user_id`, `agent_id`, `run_id` in one store                                                                            | `group_id`                                                            |
| Task start           | `get_brief`: `about` anchor and recent facts without TTL          | Search                                                                                                                  | Search                                                                |
| Empty query          | Empty result                                                      | Whatever extraction stored from the chat                                                                                | No fact if none was extracted                                         |
| Model on write       | Embeddings only                                                   | LLM on every `add`. More calls when graph memory is on                                                                  | Several LLM calls per episode. JSON must match a schema               |
| Graph                | FalkorDB or ArcadeDB. Search order is cosine, identifier match, and recency | Optional (Neo4j, Memgraph, Neptune, Kuzu, Apache AGE). Adds a `relations` list and does not reorder vector hits         | FalkorDB, Neo4j, and others. Search is vector, keyword, and graph     |
| Where it runs        | Local MCP server                                                  | Python library locally (OpenAI or Ollama, local Qdrant by default). Official MCP is hosted and stores in a Mem0 account | Library and MCP server. Small local models often fail the JSON schema |




## Sources

- Mem0 graph memory: [v1.0.10](https://github.com/mem0ai/mem0/blob/v1.0.10/docs/open-source/features/graph-memory.mdx). OSS overview: [overview](https://github.com/mem0ai/mem0/blob/db15d5c6/docs/open-source/overview.mdx). Hosted MCP: [Mem0 MCP](https://docs.mem0.ai/platform/mem0-mcp).
- Graphiti: [repository](https://github.com/getzep/graphiti). MCP: [mcp_server/README.md](https://github.com/getzep/graphiti/blob/main/mcp_server/README.md).

