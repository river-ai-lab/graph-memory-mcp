# Demo Assets

Demo recording showing graph traversal, decision superseding, and contradictions flagged by the agent with real Graph Memory MCP server output.

## Recording the demo

**One command** (Linux or macOS, Docker installed):

```bash
./assets/demo/record.sh
```

**What it does**:

1. Checks prerequisites (uv, docker, asciinema, agg) — prints exact install commands if missing
2. Starts ArcadeDB via `docker compose up -d arcadedb` and waits until healthy
3. Installs Python dependencies with `uv sync`
4. Starts `graph-memory-mcp` on `127.0.0.1:8000` when that port is free, and waits until `/admin/health` responds. The first start loads the local embedding model; that wait is not part of the GIF
5. Warms indexes with `--prepare`, then deletes owners `demo_warm` and `demo_team` so the take starts empty
6. Records `generate_demo.py` with asciinema (fixed terminal size: 88x26). The script calls the live MCP tools (`create_node`, `create_relation`, `search`, `get_context`, `mark_outdated`)
7. Converts to `demo.gif` with agg (monokai, JetBrains Mono, font-size 22, speed tuned for 15-30s). `gifsicle` optimizes the GIF when it is installed
8. Removes the temporary cast file
9. Prints result path and size

Output: `demo.gif`, embedded near the top of README.md. Keep it under about 3 MB.

Re-record with `./assets/demo/record.sh` from a machine that has Docker. Stop a server this script started by killing the pid in `/tmp/graph-memory-demo-server.pid`.

## Demo scenario

1. Alice creates decision: API gateway uses Component X
2. Link decision → RELATED_TO → API Gateway Service
3. Get context: traverse graph to find related decisions
4. Write-back after search miss: search for staging DB port at similarity 0.80 (0 results) → agent finds answer in config → write back → search again finds it
5. Bob creates new decision: migrated to Component Y
6. Mark old decision outdated
7. Link new → FOLLOWS_FROM → old (new decision follows from old context)
8. Search excludes outdated facts by default
9. Create two contradicting rate limit facts (1000 vs 500 req/min)
10. Agent creates CONTRADICTS edge between them (server does not auto-detect contradictions)
11. Search returns the contradiction pair in `contradiction_pairs`
12. Write-time dedup: attempt near-duplicate, server refuses with similarity score

**Relation types**: Uses allowed types from `RELATION_ALLOWED_TYPES` config (RELATED_TO, FOLLOWS_FROM, CONTRADICTS). Custom types can be added via env config.

**Data persistence**: Demo data persists in the Docker volume `arcade-data`. To fully clean: `docker compose down -v`

## Files

- `record.sh`: One-command recorder (checks deps, starts DB, records, converts, cleans up)
- `generate_demo.py`: Demo scenario with real server API calls and pauses for readability
- `demo.gif`: Generated recording (run record.sh to create)

## Prerequisites

- **uv**: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Docker**: https://docs.docker.com/get-docker/
- **asciinema**: `brew install asciinema` (macOS) or `pip install asciinema` (Linux)
- **agg**: `brew install agg` (macOS) or `cargo install --git https://github.com/asciinema/agg` (Linux)
- **gifsicle** (optional, keeps the GIF small): `brew install gifsicle` or `apt install gifsicle`
