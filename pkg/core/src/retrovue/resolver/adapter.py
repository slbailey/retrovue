"""
Resolver adapter for Retrovue content library integration.

This adapter isolates the *existing* content library lookup functionality.
"""

from __future__ import annotations

from src_legacy.retrovue.content_manager.library_service import LibraryService

from ..domain.entities import EntityType, ProviderRef
from ..infra.uow import session


def resolve_asset_by_series_season_episode(series: str, season: int, episode: int) -> dict | None:
    """
    Resolve an asset by series, season, and episode number.

    Args:
        series: Series title
        season: Season number
        episode: Episode number

    Returns:
        Dict with asset information: { "uuid": str, "uri": str, "duration_ms": int }
        or None if not found
    """
    with session() as db:
        library_service = LibraryService(db)

        try:
            # Get all episodes for the series
            assets = library_service.list_episodes_by_series(series)

            if not assets:
                return None

            # Find the specific episode by season and episode number
            for asset in assets:
                # Get provider reference for metadata
                provider_ref = (
                    db.query(ProviderRef)
                    .filter(
                        ProviderRef.asset_id == asset.id,
                        ProviderRef.entity_type == EntityType.ASSET,
                    )
                    .first()
                )

                if provider_ref and provider_ref.raw:
                    raw = provider_ref.raw
                    asset_season = raw.get("parentIndex")
                    asset_episode = raw.get("index")

                    # Convert to integers for comparison
                    try:
                        asset_season = int(asset_season) if asset_season else 0
                        asset_episode = int(asset_episode) if asset_episode else 0
                    except (ValueError, TypeError):
                        continue

                    # Check if this matches our target season/episode
                    if asset_season == season and asset_episode == episode:
                        return {
                            "uuid": str(asset.uuid),
                            "uri": asset.uri,
                            "duration_ms": asset.duration_ms or 0,
                        }

            return None

        except Exception as e:
            # Log error but don't raise - let caller handle
            print(f"Error resolving asset: {e}")
            return None
