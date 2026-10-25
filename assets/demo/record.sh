#!/bin/bash
#
# Record demo GIFs against a running ArcadeDB and Graph Memory MCP server.
# One command records every scenario. Pass a scenario name to record just that one.
#
#   ./assets/demo/record.sh
#   ./assets/demo/record.sh sparse
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SERVER_PORT="${GRAPH_MEMORY_PORT:-8000}"
STARTED_SERVER=0
SERVER_LOG="${TMPDIR:-/tmp}/graph-memory-demo-server.log"
SERVER_PID_FILE="${TMPDIR:-/tmp}/graph-memory-demo-server.pid"
STATUS_FILE="${TMPDIR:-/tmp}/graph-memory-demo-status"
MAX_BYTES=$((2 * 1024 * 1024))

# name gif cols rows font last_frame seed(yes/no)
TAKES=(
  "sparse demo.gif 80 26 22 2.0 no"
  "dense demo_dense.gif 88 26 22 2.5 no"
  "contradictions demo_contradictions.gif 76 14 24 1.2 yes"
  "lifecycle demo_lifecycle.gif 76 16 24 1.2 yes"
  "retrieval demo_retrieval.gif 76 14 24 1.2 yes"
)

ONLY="${1:-all}"

echo "=== Graph Memory Demo Recorder ==="
echo ""

echo "[1/5] Checking prerequisites..."

if ! command -v uv &> /dev/null; then
    echo "❌ uv not found"
    echo "Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi
echo "✓ uv found"

if ! command -v docker &> /dev/null; then
    echo "❌ docker not found"
    echo "Install: https://docs.docker.com/get-docker/"
    exit 1
fi
echo "✓ docker found"

if ! docker compose version &> /dev/null; then
    echo "❌ docker compose not found"
    echo "Install: https://docs.docker.com/compose/install/"
    exit 1
fi
echo "✓ docker compose found"

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

echo "[2/5] Starting ArcadeDB and the MCP server..."
cd "$PROJECT_ROOT"

if [ ! -f .env ]; then
    cp env.example .env
    echo "Created .env from env.example"
fi

docker compose up -d arcadedb

echo "Waiting for ArcadeDB to be ready..."
TIMEOUT=60
ELAPSED=0
while [ "$ELAPSED" -lt "$TIMEOUT" ]; do
    if docker compose ps arcadedb 2>/dev/null | grep -q "healthy"; then
        echo "✓ ArcadeDB is healthy"
        break
    fi
    if curl -sf http://localhost:2480/api/v1/ready >/dev/null 2>&1; then
        echo "✓ ArcadeDB is ready"
        break
    fi
    sleep 1
    ELAPSED=$((ELAPSED + 1))
done

if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
    echo "❌ ArcadeDB did not become ready in ${TIMEOUT}s"
    docker compose logs arcadedb
    exit 1
fi
sleep 2

echo ""
echo "[3/5] Installing Python dependencies..."
uv sync --quiet
echo "✓ Dependencies installed"
echo ""

start_server() {
    if curl -sf "http://127.0.0.1:${SERVER_PORT}/admin/health" >/dev/null 2>&1; then
        echo "✓ MCP server already listening on :${SERVER_PORT}"
        return
    fi
    echo "Starting MCP server on 127.0.0.1:${SERVER_PORT}..."
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

echo "Warming embeddings..."
uv run python "$SCRIPT_DIR/generate_demo.py" --prepare
curl -sf -X DELETE "http://127.0.0.1:${SERVER_PORT}/admin/owners/demo_warm" >/dev/null || true
echo "✓ Server ready"
echo ""

gif_duration() {
    python3 - "$1" <<'PY'
import struct, sys
data = open(sys.argv[1], "rb").read()
total = 0
i = 0
while True:
    j = data.find(b"\x21\xf9\x04", i)
    if j < 0 or j + 8 > len(data):
        break
    total += struct.unpack_from("<H", data, j + 4)[0]
    i = j + 8
print(f"{total / 100:.1f}s")
PY
}

record_one() {
    local name="$1"
    local gif_name="$2"
    local cols="$3"
    local rows="$4"
    local font="$5"
    local last_frame="$6"
    local seeded="$7"
    local gif="$SCRIPT_DIR/$gif_name"
    local cast="$SCRIPT_DIR/${name}.cast"

    echo "--- ${name} ---"
    curl -sf -X DELETE "http://127.0.0.1:${SERVER_PORT}/admin/owners/demo_team" >/dev/null || true
    if [ "$seeded" = "yes" ]; then
        uv run python "$SCRIPT_DIR/generate_demo.py" --scenario seed
    fi

    rm -f "$STATUS_FILE"
    export COLUMNS="$cols"
    export LINES="$rows"
    export DEMO_STATUS_FILE="$STATUS_FILE"
    asciinema rec "$cast" \
        --overwrite \
        --cols "$cols" \
        --rows "$rows" \
        --command "uv run python assets/demo/generate_demo.py --scenario ${name}" \
        --quiet

    if [ ! -f "$STATUS_FILE" ] || ! grep -qx "ok" "$STATUS_FILE"; then
        echo "❌ ${name} failed checks"
        cat "$STATUS_FILE" 2>/dev/null || true
        rm -f "$cast"
        exit 1
    fi

    agg "$cast" "$gif" \
        --theme monokai \
        --font-family "JetBrains Mono" \
        --font-size "$font" \
        --line-height 1.32 \
        --speed 1.0 \
        --fps-cap 10 \
        --last-frame-duration "$last_frame"

    if command -v gifsicle >/dev/null 2>&1; then
        gifsicle -O3 -o "${gif}.opt" "$gif"
        mv "${gif}.opt" "$gif"
    fi
    rm -f "$cast"

    local size
    if [[ "$OSTYPE" == "darwin"* ]]; then
        size=$(stat -f%z "$gif")
    else
        size=$(stat -c%s "$gif")
    fi
    local pretty
    if [ "$size" -lt 1048576 ]; then
        pretty="$((size / 1024)) KB"
    else
        pretty="$(awk -v bytes="$size" 'BEGIN { printf "%.1f MB", bytes / 1048576 }')"
    fi
    local duration
    duration="$(gif_duration "$gif")"
    echo "✓ ${gif_name}  ${pretty}  ${duration}"
    if [ "$size" -ge "$MAX_BYTES" ]; then
        echo "❌ ${gif_name} is over 2 MB"
        exit 1
    fi
    echo ""
}

echo "[4/5] Recording..."
found=0
for spec in "${TAKES[@]}"; do
    read -r name gif_name cols rows font last_frame seeded <<<"$spec"
    if [ "$ONLY" != "all" ] && [ "$ONLY" != "$name" ]; then
        continue
    fi
    found=1
    record_one "$name" "$gif_name" "$cols" "$rows" "$font" "$last_frame" "$seeded"
done

if [ "$found" -ne 1 ]; then
    echo "❌ Unknown scenario: ${ONLY}"
    echo "Choose: sparse dense contradictions lifecycle retrieval"
    exit 1
fi

echo "[5/5] Done."
echo "README GIF: assets/demo/demo.gif"
echo "Dense take: assets/demo/demo_dense.gif"
echo "Landing: assets/demo/demo_contradictions.gif assets/demo/demo_lifecycle.gif assets/demo/demo_retrieval.gif"
echo ""
echo "Note: ArcadeDB data persists in the docker volume arcade-data"
echo "      To clean: docker compose down -v"
if [ "$STARTED_SERVER" = 1 ]; then
    echo "To stop the server started by this script, kill the pid in $SERVER_PID_FILE"
fi
echo "To stop the database: docker compose down"
