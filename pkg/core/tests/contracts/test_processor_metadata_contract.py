"""
Contract tests for ProcessorMetadataContract.

Contract: docs/contracts/core/ProcessorMetadataContract_v0.1.md
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from retrovue.catalog.processor_runtime import execute_job
from retrovue.domain.entities import (
    Asset,
    Collection,
    ProcessorJob,
    ProcessorOutput,
    Source,
)
from retrovue.infra.uow import session


def _make_source_and_collection(db):
    src = Source(
        external_id=f"test-meta-{uuid.uuid4().hex[:12]}",
        name="Test Source",
        type="filesystem",
    )
    db.add(src)
    db.flush()
    coll = Collection(
        source_id=src.id,
        external_id=f"test-coll-{uuid.uuid4().hex[:12]}",
        name="Test Collection",
    )
    db.add(coll)
    db.flush()
    return src, coll


def _make_asset(db, collection, source, *, uri="/nonexistent/path.mp4", approved_for_broadcast=False, duration_ms=None):
    asset = Asset(
        uuid=uuid.uuid4(),
        collection_uuid=collection.uuid,
        source_id=source.id,
        canonical_key="test/asset.mp4",
        canonical_key_hash="a" * 64,
        uri=uri,
        canonical_uri=uri,
        size=1000,
        state="new",
        approved_for_broadcast=approved_for_broadcast,
        operator_verified=False,
        discovered_at=datetime.now(UTC),
        duration_ms=duration_ms,
    )
    db.add(asset)
    db.flush()
    return asset


class TestProcessorMetadataContract:
    """Verify ProcessorMetadataContract guarantees."""

    def test_processor_does_not_overwrite_operator_owned_field(self):
        """Processor does not overwrite operator-owned fields (e.g. approved_for_broadcast)."""
        with session() as db:
            src, coll = _make_source_and_collection(db)
            asset = _make_asset(db, coll, src, approved_for_broadcast=True, duration_ms=1000)
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

        approved = None
        with session() as db:
            row = db.get(Asset, asset_id)
            if row:
                approved = row.approved_for_broadcast
        assert approved is True

    def test_structured_metadata_in_structured_tables(self):
        """Core-required metadata (e.g. duration_ms, video_codec) is in structured tables/columns."""
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
            item.raw_labels = list(getattr(item, "raw_labels", [])) + ["duration_ms:6000"]
            item.probed = dict(getattr(item, "probed", None) or {})
            item.probed["duration_ms"] = 6000
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
        with session() as db:
            row = db.get(Asset, asset_id)
            if row:
                dur = row.duration_ms
        assert dur == 6000

    def test_flexible_output_in_processor_outputs(self):
        """Flexible processor output is stored in processor_outputs (processor_id, target, payload_json)."""
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
            item.raw_labels = list(getattr(item, "raw_labels", [])) + ["duration_ms:7000"]
            item.probed = dict(getattr(item, "probed", None) or {})
            item.probed["duration_ms"] = 7000
            item.probed["custom_key"] = "custom_value"
            return item

        class FakeEnricher:
            def enrich(self, item):
                return _fake_enrich(item)

        fake_ffprobe = type("FakeFfprobe", (FakeEnricher,), {})
        with patch("retrovue.catalog.processor_runtime.ENRICHERS", {"ffprobe": fake_ffprobe, "loudness": fake_ffprobe}):
            with session() as db:
                job = db.get(ProcessorJob, job_id)
                execute_job(db, job)

        outputs = []
        with session() as db:
            rows = db.query(ProcessorOutput).filter(
                ProcessorOutput.target_id == asset_id,
            ).all()
            for r in rows:
                outputs.append({"processor_id": r.processor_id, "payload_json": dict(r.payload_json), "created_at": r.created_at})
        assert len(outputs) >= 1
        payloads_with_probed = [o for o in outputs if o["payload_json"].get("probed")]
        assert len(payloads_with_probed) >= 1
        assert payloads_with_probed[0]["payload_json"]["probed"].get("custom_key") == "custom_value"
        assert payloads_with_probed[0]["created_at"] is not None

    def test_processor_may_update_own_fields_when_media_changes(self):
        """Processors may update fields they own when media or fingerprint changes."""
        with session() as db:
            src, coll = _make_source_and_collection(db)
            asset = _make_asset(db, coll, src, duration_ms=2000)
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
            item.raw_labels = list(getattr(item, "raw_labels", [])) + ["duration_ms:8000"]
            item.probed = dict(getattr(item, "probed", None) or {})
            item.probed["duration_ms"] = 8000
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
        with session() as db:
            row = db.get(Asset, asset_id)
            if row:
                dur = row.duration_ms
        assert dur == 8000
