"""
CUN render request queue: enqueue, claim, complete, dedup, skip.

Schedule-scoped content synthesis queue (INV-CUN-SCHEDULE-SCOPED-001).
Uses the same SKIP LOCKED claim pattern as processor_jobs but operates on
schedule segments, not assets.

Priority is playout-time ordered: lower number = higher priority (soonest first).
INV-CUN-PRIORITY-PLAYOUT-001.
"""

from __future__ import annotations

import hashlib
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.entities import CunRenderRequest
from .clock import AuthoritativeClock

logger = structlog.get_logger(__name__)

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


def content_hash_for(template_id: str, title: str) -> str:
    """Deterministic content hash for CUN dedup: SHA256(template_id + title).

    INV-CUN-CACHE-DEDUP-001: rendered assets are content-addressed by this hash.
    """
    payload = f"{template_id}:{title}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def find_completed_by_hash(db: Session, hash_value: str) -> CunRenderRequest | None:
    """Find an existing completed render with matching content_hash.

    INV-CUN-DEDUP-BEFORE-RENDER-001: reuse existing completed renders.
    """
    stmt = (
        select(CunRenderRequest)
        .where(
            CunRenderRequest.content_hash == hash_value,
            CunRenderRequest.status == STATUS_COMPLETED,
        )
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def claim_next(db: Session, *, clock: AuthoritativeClock) -> CunRenderRequest | None:
    """Claim one pending CUN render request (lowest priority number = soonest playout).

    Uses SELECT FOR UPDATE SKIP LOCKED so only one worker claims a given request.
    INV-CUN-PRIORITY-PLAYOUT-001.
    """
    stmt = (
        select(CunRenderRequest)
        .where(CunRenderRequest.status == STATUS_PENDING)
        .order_by(CunRenderRequest.priority.asc(), CunRenderRequest.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    req = db.execute(stmt).scalars().first()
    if req is None:
        return None
    req.status = STATUS_RUNNING
    req.started_at = clock.now_utc()
    return req


def complete(
    db: Session,
    request_id: uuid.UUID,
    rendered_path: str,
    hash_value: str,
    *,
    clock: AuthoritativeClock,
) -> None:
    """Mark a CUN render request as completed with the rendered file path."""
    req = db.get(CunRenderRequest, request_id)
    if req is None:
        return
    req.status = STATUS_COMPLETED
    req.rendered_asset_path = rendered_path
    req.content_hash = hash_value
    req.completed_at = clock.now_utc()


def skip(
    db: Session,
    request_id: uuid.UUID,
    reason: str,
    *,
    clock: AuthoritativeClock,
) -> None:
    """Mark a CUN render request as skipped (e.g. past deadline).

    INV-CUN-RENDER-DEADLINE-001.
    """
    req = db.get(CunRenderRequest, request_id)
    if req is None:
        return
    req.status = STATUS_SKIPPED
    req.error_message = reason
    req.completed_at = clock.now_utc()


def fail(
    db: Session,
    request_id: uuid.UUID,
    error: str,
    *,
    clock: AuthoritativeClock,
) -> None:
    """Mark a CUN render request as failed."""
    req = db.get(CunRenderRequest, request_id)
    if req is None:
        return
    req.status = STATUS_FAILED
    req.error_message = error
    req.completed_at = clock.now_utc()
