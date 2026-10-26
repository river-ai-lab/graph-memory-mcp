#!/usr/bin/env bash
# MCP Inspector CLI demo against a live Graph Memory MCP server.
#
# Paste the command block below into a shell, or run this file.
# The server is already listening (default owner scope, owner "default").
# Reset that owner first so search has only the fact this demo saves:
#
#   curl -s -X DELETE http://127.0.0.1:8000/admin/owners/default
#   ./assets/demo/cli_demo.sh
#
# ./assets/demo/cli_demo.sh --record rebuilds assets/demo/demo_cli.gif.
# Inspector 2.12.0. A URL ending in /mcp is streamable HTTP; --transport http
# is still passed so the transport is visible. --format json -q prints one
# JSON object. The tool payload is a JSON string in result.content[0].text
# (this server does not set structuredContent).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
GIF="$SCRIPT_DIR/demo_cli.gif"
STATUS_FILE="${DEMO_STATUS_FILE:-${TMPDIR:-/tmp}/graph-memory-cli-demo-status}"
TYPE_DELAY="${TYPE_DELAY:-0.02}"
PAUSE_AFTER="${PAUSE_AFTER:-0.35}"
COLS=86
ROWS=20
FONT=24
LAST_FRAME=1.8

extract_commands() {
  awk '/^# BEGIN COMMANDS$/{flag=1; next} /^# END COMMANDS$/{flag=0} flag' "$0"
}

# A command continues on a trailing backslash, or while a single quote is open
# (jq programs wrap inside quotes).
command_open() {
  local text="$1"
  local i char single=0
  for ((i = 0; i < ${#text}; i++)); do
    char="${text:i:1}"
    if [[ "$char" == "'" ]]; then
      if [[ $single -eq 0 ]]; then
        single=1
      else
        single=0
      fi
    fi
  done
  if [[ $single -eq 1 ]]; then
    return 0
  fi
  [[ "${text: -1}" == $'\\' ]]
}

# Group continued lines into one command.
each_command() {
  local block="$1"
  local current=""
  local line
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" && -z "$current" ]] && continue
    if [[ -z "$current" ]]; then
      current="$line"
    else
      current+=$'\n'"$line"
    fi
    if command_open "$current"; then
      continue
    fi
    printf '%s\0' "$current"
    current=""
  done <<<"$block"
  if [[ -n "$current" ]]; then
    printf '%s\0' "$current"
  fi
}

type_line() {
  local line="$1"
  local i
  for ((i = 0; i < ${#line}; i++)); do
    printf '%s' "${line:i:1}"
    sleep "$TYPE_DELAY"
  done
  printf '\n'
}

play() {
  local block
  block="$(extract_commands)"
  local first=1
  local cmd
  while IFS= read -r -d '' cmd; do
    local line_no=0
    local line
    while IFS= read -r line; do
      if [[ "$line_no" -eq 0 ]]; then
        printf '$ '
      else
        printf '> '
      fi
      type_line "$line"
      line_no=$((line_no + 1))
    done <<<"$cmd"
    eval "$cmd"
    if [[ "$first" -eq 1 ]]; then
      first=0
      sleep 0.15
    else
      sleep "$PAUSE_AFTER"
    fi
  done < <(each_command "$block")
  printf 'ok\n' >"$STATUS_FILE"
}

record() {
  command -v npx >/dev/null || {
    echo "npx not found (Node.js). https://nodejs.org/"
    exit 1
  }
  command -v jq >/dev/null || {
    echo "jq not found"
    exit 1
  }
  command -v asciinema >/dev/null || {
    echo "asciinema not found"
    exit 1
  }
  command -v agg >/dev/null || {
    echo "agg not found"
    exit 1
  }
  if ! curl -sf http://127.0.0.1:8000/admin/health >/dev/null; then
    echo "MCP server is not listening on 127.0.0.1:8000"
    echo "Start it: uv run graph-memory-mcp --host 127.0.0.1 --port 8000"
    exit 1
  fi

  export NPM_CONFIG_UPDATE_NOTIFIER=false
  export npm_config_update_notifier=false
  # Warm the Inspector binary off-screen. tools/list does not write a fact.
  npx @modelcontextprotocol/inspector@2.12.0 --cli http://127.0.0.1:8000/mcp \
    --transport http --format json -q --method tools/list >/dev/null
  curl -sf -X DELETE http://127.0.0.1:8000/admin/owners/default >/dev/null || true

  local cast
  cast="$(mktemp "${TMPDIR:-/tmp}/cli-demo.XXXXXX.cast")"
  rm -f "$STATUS_FILE"
  (
    cd "$ROOT"
    export DEMO_STATUS_FILE="$STATUS_FILE"
    export TYPE_DELAY PAUSE_AFTER
    asciinema rec "$cast" \
      --overwrite \
      --cols "$COLS" \
      --rows "$ROWS" \
      --command "bash assets/demo/cli_demo.sh --play" \
      --quiet
  )
  if [[ ! -f "$STATUS_FILE" ]] || ! grep -qx "ok" "$STATUS_FILE"; then
    echo "cli demo failed checks"
    cat "$STATUS_FILE" 2>/dev/null || true
    rm -f "$cast"
    exit 1
  fi

  agg "$cast" "$GIF" \
    --theme monokai \
    --font-family "JetBrains Mono" \
    --font-size "$FONT" \
    --line-height 1.32 \
    --speed 1.0 \
    --fps-cap 10 \
    --last-frame-duration "$LAST_FRAME"
  if command -v gifsicle >/dev/null; then
    gifsicle -O3 -o "${GIF}.opt" "$GIF"
    mv "${GIF}.opt" "$GIF"
  fi
  rm -f "$cast" "$STATUS_FILE"

  local size duration
  size="$(stat -c%s "$GIF")"
  duration="$(
    python3 - "$GIF" <<'PY'
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
print(f"{total / 100:.1f}")
PY
  )"
  echo "demo_cli.gif  ${size} bytes  ${duration}s"
  python3 - "$size" "$duration" <<'PY'
import sys
size, duration = int(sys.argv[1]), float(sys.argv[2])
if size >= 2 * 1024 * 1024:
    sys.exit("demo_cli.gif is over 2 MB")
if not 12.0 <= duration <= 20.0:
    sys.exit(f"demo_cli.gif duration {duration:.1f}s is outside 12–20s")
PY
}

case "${1:-}" in
  --record) record ;;
  --play) play ;;
  "") eval "$(extract_commands)" ;;
  *)
    echo "usage: $0 [--record]"
    exit 1
    ;;
esac
exit 0

# BEGIN COMMANDS
URL=http://127.0.0.1:8000/mcp
npx @modelcontextprotocol/inspector@2.12.0 --cli "$URL" \
  --transport http --format json -q \
  --method tools/call --tool-name create_node \
  --tool-arg text='API gateway uses Component Y' \
  | jq -ec '.result.content[0].text | fromjson | .node
      | {id: .node_id, text} | select(.id != null and .id != "")'
npx @modelcontextprotocol/inspector@2.12.0 --cli "$URL" \
  --transport http --format json -q \
  --method tools/call --tool-name search \
  --tool-arg query='which gateway component?' \
  --tool-arg limit=5 \
  | jq -ec --arg saved 'API gateway uses Component Y' \
      '.result.content[0].text | fromjson | .results[]
      | {text, similarity} | select(.text == $saved)'
# END COMMANDS
