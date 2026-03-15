"""
Backfill thumb_url into asset_editorial.payload for existing Plex assets.

INV-PLEX-ARTWORK-001: Every Plex-sourced asset MUST have its artwork URL
persisted in asset_editorial.payload at ingest time.  This script
retroactively fulfils that invariant for assets ingested before the
thumb_url persistence was added to the importer.

Usage (from activated venv):
    python -m retrovue.cli.commands._ops.backfill_plex_artwork [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

logger = logging.getLogger(__name__)


def backfill_plex_artwork(*, dry_run: bool = False) -> dict[str, int]:
    """
    For every Plex-sourced asset whose editorial payload is missing thumb_url,
    fetch the thumb from Plex metadata and persist it.

    Returns:
        Stats dict with keys: total, updated, skipped, already_has, errors.
    """
    from retrovue.adapters.importers.plex_importer import PlexClient
    from retrovue.domain.entities import Asset, AssetEditorial, Collection, Source
    from retrovue.infra.uow import session

    stats = {"total": 0, "updated": 0, "skipped": 0, "already_has": 0, "errors": 0}

    with session() as db:
        # Find all Plex sources.
        plex_sources = db.query(Source).filter(Source.type == "plex").all()
        if not plex_sources:
            logger.info("No Plex sources found.")
            return stats

        for source in plex_sources:
            config = source.config or {}
            servers = config.get("servers", [])
            if servers:
                server = servers[0]
                base_url = server.get("base_url")
                token = server.get("token")
            else:
                base_url = config.get("base_url")
                token = config.get("token")

            if not base_url or not token:
                logger.warning(
                    "Source %s (%s) has no base_url/token configured, skipping.",
                    source.name,
                    source.id,
                )
                continue

            client = PlexClient(base_url, token)
            logger.info(
                "Processing source %s (%s) at %s",
                source.name,
                source.id,
                base_url,
            )

            # Get all collections for this source.
            collections = (
                db.query(Collection)
                .filter(Collection.source_id == source.id)
                .all()
            )
            collection_uuids = [c.uuid for c in collections]
            if not collection_uuids:
                continue

            # Get all assets from these collections.
            assets = (
                db.query(Asset)
                .filter(Asset.collection_uuid.in_(collection_uuids))
                .all()
            )
            logger.info("Found %d assets for source %s", len(assets), source.name)

            for asset in assets:
                stats["total"] += 1

                # Extract rating key from URI (plex://{ratingKey}).
                uri = asset.uri or ""
                if not uri.startswith("plex://"):
                    stats["skipped"] += 1
                    continue
                rating_key_str = uri.replace("plex://", "")
                try:
                    rating_key = int(rating_key_str)
                except ValueError:
                    logger.warning(
                        "Asset %s has non-numeric rating key: %s",
                        asset.uuid,
                        rating_key_str,
                    )
                    stats["skipped"] += 1
                    continue

                # Check if editorial already has thumb_url.
                editorial_row = (
                    db.query(AssetEditorial)
                    .filter(AssetEditorial.asset_uuid == asset.uuid)
                    .first()
                )
                if editorial_row and isinstance(editorial_row.payload, dict):
                    if editorial_row.payload.get("thumb_url"):
                        stats["already_has"] += 1
                        continue
                else:
                    # No editorial row at all — skip (shouldn't happen).
                    stats["skipped"] += 1
                    continue

                # Fetch metadata from Plex.
                try:
                    meta = client.get_metadata(rating_key)
                except Exception as exc:
                    logger.warning(
                        "Failed to fetch metadata for asset %s (ratingKey=%d): %s",
                        asset.uuid,
                        rating_key,
                        exc,
                    )
                    stats["errors"] += 1
                    continue

                # Pick the poster, not the screenshot.
                # Movies: thumb IS the poster.
                # TV episodes: thumb is a video still — use series/season poster.
                editorial_payload = editorial_row.payload or {}
                is_episode = bool(editorial_payload.get("episode_id"))
                if is_episode:
                    poster = (
                        meta.get("grandparentThumbUrl")  # series poster
                        or meta.get("parentThumbUrl")     # season poster
                        or meta.get("thumbUrl")           # fallback
                    )
                else:
                    poster = meta.get("thumbUrl")  # movie poster

                if not poster:
                    stats["skipped"] += 1
                    continue
                thumb_url = poster

                if dry_run:
                    logger.info(
                        "[DRY RUN] Would set thumb_url for asset %s: %s",
                        asset.uuid,
                        thumb_url[:80],
                    )
                    stats["updated"] += 1
                    continue

                # Merge thumb_url into editorial payload.
                payload = dict(editorial_row.payload)
                payload["thumb_url"] = thumb_url
                editorial_row.payload = payload
                db.add(editorial_row)
                stats["updated"] += 1

                if stats["updated"] % 100 == 0:
                    logger.info(
                        "Progress: %d/%d updated", stats["updated"], stats["total"]
                    )
                    db.flush()

                # Be gentle to Plex server.
                time.sleep(0.05)

        if dry_run:
            logger.info("[DRY RUN] Rolling back — no changes persisted.")
            db.rollback()

    return stats


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Backfill Plex artwork thumb_url into asset_editorial.payload"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without persisting",
    )
    args = parser.parse_args()

    stats = backfill_plex_artwork(dry_run=args.dry_run)

    print(f"\nBackfill complete:")
    print(f"  Total assets scanned: {stats['total']}")
    print(f"  Updated with thumb_url: {stats['updated']}")
    print(f"  Already had thumb_url: {stats['already_has']}")
    print(f"  Skipped (no URI/no editorial/no thumb): {stats['skipped']}")
    print(f"  Errors (API failures): {stats['errors']}")

    if args.dry_run:
        print("\n  [DRY RUN] No changes were persisted.")


if __name__ == "__main__":
    main()
