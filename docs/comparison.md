# Comparison

Mem0 remembers facts. Graph Memory keeps them current.

Closest products: [Mem0](https://docs.mem0.ai/) and [Graphiti](https://github.com/getzep/graphiti) (open source, from Zep). Mem0 checked 15 October 2026. Graphiti sources accessed 11 October 2026.

- **Real graph you can traverse, in open source. Not a hidden ranking signal.** Mem0 OSS has no graph (removed in v3). The Platform graph only changes search order, and `relations` is not returned. Here the agent walks the edges and sees what is linked, and why.
- **Outdated is marked.** Mem0 keeps the old fact and the new one and ranks the new one higher, so contradictions accumulate. `mark_outdated`, an explicit `CONTRADICTS` edge, and version snapshots say what is current, what it replaced, and with what.
- **Near-duplicates are refused at write, without an LLM.** Mem0 skips exact copies by hash. Near-copies are stored, and `infer=False` stores exact copies too. This server refuses a near-paraphrase at `create_node` (`memory_duplicate`). The write computes embeddings only.

Each `owner_id` is its own graph, on FalkorDB or in its own ArcadeDB database. Mem0 keeps every `user_id`, `agent_id`, `run_id`, and `app_id` in one store.

**Design choice:** Graph Memory MCP stores the text the agent wrote. Mem0 extracts memories from a conversation with an LLM (by default; `infer=False` stores raw messages). Graphiti turns episodes into a temporal graph and invalidates edges that stopped being true. The difference is not the database — Graphiti's MCP server defaults to FalkorDB, same as this project. The difference is who chooses the text and whether an LLM rewrites it.

## Where the difference shows

| | Graph Memory MCP | Mem0 (as of Oct 2026) | Graphiti |
| --- | --- | --- | --- |
| Graph | FalkorDB or ArcadeDB. Edges are readable (`get_context`, `get_trace`). Search rank is cosine, identifier match, and recency. | OSS: no graph (removed in v3); an entity collection only boosts rank. Platform: built-in graph used for ranking only, `relations` not returned. | FalkorDB, Neo4j, and others. Search: vector + keyword + graph |
| A fact changed | `mark_outdated` and a new fact, an explicit `CONTRADICTS` edge, or a version snapshot. Default search hides outdated facts. | Add-only. The old and new facts both stay, and search ranks the newer one higher. There is no outdated mark. | Old edge gets `invalid_at` and stays queryable by time |
| Near-duplicate write | Refused at write (`memory_duplicate`). Embeddings only, no LLM. | Exact text is skipped by hash. Near-duplicates are stored. `infer=False` stores exact duplicates too. | New edges. The written sentence is provenance |

## Reference

| | Graph Memory MCP | Mem0 (as of Oct 2026) | Graphiti |
| --- | --- | --- | --- |
| Unit | Fact, entity, relation | Extracted memory | Episode, then entities and edges |
| Who chooses the text | The agent, in `create_node` | Extraction model on `add` (default `infer=True`; `infer=False` stores raw messages, one LLM call skipped) | Extraction model on episode ingest |
| Transcript in | No | Yes | Yes |
| Expiry | `ttl_days`. Default search hides it until `include_ttl=true` | `expiration_date` (YYYY-MM-DD). Hidden from search after the date. `show_expired` includes them. Fetch by id still returns them. | `valid_at` / `invalid_at`: when the fact was true |
| Scope | `owner_id`, one graph each | `user_id`, `agent_id`, `run_id`, `app_id` in one store | `group_id` |
| Task start | `get_brief`: `about` anchor and recent facts without TTL | Search | Search |
| Model on write | Embeddings only | One LLM call per `add` by default (extraction); `infer=False` skips it, only embeddings | Several LLM calls per episode; requires reliable structured output |
| Where it runs | Local MCP server | Python library locally (OpenAI or Ollama, local Qdrant by default). Platform also offers a managed service. The `mem0ai` package is 2.2.x; v3 is the algorithm and API. OSS search is vector-only without `mem0ai[nlp]`. Default Qdrant also needs `fastembed` for BM25. | Library and MCP server; requires a model with reliable structured output (documented) |




## When to choose something else

- **Mem0**: You want automatic extraction from chat transcripts, or you prefer a managed service with a dashboard.
- **Graphiti / Zep**: You need bi-temporal history — queryable "what was true at time T" with `valid_at` / `invalid_at` windows.
- **Letta**: You want an agent runtime and memory in one integrated system (MemFS, dreaming, shared memory repositories).
- **Cognee**: You want to ingest and turn Slack, Notion, or Google Drive data into a knowledge graph.
- **Reference MCP memory server**: Single local user, a JSON file is enough, no database needed.

## Other projects

- **[Letta](https://docs.letta.com/)** (f.k.a. MemGPT) — stateful-agent framework with Git-backed MemFS memory (agents edit Markdown files in their own repo), memory blocks (persistent in-context sections), and dreaming (background subagents consolidate conversations into memory).
- **[Cognee](https://docs.cognee.ai/)** — knowledge-graph memory from Slack, Notion, Google Drive, GitHub, and other data sources; SDKs and Cloud UI with per-channel/folder ingestion.
- **[Supermemory](https://supermemory.ai/)** — memory API for agents; reports top scores on LongMemEval, LoCoMo, and ConvoMem (self-reported). Open-source SDKs and MCP server, proprietary extraction/search engine.
- **[@modelcontextprotocol/server-memory](https://github.com/modelcontextprotocol/servers/tree/main/src/memory)** — reference MCP memory server; local knowledge graph stored in `memory.jsonl`; `create_entities`, `create_relations`, `search_nodes`.
- **[basic-memory](https://github.com/basicmachines-co/basic-memory)** — local MCP server for Markdown-based knowledge graphs; `write_note`, `search_notes`, `build_context`, `memory://` URLs.
- **[Neo4j memory MCP](https://github.com/neo4j-contrib/mcp-neo4j/tree/main/servers/mcp-neo4j-memory)** — MCP server backed by Neo4j; entity, relation, observation, and search tools.

## What Graph Memory MCP does not do (yet)

- No transcript ingestion — the agent writes the fact explicitly with `create_node`.
- No bi-temporal edges — facts are `mark_outdated` or `CONTRADICTS`, not `valid_at` / `invalid_at` time windows.

## Sources

- Mem0, checked 15 October 2026. Package `mem0ai` 2.2.1; v3 is the algorithm and API. [OSS v2 to v3](https://docs.mem0.ai/migration/oss-v2-to-v3), [Platform v2 to v3](https://docs.mem0.ai/migration/platform-v2-to-v3), [releases](https://github.com/mem0ai/mem0/releases), [Add Memory](https://docs.mem0.ai/core-concepts/memory-operations/add), [Memory Expiration](https://docs.mem0.ai/platform/features/memory-expiration), [Platform vs OSS](https://docs.mem0.ai/platform/platform-vs-oss).
- Graphiti: [repository](https://github.com/getzep/graphiti), [MCP server README](https://github.com/getzep/graphiti/blob/main/mcp_server/README.md). Accessed 11 October 2026.
