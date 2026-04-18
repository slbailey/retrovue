"""
Processor job queue: enqueue, claim, complete, retry, purge.

Contract: ProcessorJobQueueContract. One job per (target_type, target_id).
Reconciliation and re-enrich always enqueue; workers run the processor runtime (State 3).

Retention: Completed/failed jobs are purged when older than PROCESSOR_JOB_RETENTION_DAYS (default 30).
Purge runs once at the start of each `retrovue worker run`, or on demand via `retrovue worker purge`.
Set PROCESSOR_JOB_RETENTION_DAYS=0 to disable. processor_runs are cascade-deleted with their job.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.entities import ProcessorJob
from ..runtime.clock import AuthoritativeClock

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
        existing_pri = existing.priority if isinstance(existing.priority, int) else 0
        if priority > existing_pri:
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


def claim_next_job(db: Session, *, clock: AuthoritativeClock) -> ProcessorJob | None:
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
    job.started_at = clock.now_utc()
    return job


def complete_job(
    db: Session,
    job_id: uuid.UUID,
    success: bool,
    *,
    clock: AuthoritativeClock,
    error_message: str | None = None,
) -> None:
    """Set status to completed or failed, set completed_at and optionally error_message."""
    job = db.get(ProcessorJob, job_id)
    if job is None:
        return
    job.status = STATUS_COMPLETED if success else STATUS_FAILED
    job.completed_at = clock.now_utc()
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


def purge_old_processor_jobs(
    db: Session,
    retention_days: int,
    *,
    clock: AuthoritativeClock,
) -> int:
    """
    Delete completed/failed processor jobs whose completed_at is older than retention_days.

    processor_runs are cascade-deleted with their job. Does not touch pending/running jobs
    or processor_outputs (those are current metadata, not history).
    Returns the number of jobs deleted.
    """
    if retention_days <= 0:
        return 0
    cutoff = clock.now_utc() - timedelta(days=retention_days)
    # Delete in a subquery to avoid loading rows; CASCADE removes processor_runs
    deleted = (
        db.query(ProcessorJob)
        .filter(
            ProcessorJob.status.in_([STATUS_COMPLETED, STATUS_FAILED]),
            ProcessorJob.completed_at.isnot(None),
            ProcessorJob.completed_at < cutoff,
        )
        .delete(synchronize_session="fetch")
    )
    if deleted:
        logger.info(
            "processor_jobs_purged",
            deleted=deleted,
            retention_days=retention_days,
            cutoff=cutoff.isoformat(),
        )
    return deleted


def enqueue_processor_jobs(
    asset_ids: list[uuid.UUID],
    processor_ids: list[str],
    *,
    db: object = None,
) -> None:
    """
    Enqueue one job per (target_type, asset_id) for each distinct target_type from processor_ids.

    For each asset_id and each target_type from the collection's processors (via get_capability),
    call enqueue(). Deduplication ensures at most one pending/running job per (target_type, target_id).
    """
    from .processor_capability import get_capability

    if not db or not asset_ids:
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
    # Log only for batches to avoid flooding when ingest enqueues one asset at a time
    if len(asset_ids) > 1:
        logger.debug(
            "enqueue_processor_jobs",
            asset_count=len(asset_ids),
            target_types=list(target_types),
        )
