from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..domain.entities import Asset


def list_assets_needing_attention(
    db: Session,
    *,
    collection_uuid: str | None = None,
    limit: int | None = 100,
) -> list[dict[str, Any]]:
    """Return assets that need operator attention.

    Criteria:
    - state == 'enriching' OR approved_for_broadcast == False
    - not soft-deleted
    """
    conditions: Sequence[Any] = [
        Asset.is_deleted.is_(False),
        or_(Asset.state == "enriching", Asset.approved_for_broadcast.is_(False)),
    ]
    if collection_uuid:
        conditions = (*conditions, Asset.collection_uuid == collection_uuid)

    stmt = select(Asset).where(and_(*conditions)).order_by(Asset.discovered_at.desc())
    if limit and limit > 0:
        stmt = stmt.limit(limit)

    rows = db.execute(stmt).scalars().all()

    result: list[dict[str, Any]] = []
    for a in rows:
        result.append(
            {
                "uuid": str(a.uuid),
                "collection_uuid": str(a.collection_uuid),
                "uri": a.uri,
                "state": a.state,
                "approved_for_broadcast": bool(a.approved_for_broadcast),
                "discovered_at": a.discovered_at.isoformat() if a.discovered_at else None,
            }
        )
    return result



