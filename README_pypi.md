# Graph Memory MCP

Self-hosted MCP server for graph-based long-term memory (FalkorDB or ArcadeDB). Agents decide what to write. The server deduplicates on insert, marks outdated facts, surfaces contradictions, and gives each `owner_id` its own graph or database. Embeddings run locally. The server makes no LLM calls.

## Install

```bash
uvx graph-memory-mcp --host 127.0.0.1 --port 8000
```

```bash
pip install graph-memory-mcp
graph-memory-mcp --host 127.0.0.1 --port 8000
```

Streamable HTTP: `http://127.0.0.1:8000/mcp`. The first start downloads the default embedding weights (about 1.1 GB).

## Database

ArcadeDB is the default. The image password is `playwithdata`. The process default for `ARCADE_PASSWORD` is empty, so set it.

```bash
docker run -d --name graph-memory-arcadedb -p 2480:2480 \
  -e JAVA_OPTS="-Darcadedb.server.rootPassword=playwithdata" \
  arcadedata/arcadedb:latest

ARCADE_PASSWORD=playwithdata graph-memory-mcp --host 127.0.0.1 --port 8000
```

FalkorDB:

```bash
docker run -d --name graph-memory-falkordb -p 6379:6379 \
  -e REDIS_ARGS="--requirepass falkordb123" \
  falkordb/falkordb

GRAPH_BACKEND=falkordb FALKORDB_PASSWORD=falkordb123 graph-memory-mcp --host 127.0.0.1 --port 8000
```

The same services are in [docker-compose.yml](https://github.com/river-ai-lab/graph-memory-mcp/blob/main/docker-compose.yml).

## MCP client

```json
{
  "mcpServers": {
    "graph-memory-mcp": {
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

## Documentation

- [README](https://github.com/river-ai-lab/graph-memory-mcp/blob/main/README.md)
- [Configuration](https://github.com/river-ai-lab/graph-memory-mcp/blob/main/docs/configuration.md)
- [API contract](https://github.com/river-ai-lab/graph-memory-mcp/blob/main/docs/features.md)
- [Agent policies](https://github.com/river-ai-lab/graph-memory-mcp/blob/main/docs/memory_policies_for_LLM.md)
- [FAQ](https://github.com/river-ai-lab/graph-memory-mcp/blob/main/docs/memory_faq.md)
- [Comparison](https://github.com/river-ai-lab/graph-memory-mcp/blob/main/docs/comparison.md)

MIT License.
