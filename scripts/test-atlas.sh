#!/bin/bash
# Run Atlas tests against real ArcadeDB (>= 26.10.2)

set -e

echo "=== Atlas Shared-Graph Tests with Real ArcadeDB ==="
echo ""
echo "Prerequisites:"
echo "  - Docker running"
echo "  - ArcadeDB >= 26.10.2"
echo ""

# Check if docker is available
if ! command -v docker &> /dev/null; then
    echo "ERROR: docker not found. Please install Docker."
    exit 1
fi

# Check if docker compose is available
if ! docker compose version &> /dev/null; then
    echo "ERROR: docker compose not found. Please install Docker Compose."
    exit 1
fi

echo "Starting ArcadeDB..."
docker compose up -d arcadedb

# Wait for ArcadeDB to be ready
echo "Waiting for ArcadeDB to be ready..."
max_attempts=30
attempt=0
while [ $attempt -lt $max_attempts ]; do
    if curl -s -f http://localhost:2480/api/v1/ready > /dev/null 2>&1; then
        echo "ArcadeDB is ready!"
        break
    fi
    attempt=$((attempt + 1))
    echo "  Waiting... ($attempt/$max_attempts)"
    sleep 1
done

if [ $attempt -eq $max_attempts ]; then
    echo "ERROR: ArcadeDB failed to start"
    docker compose logs arcadedb
    exit 1
fi

echo ""
echo "Running tests..."
echo ""

# Run all arcade tests
uv run pytest -m arcade tests/test_atlas_shared_graph.py -v

exit_code=$?

echo ""
if [ $exit_code -eq 0 ]; then
    echo "=== ALL TESTS PASSED ==="
else
    echo "=== SOME TESTS FAILED ==="
fi

echo ""
echo "ArcadeDB logs:"
docker compose logs --tail=50 arcadedb

exit $exit_code
