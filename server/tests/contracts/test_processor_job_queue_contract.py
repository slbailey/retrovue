"""
Contract tests for ProcessorJobQueueContract.

Contract: docs/contracts/core/ProcessorJobQueueContract_v0.1.md
Uses real DB session (test engine) when available; processor_jobs table must exist.
"""

from __future__ import annotations

from retrovue.runtime.clock import SystemClock

import uuid

import pytest

from retrovue.catalog.processor_jobs import (
    PRIORITY_HIGH,
    PRIORITY_LOW,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    claim_next_job,
    complete_job,
    enqueue,
    retry_job,
)
from retrovue.infra.uow import session


class TestProcessorJobQueueContract:
    """Verify ProcessorJobQueueContract guarantees."""

    def test_job_identity_unique(self):
        """Job is uniquely identified by (target_type, target_id); no duplicate jobs per target."""
        target_type = "ASSET"
        target_id = uuid.uuid4()
        id1, id2 = None, None
        with session() as db:
            j1 = enqueue(db, target_type, target_id, priority=PRIORITY_LOW)
            j2 = enqueue(db, target_type, target_id, priority=PRIORITY_LOW)
            id1 = j1.id
            id2 = j2.id
        assert id1 is not None
        assert id2 is not None
        assert id1 == id2
        with session() as db:
            from retrovue.domain.entities import ProcessorJob
            rows = db.query(ProcessorJob).filter(
                ProcessorJob.target_type == target_type,
                ProcessorJob.target_id == target_id,
            ).all()
        assert len(rows) == 1

    def test_job_queue_deduplication(self):
        """Enqueue for existing job does not create duplicate; may update priority only."""
        target_type = "ASSET"
        target_id = uuid.uuid4()
        id1, id2, prio2 = None, None, None
        with session() as db:
            j1 = enqueue(db, target_type, target_id, priority=PRIORITY_LOW)
            j2 = enqueue(db, target_type, target_id, priority=PRIORITY_HIGH)
            id1 = j1.id
            id2 = j2.id
            prio2 = j2.priority
        assert id1 == id2
        assert prio2 == PRIORITY_HIGH

    def _drain_pending(self, max_jobs: int = 500):
        """Drain all pending jobs so following tests see an empty queue."""
        for _ in range(max_jobs):
            with session() as db:
                j = claim_next_job(db, clock=SystemClock())
                if j is None:
                    return
                complete_job(db, j.id, True, clock=SystemClock())

    def test_job_lifecycle_pending_to_running_to_completed(self):
        """Job can transition pending → running → completed."""
        self._drain_pending()
        target_type = "ASSET"
        target_id = uuid.uuid4()
        job_id = None
        with session() as db:
            job = enqueue(db, target_type, target_id)
            job_id = job.id
            assert job.status == STATUS_PENDING
        claimed_id = None
        with session() as db:
            claimed = claim_next_job(db, clock=SystemClock())
            if claimed:
                claimed_id = claimed.id
                _ = claimed.status  # read while session active
        assert claimed_id is not None
        assert claimed_id == job_id
        with session() as db:
            complete_job(db, job_id, True, clock=SystemClock())
        final_status = None
        with session() as db:
            from retrovue.domain.entities import ProcessorJob
            row = db.get(ProcessorJob, job_id)
            if row:
                final_status = row.status
        assert final_status == STATUS_COMPLETED

    def test_job_lifecycle_pending_to_running_to_failed(self):
        """Job can transition pending → running → failed."""
        self._drain_pending()
        target_type = "ASSET"
        target_id = uuid.uuid4()
        job_id = None
        with session() as db:
            job = enqueue(db, target_type, target_id)
            job_id = job.id
        claimed_id = None
        with session() as db:
            claimed = claim_next_job(db, clock=SystemClock())
            if claimed:
                claimed_id = claimed.id
                assert claimed.status == STATUS_RUNNING
        with session() as db:
            complete_job(db, claimed_id, False, clock=SystemClock(), error_message="test failure")
        status_failed = None
        err_msg = None
        with session() as db:
            from retrovue.domain.entities import ProcessorJob
            row = db.get(ProcessorJob, job_id)
            if row:
                status_failed = row.status
                err_msg = row.error_message
        assert status_failed == STATUS_FAILED
        assert err_msg == "test failure"

    def test_job_retry_resets_to_pending_preserves_identity(self):
        """Retry sets status to pending and preserves (target_type, target_id)."""
        self._drain_pending()
        target_type = "ASSET"
        target_id = uuid.uuid4()
        job_id = None
        with session() as db:
            job = enqueue(db, target_type, target_id)
            job_id = job.id
        with session() as db:
            claimed = claim_next_job(db, clock=SystemClock())
            if claimed:
                complete_job(db, claimed.id, False, clock=SystemClock())
        with session() as db:
            retry_job(db, job_id)
        row_status, row_tt, row_tid, row_started, row_err = None, None, None, None, None
        with session() as db:
            from retrovue.domain.entities import ProcessorJob
            row = db.get(ProcessorJob, job_id)
            if row:
                row_status = row.status
                row_tt = row.target_type
                row_tid = row.target_id
                row_started = row.started_at
                row_err = row.error_message
        assert row_status == STATUS_PENDING
        assert row_tt == target_type
        assert row_tid == target_id
        assert row_started is None
        assert row_err is None

    def test_job_priority_ordering(self):
        """Higher-priority jobs are claimed before lower-priority jobs."""
        tid_low = uuid.uuid4()
        tid_high = uuid.uuid4()
        with session() as db:
            enqueue(db, "ASSET", tid_low, priority=PRIORITY_LOW)
            enqueue(db, "ASSET", tid_high, priority=PRIORITY_HIGH)
        first_tid, first_prio = None, None
        with session() as db:
            first = claim_next_job(db, clock=SystemClock())
            if first:
                first_tid = first.target_id
                first_prio = first.priority
        assert first is not None
        assert first_tid == tid_high
        assert first_prio == PRIORITY_HIGH
        # drain second job so later tests get a clean queue
        with session() as db:
            second = claim_next_job(db, clock=SystemClock())
            if second:
                complete_job(db, second.id, True, clock=SystemClock())

    def test_worker_claims_one_job_at_a_time(self):
        """Only one worker can claim a given job; second claim returns different job or none."""
        self._drain_pending()
        t1 = uuid.uuid4()
        t2 = uuid.uuid4()
        with session() as db:
            enqueue(db, "ASSET", t1)
            enqueue(db, "ASSET", t2)
        first_id, second_id = None, None
        with session() as db:
            first = claim_next_job(db, clock=SystemClock())
            if first:
                first_id = first.id
        with session() as db:
            second = claim_next_job(db, clock=SystemClock())
            if second:
                second_id = second.id
        assert first is not None
        assert second is not None
        assert second_id != first_id  # each claim returned a different job
        third = None
        with session() as db:
            third = claim_next_job(db, clock=SystemClock())
        assert third is None
        # drain so queue is clean
        with session() as db:
            complete_job(db, first_id, True, clock=SystemClock())
            complete_job(db, second_id, True, clock=SystemClock())

    def test_observable_state_queued_running_completed_failed(self):
        """Queue exposes observable state for queued, running, completed, and failed jobs."""
        from retrovue.domain.entities import ProcessorJob

        self._drain_pending()
        target_id = uuid.uuid4()
        job_id = None
        with session() as db:
            job = enqueue(db, "ASSET", target_id)
            job_id = job.id
            row = db.get(ProcessorJob, job_id)
            status_pending = row.status
        assert status_pending == STATUS_PENDING
        with session() as db:
            claimed = claim_next_job(db, clock=SystemClock())
            assert claimed is not None and claimed.id == job_id
            status_running = claimed.status
        assert status_running == STATUS_RUNNING
        with session() as db:
            complete_job(db, job_id, True, clock=SystemClock())
            row = db.get(ProcessorJob, job_id)
            status_completed = row.status
        assert status_completed == STATUS_COMPLETED
