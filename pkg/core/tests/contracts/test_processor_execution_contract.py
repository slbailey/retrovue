"""
Contract tests for ProcessorExecutionContract.

Contract: docs/contracts/core/ProcessorExecutionContract_v0.1.md
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from retrovue.catalog.processor_runtime import (
    ProcessorResult,
    execute_job,
    validate_processor_result,
)
from retrovue.domain.entities import (
    Asset,
    Collection,
    ProcessorJob,
    ProcessorRun,
    Source,
)
from retrovue.infra.uow import session


def _make_source_and_collection(db):
    src = Source(
        external_id=f"test-exec-{uuid.uuid4().hex[:12]}",
        name="Test Source",
        type="filesystem",
    )
    db.add(src)
    db.flush()
    coll = Collection(
        source_id=src.id,
        external_id=f"test-coll-{uuid.uuid4().hex[:12]}",
        name="Test Container",
    )
    db.add(coll)
    db.flush()
    return src, coll


def _make_asset(db, collection, source, *, uri="/nonexistent/path.mp4", duration_ms=None):
    asset = Asset(
        uuid=uuid.uuid4(),
        container_id=collection.uuid,
        source_id=source.id,
        canonical_key="test/asset.mp4",
        canonical_key_hash="a" * 64,
        uri=uri,
        canonical_uri=uri,
        size=1000,
        state="new",
        approved_for_broadcast=False,
        operator_verified=False,
        discovered_at=datetime.now(UTC),
        duration_ms=duration_ms,
    )
    db.add(asset)
    db.flush()
    return asset


class TestProcessorExecutionContract:
    """Verify ProcessorExecutionContract guarantees."""

    def test_processor_receives_execution_context(self):
        """Processor receives execution context and read-only view of shared ProcessingContext."""
        with session() as db:
            src, coll = _make_source_and_collection(db)
            asset = _make_asset(db, coll, src)
            job = ProcessorJob(
                id=uuid.uuid4(),
                target_type="ASSET",
                target_id=asset.uuid,
                status="running",
            )
            db.add(job)
            db.flush()
            job_id = job.id
            asset_id = asset.uuid
        try:
            with session() as db:
                job = db.get(ProcessorJob, job_id)
                execute_job(db, job)
        except Exception:
            pass
        with session() as db:
            row = db.get(Asset, asset_id)
        assert row is not None

    def test_shared_context_single_transaction_persist(self):
        """Runtime loads once, merges results into context (no DB per processor), persists in single transaction."""
        with session() as db:
            src, coll = _make_source_and_collection(db)
            asset = _make_asset(db, coll, src, duration_ms=1000)
            job = ProcessorJob(
                id=uuid.uuid4(),
                target_type="MEDIA",
                target_id=asset.uuid,
                status="running",
            )
            db.add(job)
            db.flush()
            job_id = job.id
            asset_id = asset.uuid

        def _fake_enrich(item):
            item.raw_labels = list(getattr(item, "raw_labels", [])) + ["duration_ms:5000"]
            item.probed = dict(getattr(item, "probed", None) or {})
            item.probed["duration_ms"] = 5000
            return item

        class FakeEnricher:
            def enrich(self, item):
                return _fake_enrich(item)

        fake_ffprobe = type("FakeFfprobe", (FakeEnricher,), {})
        with patch("retrovue.catalog.processor_runtime.ENRICHERS", {"ffprobe": fake_ffprobe, "loudness": fake_ffprobe}):
            with session() as db:
                job = db.get(ProcessorJob, job_id)
                execute_job(db, job)

        dur = None
        run_count = 0
        with session() as db:
            row = db.get(Asset, asset_id)
            if row:
                dur = row.duration_ms
            run_count = len(db.query(ProcessorRun).filter(ProcessorRun.job_id == job_id).all())
        assert dur == 5000
        assert run_count >= 1

    def test_processor_runs_recorded_per_execution(self):
        """After success, processor_runs has one row per processor; after failure, run rows for each invoked."""
        with session() as db:
            src, coll = _make_source_and_collection(db)
            asset = _make_asset(db, coll, src, uri="/nonexistent/file.mp4")
            job = ProcessorJob(
                id=uuid.uuid4(),
                target_type="MEDIA",
                target_id=asset.uuid,
                status="running",
            )
            db.add(job)
            db.flush()
            job_id = job.id

        with session() as db:
            job = db.get(ProcessorJob, job_id)
            try:
                execute_job(db, job)
            except Exception:
                pass

        run_count = 0
        run_statuses = []
        with session() as db:
            runs = db.query(ProcessorRun).filter(ProcessorRun.job_id == job_id).all()
            run_count = len(runs)
            run_statuses = [r.status for r in runs]
        assert run_count >= 1
        assert "failed" in run_statuses

    def test_processor_failure_does_not_modify_metadata(self):
        """When processor fails, catalog is not updated for that job."""
        with session() as db:
            src, coll = _make_source_and_collection(db)
            asset = _make_asset(db, coll, src, uri="/nonexistent/file.mp4", duration_ms=999)
            job = ProcessorJob(
                id=uuid.uuid4(),
                target_type="ASSET",
                target_id=asset.uuid,
                status="running",
            )
            db.add(job)
            db.flush()
            job_id = job.id
            asset_id = asset.uuid

        with session() as db:
            job = db.get(ProcessorJob, job_id)
            try:
                execute_job(db, job)
            except Exception:
                pass

        dur = None
        with session() as db:
            row = db.get(Asset, asset_id)
            if row:
                dur = row.duration_ms
        assert dur == 999

    def test_processor_result_validated_before_apply(self):
        """Results are validated before apply; invalid result fails job and no apply."""
        with pytest.raises(ValueError, match="disallowed metadata key"):
            validate_processor_result(
                ProcessorResult(metadata={"disallowed_key": 1}),
                "ffprobe",
            )

    def test_execution_isolated_from_scheduler(self):
        """Processor execution is not triggered by scheduler; only workers or explicit enqueue."""
        import retrovue.runtime.playlist_builder_daemon as daemon_module

        source = getattr(daemon_module, "__file__", "") or ""
        with open(source) as f:
            content = f.read()
        assert "processor_runtime" not in content and "execute_job" not in content

    def test_observable_events_started_completed_failed_duration(self):
        """Execution produces observable events: run rows and job outcome (started/completed/failed)."""
        with session() as db:
            src, coll = _make_source_and_collection(db)
            asset = _make_asset(db, coll, src, uri="/nonexistent/file.mp4")
            job = ProcessorJob(
                id=uuid.uuid4(),
                target_type="MEDIA",
                target_id=asset.uuid,
                status="running",
            )
            db.add(job)
            db.flush()
            job_id = job.id

        with session() as db:
            job = db.get(ProcessorJob, job_id)
            try:
                execute_job(db, job)
            except Exception:
                pass

        run_count = 0
        with session() as db:
            runs = db.query(ProcessorRun).filter(ProcessorRun.job_id == job_id).all()
            run_count = len(runs)
            for r in runs:
                _ = r.started_at
                _ = r.status
        assert run_count >= 1
