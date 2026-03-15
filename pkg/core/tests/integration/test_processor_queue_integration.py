"""
Integration test: reconciliation → enqueue → worker.

Contract: Phase 3 task 8. With ENABLE_PROCESSOR_QUEUE true, enqueue leaves pending jobs;
worker run processes them (completed or failed depending on asset/file).
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from retrovue.catalog.processor_jobs import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    enqueue,
    enqueue_processor_jobs,
)
from retrovue.domain.entities import ProcessorJob
from retrovue.infra.uow import session


@pytest.mark.contract
def test_enqueue_leaves_pending_job():
    """With enable_processor_queue true, enqueue_processor_jobs creates pending rows."""
    with patch("retrovue.infra.settings.settings") as mock_settings:
        mock_settings.enable_processor_queue = True
        target_id = uuid.uuid4()
        with session() as db:
            enqueue_processor_jobs([target_id], ["ffprobe"], db=db)
            rows = db.query(ProcessorJob).filter(
                ProcessorJob.target_id == target_id,
                ProcessorJob.status == "pending",
            ).all()
        assert len(rows) >= 1


@pytest.mark.contract
def test_worker_claim_execute_complete_cycle():
    """Enqueue one job, run worker once; job ends up completed or failed (no duplicate)."""
    from retrovue.catalog.processor_jobs import claim_next_job, complete_job
    from retrovue.runtime.processor_worker import run_once

    # Drain so we only have our job
    for _ in range(100):
        with session() as db:
            j = claim_next_job(db)
            if j is None:
                break
            complete_job(db, j.id, True)

    target_id = uuid.uuid4()
    job_id = None
    with session() as db:
        enqueue(db, "ASSET", target_id)
        row = db.query(ProcessorJob).filter(
            ProcessorJob.target_id == target_id,
            ProcessorJob.status == "pending",
        ).first()
        assert row is not None
        job_id = row.id

    run_once()

    final_status = None
    with session() as db:
        row = db.get(ProcessorJob, job_id)
        if row:
            final_status = row.status
    assert final_status is not None
    assert final_status in (STATUS_COMPLETED, STATUS_FAILED)
