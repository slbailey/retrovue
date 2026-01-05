from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..domain.entities import Collection, Source


def list_sources(db: Session, *, source_type: str | None = None) -> list[dict[str, Any]]:
    """
    List sources with enabled/ingestible collection counts. Single operation.
    """
    query = db.query(Source)
    if source_type:
        query = query.filter(Source.type == source_type)

    sources = query.all()

    result: list[dict[str, Any]] = []
    for src in sources:
        try:
            enabled = (
                db.query(Collection)
                .filter(
                    Collection.source_id == src.id,
                    Collection.sync_enabled.is_(True),
                )
                .count()
            )
            ingestible = (
                db.query(Collection)
                .filter(
                    Collection.source_id == src.id,
                    Collection.ingestible.is_(True),
                )
                .count()
            )
        except Exception:
            enabled = 0
            ingestible = 0

        created_at_value = None
        if getattr(src, "created_at", None):
            created_at_value = (
                src.created_at.isoformat()
                if hasattr(src.created_at, "isoformat")
                else src.created_at
            )
        updated_at_value = None
        if getattr(src, "updated_at", None):
            updated_at_value = (
                src.updated_at.isoformat()
                if hasattr(src.updated_at, "isoformat")
                else src.updated_at
            )

        result.append(
            {
                "id": str(src.id),
                "name": src.name,
                "type": src.type,
                "created_at": created_at_value,
                "updated_at": updated_at_value,
                "enabled_collections": enabled,
                "ingestible_collections": ingestible,
            }
        )

    return result


__all__ = ["list_sources"]


