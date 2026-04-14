from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from ..domain.entities import Asset, Container


def _resolve_container(db: Session, container_selector: str) -> Container:
    """Resolve container by UUID, external_id, or case-insensitive name."""
    container = None

    try:
        container_uuid = UUID(container_selector)
        container = db.query(Container).filter(Container.uuid == container_uuid).first()
    except Exception:
        container = None

    if not container:
        container = (
            db.query(Container).filter(Container.external_id == container_selector).first()
        )

    if not container:
        matches = db.query(Container).filter(Container.name.ilike(container_selector)).all()
        if len(matches) == 1:
            container = matches[0]
        elif len(matches) > 1:
            raise ValueError(
                f"Multiple containers named '{container_selector}' found. Use container UUID."
            )

    if not container:
        raise ValueError(f"Container '{container_selector}' not found")

    return container


def _is_invalid_duration(duration_ms: int | None) -> bool:
    return duration_ms is None or duration_ms <= 0


def _is_broadcast_ready(*, state: str | None, approved_for_broadcast: bool, duration_ms: int | None) -> bool:
    return state == "ready" and bool(approved_for_broadcast) and not _is_invalid_duration(duration_ms)


def list_assets_for_container(
    db: Session,
    *,
    container_selector: str,
    issues_only: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """List assets for a container with readiness diagnostics."""
    container = _resolve_container(db, container_selector)

    query = (
        db.query(Asset)
        .filter(
            Asset.container_id == container.uuid,
            Asset.is_deleted.is_(False),
        )
        .order_by(Asset.discovered_at.desc())
    )

    if limit and limit > 0:
        query = query.limit(limit)

    assets = query.all()
    rows: list[dict[str, Any]] = []
    for a in assets:
        invalid_duration = _is_invalid_duration(a.duration_ms)
        broadcast_ready = _is_broadcast_ready(
            state=a.state,
            approved_for_broadcast=bool(a.approved_for_broadcast),
            duration_ms=a.duration_ms,
        )
        if issues_only and not (invalid_duration or not broadcast_ready):
            continue

        rows.append(
            {
                "uuid": str(a.uuid),
                "collection_uuid": str(a.container_id),
                "container_name": container.name,
                "uri": a.uri,
                "state": a.state,
                "approved_for_broadcast": bool(a.approved_for_broadcast),
                "duration_ms": a.duration_ms,
                "invalid_duration": invalid_duration,
                "broadcast_ready": broadcast_ready,
                "discovered_at": a.discovered_at.isoformat() if a.discovered_at else None,
            }
        )

    return rows
