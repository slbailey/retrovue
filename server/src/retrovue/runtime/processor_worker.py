"""
Processor job worker: claim jobs from the queue and run the processor runtime.

Contract: ProcessorJobQueueContract. One transaction to claim (and set running),
then execute and complete in a separate transaction.
"""

from __future__ import annotations

import time

import structlog

from ..catalog.processor_jobs import claim_next_job, complete_job, purge_old_processor_jobs
from ..catalog.processor_runtime import execute_job
from ..domain.entities import ProcessorJob
from ..infra.settings import settings
from ..infra.uow import session

logger = structlog.get_logger(__name__)


def run_once() -> bool:
    """
    Claim one job, execute it, mark completed or failed. Returns True if a job was processed.
    """
    job_id = None
    target_type = None
    target_id = None
    with session() as db:
        job = claim_next_job(db)
        if job is not None:
            job_id = job.id
            target_type = job.target_type
            target_id = job.target_id
    if job_id is None:
        return False
    try:
        with session() as db:
            job = db.get(ProcessorJob, job_id)
            if job is not None:
                execute_job(db, job)
            complete_job(db, job_id, True)
        logger.info(
            "processor_job_completed",
            job_id=str(job_id),
            target_type=target_type,
            target_id=str(target_id) if target_id else None,
        )
        return True
    except Exception as e:
        logger.exception("processor_job_failed", job_id=str(job_id), error=str(e))
        with session() as db:
            complete_job(db, job_id, False, error_message=str(e))
        return True


def run_loop(iterations: int | None = None, *, poll: bool = False, interval: int = 30) -> int:
    """
    Process jobs until the queue is empty or iterations is reached.
    Runs a purge of old completed/failed jobs once at start if processor_job_retention_days > 0.

    When poll=True, sleeps for `interval` seconds after draining the queue and
    re-checks instead of exiting.  This prevents systemd restart churn when the
    queue is transiently empty.

    Returns the number of jobs processed (only reachable when poll=False or
    iterations is set).
    """
    if settings.processor_job_retention_days > 0:
        try:
            with session() as db:
                purge_old_processor_jobs(db, settings.processor_job_retention_days)
        except Exception as e:
            logger.warning("processor_job_purge_skipped", error=str(e))
    count = 0
    while True:
        if iterations is not None and count >= iterations:
            break
        if not run_once():
            if poll:
                logger.debug("worker_poll_sleeping", interval=interval)
                time.sleep(interval)
                continue
            break
        count += 1
    return count
