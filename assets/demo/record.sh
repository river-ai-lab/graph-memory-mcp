#!/bin/bash
#
# Record demo GIF with real ArcadeDB server.
# Checks prerequisites, starts database, runs demo, generates GIF, cleans up.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEMO_GIF="$SCRIPT_DIR/demo.gif"
DEMO_CAST="$SCRIPT_DIR/demo.cast"
SERVER_PORT="${GRAPH_MEMORY_PORT:-8000}"
STARTED_SERVER=0
SERVER_LOG="${TMPDIR:-/tmp}/graph-memory-demo-server.log"
SERVER_PID_FILE="${TMPDIR:-/tmp}/graph-memory-demo-server.pid"

echo "=== Graph Memory Demo Recorder ==="
echo ""

# 1. Check prerequisites
echo "[1/7] Checking prerequisites..."

# Check uv
if ! command -v uv &> /dev/null; then
    echo "❌ uv not found"
    echo "Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi
echo "✓ uv found"

# Check docker
if ! command -v docker &> /dev/null; then
    echo "❌ docker not found"
    echo "Install: https://docs.docker.com/get-docker/"
    exit 1
fi
echo "✓ docker found"

# Check docker compose
if ! docker compose version &> /dev/null; then
    echo "❌ docker compose not found"
    echo "Install: https://docs.docker.com/compose/install/"
    exit 1
fi
echo "✓ docker compose found"

# Check asciinema
if ! command -v asciinema &> /dev/null; then
    echo "❌ asciinema not found"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "Install: brew install asciinema"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        echo "Install: pip install asciinema  # or: apt install asciinema / dnf install asciinema"
    fi
    exit 1
fi
echo "✓ asciinema found"

# Check agg
if ! command -v agg &> /dev/null; then
    echo "❌ agg not found"
    echo "Install:"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "  brew install agg"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        echo "  cargo install --git https://github.com/asciinema/agg"
        echo "  # or download binary from https://github.com/asciinema/agg/releases"
    fi
    exit 1
fi
echo "✓ agg found"

echo ""

# 2. Start ArcadeDB and the MCP server
echo "[2/7] Starting ArcadeDB and the MCP server..."
cd "$PROJECT_ROOT"

# Ensure .env exists
if [ ! -f .env ]; then
    cp env.example .env
    echo "Created .env from env.example"
fi

# Start ArcadeDB only (or both, compose starts both)
docker compose up -d arcadedb

# Wait for ArcadeDB to be healthy (max 30s)
echo "Waiting for ArcadeDB to be ready..."
TIMEOUT=30
ELAPSED=0
while [ $ELAPSED -lt $TIMEOUT ]; do
    # Check Docker healthcheck first
    if docker compose ps arcadedb 2>/dev/null | grep -q "healthy"; then
        echo "✓ ArcadeDB is healthy (Docker healthcheck)"
        break
    fi
    # Fallback: HTTP readiness check (no auth on /ready endpoint)
    if curl -sf http://localhost:2480/api/v1/ready >/dev/null 2>&1; then
        echo "✓ ArcadeDB is ready (HTTP check)"
        break
    fi
    sleep 1
    ELAPSED=$((ELAPSED + 1))
done

if [ $ELAPSED -ge $TIMEOUT ]; then
    echo "❌ ArcadeDB did not become ready in ${TIMEOUT}s"
    docker compose logs arcadedb
    exit 1
fi

# Additional wait for API to be fully ready
sleep 2

echo ""

# 3. Install dependencies (before the server process, so uv run can start it)
echo "[3/7] Installing Python dependencies..."
cd "$PROJECT_ROOT"
uv sync --quiet
echo "✓ Dependencies installed"
echo ""

start_server() {
    if curl -sf "http://127.0.0.1:${SERVER_PORT}/admin/health" >/dev/null 2>&1; then
        echo "✓ MCP server already listening on :${SERVER_PORT}"
        return
    fi
    echo "Starting MCP server on 127.0.0.1:${SERVER_PORT}..."
    # Model load is outside the recording. First start downloads the ONNX weights.
    uv run graph-memory-mcp --host 127.0.0.1 --port "$SERVER_PORT" --log-level WARNING \
        >"$SERVER_LOG" 2>&1 &
    echo $! >"$SERVER_PID_FILE"
    STARTED_SERVER=1
    local timeout=240
    local elapsed=0
    while [ "$elapsed" -lt "$timeout" ]; do
        if curl -sf "http://127.0.0.1:${SERVER_PORT}/admin/health" >/dev/null 2>&1; then
            echo "✓ MCP server is ready"
            return
        fi
        if ! kill -0 "$(cat "$SERVER_PID_FILE")" 2>/dev/null; then
            echo "❌ MCP server exited"
            cat "$SERVER_LOG"
            exit 1
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    echo "❌ MCP server did not become ready in ${timeout}s"
    cat "$SERVER_LOG"
    exit 1
}

start_server

echo "Warming embeddings and resetting demo owner..."
uv run python "$SCRIPT_DIR/generate_demo.py" --prepare
curl -sf -X DELETE "http://127.0.0.1:${SERVER_PORT}/admin/owners/demo_warm" >/dev/null || true
curl -sf -X DELETE "http://127.0.0.1:${SERVER_PORT}/admin/owners/demo_team" >/dev/null || true
echo "✓ Server ready, demo owner reset"
echo ""

# 4. Record demo
echo "[4/7] Recording demo (this takes ~20s)..."
cd "$PROJECT_ROOT"

# Fixed terminal size. Short lines stay on one row at a large font.
export COLUMNS=88
export LINES=26

# Record with asciinema (run from project root so .env is found)
asciinema rec "$DEMO_CAST" \
    --overwrite \
    --cols 88 \
    --rows 26 \
    --command "uv run python assets/demo/generate_demo.py" \
    --quiet

echo "✓ Demo recorded to demo.cast"
echo ""

# 5. Convert to GIF
echo "[5/7] Converting to GIF..."
agg "$DEMO_CAST" "$DEMO_GIF" \
    --theme monokai \
    --font-family "JetBrains Mono" \
    --font-size 22 \
    --line-height 1.32 \
    --speed 1.0 \
    --fps-cap 10 \
    --last-frame-duration 2.5

if command -v gifsicle >/dev/null 2>&1; then
    # Lossless optimize. Lossy quantization blurs the monospace text.
    gifsicle -O3 -o "${DEMO_GIF}.opt" "$DEMO_GIF"
    mv "${DEMO_GIF}.opt" "$DEMO_GIF"
fi

echo "✓ GIF created"
echo ""

# 6. Cleanup
echo "[6/7] Cleaning up demo data..."

# The demo creates owner_id="demo_team" and deletes that owner before each take.
# ArcadeDB data lives in the named volume arcade-data.
echo "Note: ArcadeDB data persists in the docker volume arcade-data"
echo "      To clean: docker compose down -v"

# Clean up cast file
rm -f "$DEMO_CAST"
echo "✓ Temporary files removed"
echo ""

# 7. Report
echo "[7/7] Done!"
echo ""
echo "📹 Demo GIF: $DEMO_GIF"

# Get file size
if [[ "$OSTYPE" == "darwin"* ]]; then
    SIZE=$(stat -f%z "$DEMO_GIF")
else
    SIZE=$(stat -c%s "$DEMO_GIF")
fi

# Convert to KB or MB
if [ "$SIZE" -lt 1048576 ]; then
    SIZE_HUMAN="$((SIZE / 1024)) KB"
else
    SIZE_HUMAN="$(awk -v bytes="$SIZE" 'BEGIN { printf "%.1f MB", bytes / 1048576 }')"
fi

echo "📊 Size: $SIZE_HUMAN"
echo ""
echo "Embed in README.md:"
echo '![Demo](assets/demo/demo.gif)'
echo ""
if [ "$STARTED_SERVER" = 1 ]; then
    echo "To stop the server started by this script, kill the pid in $SERVER_PID_FILE"
fi
echo "To stop the database: docker compose down"
echo "To clean data: docker compose down -v"
