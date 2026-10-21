# Examples

Copy `env.example` to `.env`, then run `docker compose up -d arcadedb` to start ArcadeDB (default backend, port 2480). For FalkorDB instead, set `GRAPH_BACKEND=falkordb` in `.env` and run `docker compose up -d falkordb` (port 6379). The first example run downloads the embedding model.

```bash
cp env.example .env
uv sync
docker compose up -d arcadedb  # Or: docker compose up -d falkordb
```

| Mode | Process | Example |
|------|---------|---------|
| In-process Python | none | `embedded_python_usage.py` |
| HTTP server | `examples/run_server.py` or `graph-memory-mcp` | serves `/mcp` |
| HTTP client | server already running | `http_client_usage.py` |
| Client config | server already running | `mcp_servers_config.json` |

`examples/run_server.py` starts the default profile. `--simple` and `--extended` are flags of `graph-memory-mcp`.

```bash
uv run --env-file .env python examples/embedded_python_usage.py
uv run --env-file .env python examples/run_server.py
uv run --env-file .env python examples/http_client_usage.py
uv run graph-memory-mcp --host 127.0.0.1 --port 8000
```

Streamable HTTP is `http://127.0.0.1:8000/mcp`. Tool calls go through the MCP client, not REST paths under `/mcp`.
