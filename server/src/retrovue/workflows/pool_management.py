"""
Pool management workflow.

Implements persistent pool CRUD operations per docs/contracts/pool_management.md.
All pool CLI commands delegate to this module (INV-POOL-CLI-DELEGATES-001).

This module MUST NOT read from stdin or write to stdout. All IO stays in the CLI command wrapper.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.entities import Channel, Pool, PoolAssignment
from ..runtime.asset_resolver import PoolDiagnostics

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class PoolInspectResult:
    """Result of inspecting a pool against the current catalog."""

    pool_name: str
    match_criteria: dict
    matched_asset_ids: list[str]
    matched_count: int
    diagnostics: PoolDiagnostics


def create_pool(
    db: Session,
    name: str,
    match_criteria: dict[str, Any],
    description: str | None = None,
) -> Pool:
    """Create a persistent named pool definition.

    INV-POOL-NAME-UNIQUE-001: raises ValueError if name already exists.
    """
    existing = db.execute(
        select(Pool).where(Pool.name == name)
    ).scalar_one_or_none()
    if existing is not None:
        raise ValueError(f"Pool '{name}' already exists")

    pool = Pool(name=name, match_criteria=match_criteria, description=description)
    db.add(pool)
    db.flush()

    logger.info("pool.created", pool_name=name)
    return pool


def list_pools(db: Session) -> list[Pool]:
    """Return all persistent pool definitions, ordered by name."""
    return list(
        db.execute(select(Pool).order_by(Pool.name)).scalars().all()
    )


def inspect_pool(
    db: Session,
    resolver: Any,
    pool_name: str,
) -> PoolInspectResult:
    """Resolve a pool's match criteria against the catalog.

    INV-POOL-RESOLUTION-VISIBILITY-001: returns PoolDiagnostics breakdown.
    """
    pool = db.execute(
        select(Pool).where(Pool.name == pool_name)
    ).scalar_one_or_none()
    if pool is None:
        raise ValueError(f"Pool '{pool_name}' not found")

    matched_ids, diagnostics = resolver.query_with_diagnostics(pool.match_criteria)

    logger.info(
        "pool.inspected",
        pool_name=pool_name,
        matched_count=len(matched_ids),
        total_considered=diagnostics.total_considered,
    )

    return PoolInspectResult(
        pool_name=pool.name,
        match_criteria=pool.match_criteria,
        matched_asset_ids=matched_ids,
        matched_count=len(matched_ids),
        diagnostics=diagnostics,
    )


def assign_pool(
    db: Session,
    pool_name: str,
    channel_name: str,
) -> PoolAssignment:
    """Create an advisory pool→channel association.

    Both pool and channel must exist. Duplicate assignments raise ValueError.
    """
    pool = db.execute(
        select(Pool).where(Pool.name == pool_name)
    ).scalar_one_or_none()
    if pool is None:
        raise ValueError(f"Pool '{pool_name}' not found")

    channel = db.execute(
        select(Channel).where(Channel.slug == channel_name)
    ).scalar_one_or_none()
    if channel is None:
        raise ValueError(f"Channel '{channel_name}' not found")

    existing = db.execute(
        select(PoolAssignment).where(
            PoolAssignment.pool_id == pool.id,
            PoolAssignment.channel_id == channel.id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ValueError(
            f"Pool '{pool_name}' is already assigned to channel '{channel_name}'"
        )

    assignment = PoolAssignment(pool_id=pool.id, channel_id=channel.id)
    db.add(assignment)
    db.flush()

    logger.info(
        "pool.assigned",
        pool_name=pool_name,
        channel_slug=channel_name,
    )

    return assignment
