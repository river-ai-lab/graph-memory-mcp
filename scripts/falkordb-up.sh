#!/usr/bin/env bash
# Start FalkorDB via Docker Compose and wait until Redis responds.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "error: docker not found" >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "Creating .env from env.example (FalkorDB password and defaults)."
  cp env.example .env
fi

echo "Starting FalkorDB (docker compose)..."
docker compose up -d --wait

echo "FalkorDB is ready on localhost:6379 (password: falkordb123)."
