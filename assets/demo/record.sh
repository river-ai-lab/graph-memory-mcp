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

# 2. Start ArcadeDB
echo "[2/7] Starting ArcadeDB..."
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

# 3. Install dependencies
echo "[3/7] Installing Python dependencies..."
cd "$PROJECT_ROOT"
uv sync --quiet
echo "✓ Dependencies installed"
echo ""

# 4. Record demo
echo "[4/7] Recording demo (this takes ~20s)..."
cd "$PROJECT_ROOT"

# Fixed terminal size (100 columns x 28 rows, no mid-word wrapping)
export COLUMNS=100
export LINES=28

# Record with asciinema (run from project root so .env is found)
asciinema rec "$DEMO_CAST" \
    --overwrite \
    --cols 100 \
    --rows 28 \
    --command "uv run python assets/demo/generate_demo.py" \
    --quiet

echo "✓ Demo recorded to demo.cast"
echo ""

# 5. Convert to GIF
echo "[5/7] Converting to GIF..."
agg "$DEMO_CAST" "$DEMO_GIF" \
    --theme monokai \
    --font-size 18 \
    --line-height 1.4 \
    --speed 1.2 \
    --fps 10

echo "✓ GIF created"
echo ""

# 6. Cleanup
echo "[6/7] Cleaning up demo data..."

# The demo creates owner_id="demo_team". Data persists in ./data-arcade (ArcadeDB volume).
# To fully clean: docker compose down && rm -rf ./data-arcade
echo "Note: Demo data in ./data-arcade persists across runs"
echo "      To clean: docker compose down && rm -rf ./data-arcade"

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
    SIZE_HUMAN="$((SIZE / 1048576)) MB"
fi

echo "📊 Size: $SIZE_HUMAN"
echo ""
echo "Embed in README.md:"
echo '![Demo](assets/demo/demo.gif)'
echo ""
echo "To stop database: docker compose down"
echo "To clean data: docker compose down && rm -rf ./data-arcade"
