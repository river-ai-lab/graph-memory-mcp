#!/usr/bin/env bash
# Full test suite: ensure FalkorDB is up, then run pytest.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

"$ROOT/scripts/falkordb-up.sh"
uv run pytest -q "$@"
