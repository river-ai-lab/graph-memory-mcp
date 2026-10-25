# Demo Assets

These GIFs are recorded from a real MCP client session against a live Graph Memory MCP server. Each one starts at a shell prompt, types `uv run python assets/demo/generate_demo.py --scenario <name>`, and runs that command. The client connects to `http://127.0.0.1:8000/mcp`, prints the server name and version from `initialize`, prints the tool count from `list_tools`, then shows every tool call as `→ name {arguments}` and a trimmed excerpt of the JSON response as `← {...}`. Arguments omit `owner_id`. Ids in the excerpt are prefixes of the ids the server returned. Similarity scores are the live scores, rounded to three decimals.

The server process is already listening. The GIF notes `uv run graph-memory-mcp --host 127.0.0.1 --port 8000` instead of typing a server command that does not run.

`record.sh` starts ArcadeDB, starts the server, and records every scenario with asciinema and agg (monokai, JetBrains Mono). `session.sh` is the prompt the recorder types.

The README uses the short GIF. The 13-step take is `demo_dense.gif`. Three shorter GIFs are for a landing page. They share one seeded API-gateway story (same owner): Component X marked outdated, Component Y linked to the API Gateway Service, and two rate-limit facts with a CONTRADICTS edge the agent created. The server does not detect contradictions.

## Recording

**One command** (Linux or macOS, Docker installed):

```bash
./assets/demo/record.sh
```

Record a single scenario with `./assets/demo/record.sh sparse` (also `dense`, `contradictions`, `lifecycle`, `retrieval`).

**What it does**:

1. Checks prerequisites (uv, docker, asciinema, agg) — prints exact install commands if missing
2. Starts ArcadeDB via `docker compose up -d arcadedb` and waits until healthy
3. Installs Python dependencies with `uv sync`
4. Starts `graph-memory-mcp` on `127.0.0.1:8000` when that port is free, and waits until `/admin/health` responds. The first start loads the local embedding model; that wait is not part of the GIF
5. Warms indexes with `--prepare`
6. For each scenario, resets owner `demo_team`. The three landing-page scenarios then run `--scenario seed` (not recorded) so they share one dataset
7. Records `session.sh <name>` with asciinema. That script types and runs `generate_demo.py --scenario <name>`. The client calls the live MCP server and exits non-zero when a check fails. Sparse must land at 20–25 s. Each landing-page GIF must land at 10–15 s
8. Converts with agg (monokai, JetBrains Mono, large font). `gifsicle` optimizes the GIF when it is installed
9. Removes the temporary cast and refuses a GIF at or over 2 MB

Re-record with `./assets/demo/record.sh`. Stop a server this script started by killing the pid in `/tmp/graph-memory-demo-server.pid`.

## Scenarios

```bash
uv run python assets/demo/generate_demo.py --scenario sparse
```

`--prepare` warms the model. `--scenario seed` loads the shared story and prints nothing on the terminal.

### sparse — `demo.gif` (README, about 20–25 s)

1. Save the decision: API gateway uses Component X
2. Link decision → RELATED_TO → API Gateway Service
3. Save Component Y and mark Component X outdated
4. Search returns the current decision
5. Near-duplicate of Component Y is refused

### dense — `demo_dense.gif`

The long take:

1. Alice creates decision: API gateway uses Component X
2. Create service node: API Gateway Service
3. Link decision → RELATED_TO → API Gateway Service
4. Write-back after search miss: search for staging DB port at similarity 0.80 (0 results) → agent finds answer in config → write back → search again finds it
5. Get context: traverse the graph to find the related decision
6. Bob creates new decision: migrated to Component Y
7. Mark old decision outdated
8. Link new → FOLLOWS_FROM → old (new decision follows from old context)
9. Search excludes outdated facts by default
10. Create two contradicting rate limit facts (1000 vs 500 req/min)
11. Agent creates CONTRADICTS edge between them (server does not auto-detect contradictions)
12. Search returns the contradiction pair in `contradiction_pairs`
13. Write-time dedup: attempt near-duplicate, server refuses with similarity score

### contradictions — `demo_contradictions.gif`

Search for the rate limit. Both facts come back with the CONTRADICTS pair. The title says the agent marked that edge. The server does not detect it.

### lifecycle — `demo_lifecycle.gif`

Search for the gateway component returns Component Y and leaves Component X out because it is outdated. A near-duplicate of Component Y is refused at write time.

### retrieval — `demo_retrieval.gif`

Search for the gateway component, then `get_context` on that decision shows the API Gateway Service.

**Relation types**: Uses allowed types from `RELATION_ALLOWED_TYPES` config (RELATED_TO, FOLLOWS_FROM, CONTRADICTS). Custom types can be added via env config.

**Data persistence**: Demo data persists in the Docker volume `arcade-data`. To fully clean: `docker compose down -v`

## Files

- `record.sh`: Records every GIF (or one scenario name)
- `session.sh`: Shell prompt that types the client command, then runs it
- `generate_demo.py`: MCP client, scenarios, the shared seed, and checks
- `demo.gif`: Sparse README recording
- `demo_dense.gif`: 13-step recording
- `demo_contradictions.gif`, `demo_lifecycle.gif`, `demo_retrieval.gif`: Landing-page clips

## Prerequisites

- **uv**: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Docker**: https://docs.docker.com/get-docker/
- **asciinema**: `brew install asciinema` (macOS) or `pip install asciinema` (Linux)
- **agg**: `brew install agg` (macOS) or `cargo install --git https://github.com/asciinema/agg` (Linux)
- **gifsicle** (optional, keeps the GIF small): `brew install gifsicle` or `apt install gifsicle`
