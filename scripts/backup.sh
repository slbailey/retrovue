#!/usr/bin/env bash
# RetroVue backup script
# Backs up: SQLite database, config files, DSL schedules
# Keeps last 7 daily backups, rotates automatically

set -euo pipefail

RETROVUE_HOME="/opt/retrovue"
BACKUP_DIR="${RETROVUE_HOME}/backups"
TIMESTAMP=$(date +%Y-%m-%d_%H%M%S)
BACKUP_NAME="retrovue_${TIMESTAMP}"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_NAME}"
KEEP_DAYS=7

mkdir -p "${BACKUP_PATH}"

# 1. SQLite backup (cp is safe for small DBs; use sqlite3 .backup for large/busy ones)
DB_FILE="${RETROVUE_HOME}/data/retrovue.db"
if [ -f "$DB_FILE" ]; then
    sqlite3 "$DB_FILE" ".backup ${BACKUP_PATH}/retrovue.db"
    echo "✓ Database backed up ($(du -h "${BACKUP_PATH}/retrovue.db" | cut -f1))"
else
    echo "✗ Database not found: ${DB_FILE}"
fi

# 2. Config files
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
