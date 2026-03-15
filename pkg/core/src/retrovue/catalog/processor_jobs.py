"""
Processor job queue: enqueue, claim, complete, retry.

Contract: ProcessorJobQueueContract. One job per (target_type, target_id).
When ENABLE_PROCESSOR_QUEUE is true, reconciliation calls real enqueue.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.entities import ProcessorJob

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)

PRIORITY_LOW = 0
PRIORITY_NORMAL = 1
PRIORITY_HIGH = 2
PRIORITY_CRITICAL = 3

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


def enqueue(
    db: Session,
    target_type: str,
    target_id: uuid.UUID,
    priority: int = PRIORITY_NORMAL,
) -> ProcessorJob | None:
    """
    Insert a job only if no pending/running job exists for (target_type, target_id).

    Returns the new job or the existing active job (optionally with escalated priority).
    """
    existing = (
        db.query(ProcessorJob)
        .filter(
            ProcessorJob.target_type == target_type,
            ProcessorJob.target_id == target_id,
            ProcessorJob.status.in_([STATUS_PENDING, STATUS_RUNNING]),
        )
        .first()
    )
    if existing is not None:
        if priority > existing.priority:
            existing.priority = priority
        return existing
    job = ProcessorJob(
        id=uuid.uuid4(),
        target_type=target_type,
        target_id=target_id,
        status=STATUS_PENDING,
        priority=priority,
    )
    db.add(job)
    db.flush()  # so same-session second enqueue sees this row and deduplicates
    return job


def claim_next_job(db: Session) -> ProcessorJob | None:
    """
    Select one pending job (highest priority, then oldest), set status=running, started_at=now.

    Uses FOR UPDATE SKIP LOCKED so only one worker claims a given job.
    """
    stmt = (
        select(ProcessorJob)
        .where(ProcessorJob.status == STATUS_PENDING)
        .order_by(ProcessorJob.priority.desc(), ProcessorJob.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = db.execute(stmt).scalars().first()
    if job is None:
        return None
    job.status = STATUS_RUNNING
    job.started_at = datetime.now(UTC)
    return job


def complete_job(
    db: Session,
    job_id: uuid.UUID,
    success: bool,
    error_message: str | None = None,
) -> None:
    """Set status to completed or failed, set completed_at and optionally error_message."""
    job = db.get(ProcessorJob, job_id)
    if job is None:
        return
    job.status = STATUS_COMPLETED if success else STATUS_FAILED
    job.completed_at = datetime.now(UTC)
    job.error_message = error_message


def retry_job(db: Session, job_id: uuid.UUID) -> None:
    """Set status back to pending, clear started_at and error_message."""
    job = db.get(ProcessorJob, job_id)
    if job is None:
        return
    job.status = STATUS_PENDING
    job.started_at = None
    job.completed_at = None
    job.error_message = None


def enqueue_processor_jobs(
    asset_ids: list[uuid.UUID],
    processor_ids: list[str],
    *,
    db: object = None,
) -> None:
    """
    Enqueue one job per (target_type, asset_id) for each distinct target_type from processor_ids.

    When ENABLE_PROCESSOR_QUEUE is false, no-op (stub). When true, for each asset_id and each
    target_type from the collection's processors (via get_capability), call enqueue().
    Deduplication ensures at most one pending/running job per (target_type, target_id).
    """
    from ..infra.settings import settings

    from .processor_capability import get_capability

    if not settings.enable_processor_queue or not db or not asset_ids:
        if asset_ids and processor_ids:
            logger.debug(
                "enqueue_processor_jobs_skipped",
                asset_count=len(asset_ids),
                processor_ids=processor_ids,
            )
        return
    target_types = set()
    for pid in processor_ids or []:
        cap = get_capability(pid)
        if cap:
            target_types.add(cap.target_type)
    if not target_types:
        target_types = {"ASSET"}
    for asset_id in asset_ids:
        for target_type in target_types:
            enqueue(db, target_type, asset_id, priority=PRIORITY_NORMAL)
    logger.debug(
        "enqueue_processor_jobs",
        asset_count=len(asset_ids),
        target_types=list(target_types),
    )
