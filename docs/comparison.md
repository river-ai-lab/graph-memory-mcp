# Comparison

Closest products: [Mem0](https://docs.mem0.ai/) and [Graphiti](https://github.com/getzep/graphiti) (open source, from Zep). Sources below, accessed 11 October 2026.

**Design choice:** Graph Memory MCP stores the text the agent wrote. Mem0 extracts memories from a conversation with an LLM (by default; `infer=False` stores raw messages). Graphiti turns episodes into a temporal graph and invalidates edges that stopped being true. The difference is not the database — Graphiti's MCP server defaults to FalkorDB, same as this project. The difference is who chooses the text and whether an LLM rewrites it.


|                      | Graph Memory MCP                                                  | Mem0 (v3)                                                                                                                    | Graphiti                                                              |
| -------------------- | ----------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| Unit                 | Fact, entity, relation                                            | Extracted memory                                                                                                        | Episode, then entities and edges                                      |
| Who chooses the text | The agent, in `create_node`                                       | Extraction model on `add` (default `infer=True`; `infer=False` stores raw messages, one LLM call skipped)                                                                                        | Extraction model on episode ingest                                    |
| Transcript in        | No                                                                | Yes                                                                                                                     | Yes                                                                   |
| Near-duplicate write | Refused (`memory_duplicate`)                                      | Add-only; model may add a similar memory (extraction behavior varies)                                                                                       | New edges. The written sentence is provenance                         |
| A fact changed       | `mark_outdated` and a new fact, or an explicit `CONTRADICTS` edge | Add-only (v3); extraction adds new memories, old ones stay unless manually deleted                                                      | Old edge gets `invalid_at` and stays queryable by time                |
| Expiry               | `ttl_days`. Default search hides it until `include_ttl=true`      | `expiration_date` (YYYY-MM-DD; hidden from search after the date, not deleted)                                                                                                                    | `valid_at` / `invalid_at`: when the fact was true                     |
| Scope                | `owner_id`, one graph each                                        | `user_id`, `agent_id`, `run_id` in one store                                                                            | `group_id`                                                            |
| Task start           | `get_brief`: `about` anchor and recent facts without TTL          | Search                                                                                                                  | Search                                                                |
| Model on write       | Embeddings only                                                   | One LLM call per `add` by default (extraction); `infer=False` skips it, only embeddings                                                                  | Several LLM calls per episode; requires reliable structured output               |
| Graph                | FalkorDB or ArcadeDB. Search: cosine + identifier match + recency | Built-in graph (v3); entities extracted and linked natively. Search: semantic (vector) + BM25 + entity signals         | FalkorDB, Neo4j, and others. Search: vector + keyword + graph     |
| Where it runs        | Local MCP server                                                  | Python library locally (OpenAI or Ollama, local Qdrant by default). Platform MCP is hosted, stores in a Mem0 account | Library and MCP server; requires a model with reliable structured output (documented) |




## When to choose something else

- **Mem0**: You want automatic extraction from chat transcripts, or you want a hosted service with a dashboard.
- **Graphiti / Zep**: You need bi-temporal history — queryable "what was true at time T" with `valid_at` / `invalid_at` windows.
- **Letta**: You want an agent runtime and memory in one integrated system (MemFS, dreaming, shared memory repositories).
- **Cognee**: You want to ingest and turn Slack, Notion, or Google Drive data into a knowledge graph.
- **Reference MCP memory server**: Single local user, a JSON file is enough, no database needed.

## Other projects

- **[Letta](https://docs.letta.com/)** (f.k.a. MemGPT) — stateful-agent framework with Git-backed MemFS memory (agents edit Markdown files in their own repo), memory blocks (persistent in-context sections), and dreaming (background subagents consolidate conversations into memory).
- **[Cognee](https://docs.cognee.ai/)** — knowledge-graph memory from Slack, Notion, Google Drive, GitHub, and other data sources; SDKs and Cloud UI with per-channel/folder ingestion.
- **[Supermemory](https://supermemory.ai/)** — hosted memory-as-a-service API for agents; ranks #1 on LongMemEval, LoCoMo, ConvoMem; open-source SDKs and MCP server, proprietary extraction/search engine.
- **[@modelcontextprotocol/server-memory](https://github.com/modelcontextprotocol/servers/tree/main/src/memory)** — reference MCP memory server; local knowledge graph stored in `memory.jsonl`; `create_entities`, `create_relations`, `search_nodes`.
- **[basic-memory](https://github.com/basicmachines-co/basic-memory)** — local MCP server for Markdown-based knowledge graphs; `write_note`, `search_notes`, `build_context`, `memory://` URLs.
- **[Neo4j memory MCP](https://github.com/neo4j-contrib/mcp-neo4j/tree/main/servers/mcp-neo4j-memory)** — MCP server backed by Neo4j; entity, relation, observation, and search tools.

## What Graph Memory MCP does not do (yet)

- No transcript ingestion — the agent writes the fact explicitly with `create_node`.
- No bi-temporal edges — facts are `mark_outdated` or `CONTRADICTS`, not `valid_at` / `invalid_at` time windows.
- No hosted version yet — runs as a local or self-hosted MCP server.

## Sources

- Mem0 (v3): [Add Memory](https://docs.mem0.ai/core-concepts/memory-operations/add), [Memory Expiration](https://docs.mem0.ai/platform/features/memory-expiration), [Platform v2 to v3 migration](https://docs.mem0.ai/migration/platform-v2-to-v3), [OSS v2 to v3 migration](https://docs.mem0.ai/migration/oss-v2-to-v3). Accessed 11 October 2026.
- Graphiti: [repository](https://github.com/getzep/graphiti), [MCP server README](https://github.com/getzep/graphiti/blob/main/mcp_server/README.md). Accessed 11 October 2026.

