"""
Artwork resolution for XMLTV/Plex guide.

INV-PLEX-ARTWORK-001: Resolves programme poster URLs from persisted
editorial metadata. MUST NOT make live upstream API calls to resolve artwork.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


def resolve_programme_poster_url(asset_id: uuid.UUID, db: Any) -> str | None:
    """
    Resolve a programme (asset) to a poster image URL.

    INV-PLEX-ARTWORK-001: reads thumb_url from asset_editorial.payload.
    No live Plex API calls. If thumb_url is absent, returns None
    (caller serves placeholder).

    Args:
        asset_id: Asset UUID (programme id from EPG).
        db: SQLAlchemy session.

    Returns:
        Full URL to the poster image, or None if not available.
    """
    from retrovue.domain.entities import Asset, AssetEditorial

    asset = db.query(Asset).filter(Asset.uuid == asset_id).first()
    if not asset:
        return None

    editorial = db.query(AssetEditorial).filter(AssetEditorial.asset_uuid == asset_id).first()
    if editorial and isinstance(editorial.payload, dict):
        thumb = editorial.payload.get("thumb_url")
        if thumb:
            return thumb

    return None
