#!/usr/bin/env bash
# Snapshot FalkorDB to ./backups: trigger BGSAVE, then copy the RDB dump.
# Usage: ./scripts/backup.sh [backup_dir]
# Schedule example (hourly): 0 * * * * cd /path/to/repo && ./scripts/backup.sh
set -euo pipefail

CONTAINER="${FALKORDB_CONTAINER:-graph-memory-falkordb}"
PASSWORD="${FALKORDB_PASSWORD:-falkordb123}"
DATA_DIR="${FALKORDB_DATA_DIR:-./data}"
BACKUP_DIR="${1:-./backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP_DIR"

# Trigger a background save and wait for it to finish.
docker exec "$CONTAINER" redis-cli -a "$PASSWORD" --no-auth-warning BGSAVE >/dev/null
last_save="$(docker exec "$CONTAINER" redis-cli -a "$PASSWORD" --no-auth-warning LASTSAVE)"
for _ in $(seq 1 60); do
  sleep 1
  now_save="$(docker exec "$CONTAINER" redis-cli -a "$PASSWORD" --no-auth-warning LASTSAVE)"
  [ "$now_save" != "$last_save" ] && break
done

cp "$DATA_DIR/dump.rdb" "$BACKUP_DIR/dump-$STAMP.rdb"
echo "Backup written: $BACKUP_DIR/dump-$STAMP.rdb"

# Keep the 14 most recent backups.
ls -1t "$BACKUP_DIR"/dump-*.rdb 2>/dev/null | tail -n +15 | xargs -r rm --
