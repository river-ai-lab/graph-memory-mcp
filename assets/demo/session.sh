#!/usr/bin/env bash
# Type the demo client at a shell prompt, then run that same command.
# record.sh captures this. The MCP server is already listening.
set -euo pipefail

scenario="${1:?scenario name}"
delay="${DEMO_TYPE_DELAY:-0.024}"
typed="uv run python assets/demo/generate_demo.py --scenario ${scenario}"

printf '$ '
for ((i = 0; i < ${#typed}; i++)); do
  printf '%s' "${typed:i:1}"
  sleep "$delay"
done
printf '\n'

exec uv run python assets/demo/generate_demo.py --scenario "$scenario"
