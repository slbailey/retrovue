from __future__ import annotations

import uuid as uuid_module
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..domain.entities import Zone


def _resolve_zone(db: Session, identifier: str) -> Zone:
    """Resolve zone by UUID or name (case-insensitive).

    Raises ValueError if zone not found.
    """
    zone = None
    try:
        zone_uuid = uuid_module.UUID(identifier)
        zone = db.query(Zone).filter(Zone.id == zone_uuid).first()
    except ValueError:
        pass

    if not zone:
        zone = (
            db.query(Zone)
            .filter(func.lower(Zone.name) == identifier.lower())
            .first()
        )

    if not zone:
        raise ValueError(f"Zone '{identifier}' not found")

    return zone


def delete_zone(
    db: Session,
    *,
    zone_identifier: str,
) -> dict[str, Any]:
    """Delete a Zone by UUID or name.

    Args:
        db: Database session
        zone_identifier: Zone UUID or name

    Returns:
        Dictionary with deleted zone ID and confirmation

    Raises:
        ValueError: If zone is not found
    """
    zone = _resolve_zone(db, zone_identifier)

    zone_id = str(zone.id)
    zone_name = zone.name

    db.delete(zone)
    db.commit()

    return {
        "id": zone_id,
        "name": zone_name,
        "deleted": True,
    }


__all__ = ["delete_zone"]
