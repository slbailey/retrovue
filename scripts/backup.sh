#!/usr/bin/env bash
# RetroVue backup script
# Backs up: PostgreSQL database, SQLite legacy database, config files
# Keeps last 7 daily backups, rotates automatically

set -euo pipefail

RETROVUE_HOME="/opt/retrovue"
BACKUP_DIR="${RETROVUE_HOME}/backups"
TIMESTAMP=$(date +%Y-%m-%d_%H%M%S)
BACKUP_NAME="retrovue_${TIMESTAMP}"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_NAME}"
KEEP_DAYS=7

# PostgreSQL connection (matches pkg/core settings)
PG_HOST="${PG_HOST:-192.168.1.50}"
PG_PORT="${PG_PORT:-5432}"
PG_DB="${PG_DB:-retrovue}"
PG_USER="${PG_USER:-retrovue}"

mkdir -p "${BACKUP_PATH}"

# 1. PostgreSQL backup (primary database)
if command -v pg_dump &>/dev/null; then
    pg_dump -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" \
        --format=custom --compress=6 \
        -f "${BACKUP_PATH}/retrovue_pg.dump" 2>/dev/null
    if [ $? -eq 0 ] && [ -f "${BACKUP_PATH}/retrovue_pg.dump" ]; then
        echo "✓ PostgreSQL backed up ($(du -h "${BACKUP_PATH}/retrovue_pg.dump" | cut -f1))"
    else
        echo "✗ PostgreSQL backup failed"
    fi
else
    echo "✗ pg_dump not found — skipping PostgreSQL backup"
fi

# 2. SQLite backup (legacy database)
DB_FILE="${RETROVUE_HOME}/data/retrovue.db"
if [ -f "$DB_FILE" ]; then
    sqlite3 "$DB_FILE" ".backup ${BACKUP_PATH}/retrovue.db"
    echo "✓ SQLite backed up ($(du -h "${BACKUP_PATH}/retrovue.db" | cut -f1))"
else
    echo "- SQLite not found (legacy): ${DB_FILE}"
fi

# 3. Config files
cp -r "${RETROVUE_HOME}/config" "${BACKUP_PATH}/config"
echo "✓ Config backed up"

# 3. Compress
cd "${BACKUP_DIR}"
tar czf "${BACKUP_NAME}.tar.gz" "${BACKUP_NAME}"
rm -rf "${BACKUP_PATH}"
echo "✓ Compressed: ${BACKUP_NAME}.tar.gz ($(du -h "${BACKUP_NAME}.tar.gz" | cut -f1))"

# 4. Rotate old backups
find "${BACKUP_DIR}" -name "retrovue_*.tar.gz" -mtime +${KEEP_DAYS} -delete 2>/dev/null
REMAINING=$(ls -1 "${BACKUP_DIR}"/retrovue_*.tar.gz 2>/dev/null | wc -l)
echo "✓ Backups on disk: ${REMAINING} (keeping last ${KEEP_DAYS} days)"

echo "Done: ${BACKUP_DIR}/${BACKUP_NAME}.tar.gz"
