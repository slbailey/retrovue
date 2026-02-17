#!/usr/bin/env python3
"""
Backfill content_editorial table in SQLite from PostgreSQL asset_editorial data.

Usage:
    cd /opt/retrovue/pkg/core
    source .venv/bin/activate
    python /opt/retrovue/scripts/backfill_editorial.py
"""

import json
import sqlite3
import sys

sys.path.insert(0, "/opt/retrovue/pkg/core/src")

SQLITE_DB = "/opt/retrovue/data/retrovue.db"
PLEX_SOURCE = "plex"


def main():
    try:
        from retrovue.infra.uow import session
        from retrovue.domain.entities import Asset, AssetEditorial
    except ImportError:
        print("ERROR: Could not import retrovue. Activate venv first.")
        sys.exit(1)

    conn = sqlite3.connect(SQLITE_DB)
    cur = conn.cursor()

    cur.execute("SELECT count(*) FROM content_items")
    ci_count = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM content_editorial")
    ce_count = cur.fetchone()[0]
    print(f"SQLite before: {ci_count} content_items, {ce_count} content_editorial rows")

    # Extract data from PostgreSQL within the session
    asset_data = []
    with session() as db:
        # Load editorials
        editorials = {}
        for ed in db.query(AssetEditorial).all():
            editorials[str(ed.asset_uuid)] = ed.payload or {}

        # Load assets - extract needed fields while in session
        for asset in db.query(Asset).filter(Asset.state == "ready").all():
            uuid_str = str(asset.uuid)
            asset_data.append({
                "uuid": uuid_str,
                "duration_ms": asset.duration_ms,
                "editorial": editorials.get(uuid_str, {}),
            })

    print(f"PostgreSQL: {len(asset_data)} ready assets with editorial data")

    inserted_ci = 0
    inserted_ce = 0
    skipped = 0

    for item in asset_data:
        editorial = item["editorial"]
        description = editorial.get("description", "")
        title = editorial.get("title", "") or editorial.get("series_title", "")

        if not description and not title:
            skipped += 1
            continue

        int_id = hash(item["uuid"]) & 0x7FFFFFFF
        kind = "episode" if editorial.get("series_title") else "movie"

        try:
            cur.execute(
                "INSERT OR IGNORE INTO content_items (id, kind, title, synopsis, duration_ms) VALUES (?, ?, ?, ?, ?)",
                (int_id, kind, title, description, item["duration_ms"]),
            )
            if cur.rowcount > 0:
                inserted_ci += 1
        except Exception as e:
            continue

        try:
            cur.execute(
                "INSERT OR IGNORE INTO content_editorial (content_item_id, source_name, source_payload_json, original_title, original_synopsis) VALUES (?, ?, ?, ?, ?)",
                (int_id, PLEX_SOURCE, json.dumps(editorial), title, description),
            )
            if cur.rowcount > 0:
                inserted_ce += 1
        except Exception as e:
            continue

    conn.commit()

    cur.execute("SELECT count(*) FROM content_items")
    ci_after = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM content_editorial")
    ce_after = cur.fetchone()[0]
    conn.close()

    print(f"\nResults:")
    print(f"  content_items inserted: {inserted_ci}")
    print(f"  content_editorial inserted: {inserted_ce}")
    print(f"  skipped (no title/description): {skipped}")
    print(f"SQLite after: {ci_after} content_items, {ce_after} content_editorial rows")


if __name__ == "__main__":
    main()
