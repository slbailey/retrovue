from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..domain.entities import Source


def add_source(
    db: Session,
    *,
    source_type: str,
    name: str,
    config: dict[str, Any],
    enrichers: list[str] | None = None,
) -> dict[str, Any]:
    """
    Create a Source. Single noun-verb operation. Returns data for CLI.
    """
    external_id = f"{source_type}-{name.lower().replace(' ', '-')}"

    source = Source(
        external_id=external_id,
        name=name,
        type=source_type,
        config=config,
    )

    db.add(source)
    db.commit()
    db.refresh(source)

    return {
        "id": str(source.id),
        "external_id": source.external_id,
        "name": source.name,
        "type": source.type,
        "config": source.config,
        "enrichers": enrichers or [],
    }


__all__ = ["add_source"]


