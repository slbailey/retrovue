from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from ..domain.entities import Asset


def _serialize_asset(asset: Asset) -> dict[str, Any]:
    return {
        "uuid": str(asset.uuid),
        "collection_uuid": str(asset.collection_uuid),
        "uri": asset.uri,
        "state": asset.state,
        "approved_for_broadcast": bool(asset.approved_for_broadcast),
    }


def get_asset_summary(db: Session, *, asset_uuid: str) -> dict[str, Any]:
    """Read-only fetch of an asset summary by UUID or raise ValueError if missing."""
    try:
        asset_id = _uuid.UUID(asset_uuid)
    except Exception as exc:  # noqa: BLE001 - validation funnelled to not found
        raise ValueError("Asset not found") from exc

    asset = db.get(Asset, asset_id)
    if not asset:
        raise ValueError("Asset not found")
    return _serialize_asset(asset)


def update_asset_review_status(
    db: Session,
    *,
    asset_uuid: str,
    approved: bool | None = None,
    state: str | None = None,
) -> dict[str, Any]:
    """Update minimal review fields on an Asset.

    - Hard fail if asset not found
    - If approved is True, set approved_for_broadcast = True
    - If state provided, set state (enables enriching -> ready path)
    - Always bump updated_at
    - Add to session, but do not commit
    """
    try:
        asset_id = _uuid.UUID(asset_uuid)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Asset not found") from exc

    asset = db.get(Asset, asset_id)
    if not asset:
        raise ValueError("Asset not found")

    if approved is True:
        asset.approved_for_broadcast = True

    if state is not None:
        asset.state = state

    asset.updated_at = datetime.now(UTC)

    db.add(asset)  # no commit; UoW handles it

    return _serialize_asset(asset)



