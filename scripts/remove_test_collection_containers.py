#!/usr/bin/env python3
"""
One-off patch: remove all containers named "Test Collection" from the database.

Run once to clean up rows created before the rename to "Test Container".
Usage:
    cd /opt/retrovue/server
    source .venv/bin/activate
    python /opt/retrovue/scripts/remove_test_collection_containers.py [--dry-run]
"""

import sys
from pathlib import Path

# Allow importing retrovue from server/src
_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_SRC = _REPO_ROOT / "pkg" / "core" / "src"
if _CORE_SRC.exists() and str(_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(_CORE_SRC))

NAME = "Test Collection"


def main():
    dry_run = "--dry-run" in sys.argv
    try:
        from retrovue.domain.entities import Asset, Container, PathMapping, ReviewQueue, ScheduleItem
        from retrovue.infra.uow import session
    except ImportError as e:
        print("ERROR: Could not import retrovue. Run from server with venv activated.", file=sys.stderr)
        print("  cd /opt/retrovue/server && source .venv/bin/activate", file=sys.stderr)
        sys.exit(1)

    with session() as db:
        rows = db.query(Container).filter(Container.name == NAME).all()
        if not rows:
            print(f"No containers named '{NAME}' found.")
            return
        print(f"Found {len(rows)} container(s) named '{NAME}'.")
        if dry_run:
            for c in rows:
                print(f"  Would delete: {c.uuid} (source_id={c.source_id}, external_id={c.external_id})")
            print("Run without --dry-run to delete.")
            return
        deleted = 0
        for container in rows:
            c_uuid = container.uuid
            asset_uuids = [a.uuid for a in db.query(Asset).filter(Asset.container_id == c_uuid).all()]
            if asset_uuids:
                db.query(ReviewQueue).filter(ReviewQueue.asset_uuid.in_(asset_uuids)).delete(
                    synchronize_session=False
                )
                db.query(Asset).filter(Asset.container_id == c_uuid).delete(synchronize_session=False)
            db.query(PathMapping).filter(PathMapping.container_id == c_uuid).delete()
            db.query(ScheduleItem).filter(ScheduleItem.container_id == c_uuid).update(
                {ScheduleItem.container_id: None}, synchronize_session=False
            )
            db.delete(container)
            deleted += 1
        db.commit()
        print(f"Removed {deleted} container(s) named '{NAME}'.")


if __name__ == "__main__":
    main()
