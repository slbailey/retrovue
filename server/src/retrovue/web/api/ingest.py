"""
REST API endpoints for ingest operations.

Thin HTTP layer over workflow functions — no business logic here.
All ingest orchestration lives in retrovue.workflows.

Phase 2 of Asset Domain Alignment Plan (RETA-69).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...domain.entities import Container, Source
from ...infra.uow import session as get_session
from ...runtime.clock import AuthoritativeClock
from ...workflows import (
    ContainerIngestService,
    SourceIngestService,
    resolve_container_selector,
    resolve_source_selector,
)
from ._clock import get_clock

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------

def get_db():
    """Get database session for dependency injection."""
    db = get_session()
    try:
        with db as session:
            yield session
    finally:
        pass


# ---------------------------------------------------------------------------
# Importer factory (mirrors workflow's internal helper)
# ---------------------------------------------------------------------------

def _construct_importer(container, db):
    """Late-import wrapper to construct importer for a container."""
    from ...cli.commands.collection import construct_importer_for_collection

    return construct_importer_for_collection(container, db)


# ---------------------------------------------------------------------------
# Source endpoints
# ---------------------------------------------------------------------------

@router.post("/sources/{selector}/sync")
def sync_source(
    selector: str,
    dry_run: bool = Query(False, description="Preview without persisting"),
    db: Session = Depends(get_db),
    clock: AuthoritativeClock = Depends(get_clock),
):
    """Trigger ingest for all eligible containers in a source.

    Resolves source by UUID, external_id, or case-insensitive name.
    """
    try:
        source = resolve_source_selector(db, selector)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    svc = SourceIngestService(db, clock=clock)
    result = svc.ingest_source(source, dry_run=dry_run)
    return result.to_dict()


@router.get("/sources/{selector}/status")
def source_status(
    selector: str,
    db: Session = Depends(get_db),
):
    """Get source info and container summary.

    Returns basic source metadata and a list of its containers with
    sync/ingest status flags.
    """
    try:
        source = resolve_source_selector(db, selector)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    containers = (
        db.query(Container)
        .filter(Container.source_id == source.id)
        .all()
    )

    return {
        "source_id": str(source.id),
        "source_name": source.name,
        "source_type": source.type,
        "containers": [
            {
                "container_id": str(c.uuid),
                "name": c.name,
                "sync_enabled": c.sync_enabled,
                "ingestible": c.ingestible,
            }
            for c in containers
        ],
    }


# ---------------------------------------------------------------------------
# Container endpoints
# ---------------------------------------------------------------------------

@router.post("/containers/{selector}/sync")
def sync_container(
    selector: str,
    dry_run: bool = Query(False, description="Preview without persisting"),
    db: Session = Depends(get_db),
    clock: AuthoritativeClock = Depends(get_clock),
):
    """Trigger ingest for a single container.

    Resolves container by UUID, external_id, or case-insensitive name.
    """
    try:
        container = resolve_container_selector(db, selector)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    importer = _construct_importer(container, db)
    svc = ContainerIngestService(db, clock=clock)
    result = svc.ingest_container(
        container=container,
        importer=importer,
        dry_run=dry_run,
    )
    return result.to_dict()
