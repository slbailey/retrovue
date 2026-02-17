#!/usr/bin/env python3
"""
Enrich asset durations from Plex metadata and promote ready assets.

1. For assets with duration_ms = 0 or NULL:
   - First try editorial payload runtime_ms
   - Fall back to Plex API call using rating_key from URI
2. Promote assets with duration + editorial data to state='ready'
"""

import json
import re
import sys
import xml.etree.ElementTree as ET

import psycopg
import requests

DB_URL = "postgresql://retrovue:mb061792@192.168.1.50:5432/retrovue"
PLEX_BASE = "https://plex.slbhome.com"
PLEX_TOKEN = "GFsoKwy-7gU8QUa2FojE"


def get_plex_duration(rating_key: str) -> int | None:
    """Fetch duration_ms from Plex API for a given rating_key."""
    try:
        url = f"{PLEX_BASE}/library/metadata/{rating_key}"
        resp = requests.get(
            url,
            params={"X-Plex-Token": PLEX_TOKEN},
            headers={"Accept": "application/xml"},
            timeout=20,
            verify=False,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        video = root.find(".//Video")
        if video is not None:
            dur = video.get("duration")
            if dur:
                return int(dur)
        # Try Media element
        media = root.find(".//Media")
        if media is not None:
            dur = media.get("duration")
            if dur:
                return int(dur)
    except Exception as e:
        print(f"  [WARN] Plex API error for rk={rating_key}: {e}", file=sys.stderr)
    return None


def main():
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    conn = psycopg.connect(DB_URL)

    # Phase 1: Update duration_ms from editorial runtime_ms
    print("=== Phase 1: Update duration_ms from editorial payload ===")
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE assets a
            SET duration_ms = (ae.payload->>'runtime_ms')::int,
                updated_at = NOW()
            FROM asset_editorial ae
            WHERE ae.asset_uuid = a.uuid
              AND (a.duration_ms IS NULL OR a.duration_ms = 0)
              AND (ae.payload->>'runtime_ms') IS NOT NULL
              AND (ae.payload->>'runtime_ms')::int > 0
        """)
        editorial_updated = cur.rowcount
        conn.commit()
    print(f"  Updated {editorial_updated} assets from editorial runtime_ms")

    # Phase 2: For remaining assets with no duration, try Plex API
    print("\n=== Phase 2: Fetch remaining durations from Plex API ===")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT uuid, uri FROM assets
            WHERE (duration_ms IS NULL OR duration_ms = 0)
        """)
        missing = cur.fetchall()

    print(f"  {len(missing)} assets still missing duration")
    plex_updated = 0
    plex_failed = 0

    for asset_uuid, uri in missing:
        # Extract rating_key from plex://{rating_key}
        m = re.match(r"plex://(\d+)", uri or "")
        if not m:
            plex_failed += 1
            continue
        rating_key = m.group(1)
        duration = get_plex_duration(rating_key)
        if duration and duration > 0:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE assets SET duration_ms = %s, updated_at = NOW() WHERE uuid = %s",
                    (duration, asset_uuid),
                )
            plex_updated += 1
        else:
            plex_failed += 1

    conn.commit()
    print(f"  Updated {plex_updated} from Plex API, {plex_failed} failed/skipped")

    # Phase 3: Promote assets to 'ready'
    print("\n=== Phase 3: Promote eligible assets to 'ready' ===")
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE assets a
            SET state = 'ready', updated_at = NOW()
            FROM asset_editorial ae
            WHERE ae.asset_uuid = a.uuid
              AND a.state != 'ready'
              AND a.duration_ms IS NOT NULL AND a.duration_ms > 0
              AND (ae.payload->>'series_title') IS NOT NULL
              AND (ae.payload->>'season_number') IS NOT NULL
              AND (ae.payload->>'episode_number') IS NOT NULL
        """)
        promoted = cur.rowcount
        conn.commit()
    print(f"  Promoted {promoted} assets to 'ready'")

    # Summary
    print("\n=== Summary ===")
    with conn.cursor() as cur:
        cur.execute("SELECT state, COUNT(*) FROM assets GROUP BY state ORDER BY state")
        states = cur.fetchall()
        cur.execute("SELECT COUNT(*) FROM assets WHERE duration_ms > 0")
        has_dur = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM assets WHERE duration_ms IS NULL OR duration_ms = 0")
        no_dur = cur.fetchone()[0]

    print(f"  Total with duration: {has_dur}")
    print(f"  Total without duration: {no_dur}")
    print(f"  States: {dict(states)}")
    print(f"\n  Editorial updates: {editorial_updated}")
    print(f"  Plex API updates: {plex_updated}")
    print(f"  Plex API failures: {plex_failed}")
    print(f"  Promoted to ready: {promoted}")

    conn.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
