"""
Contract tests: INV-ENRICHER-OBSERVABILITY-001
Every enricher execution MUST produce a queryable record containing:
enricher name, asset ID, execution status, enricher version, and timestamps.

Enricher progress MUST be retrievable per-asset with per-enricher granularity.

Tests are deterministic (no wall-clock sleep, no network).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from retrovue.domain.entities import EnricherRun


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_enricher_run(
    asset_id: uuid.UUID,
    enricher_name: str,
    *,
    status: str = "succeeded",
    version: str = "1.0",
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    error: str | None = None,
    result_payload: dict[str, Any] | None = None,
) -> EnricherRun:
    """Create an EnricherRun instance for testing."""
    now = datetime.now(UTC)
    return EnricherRun(
        id=uuid.uuid4(),
        asset_id=asset_id,
        enricher_name=enricher_name,
        enricher_version=version,
        status=status,
        started_at=started_at or now,
        completed_at=completed_at or now,
        error=error,
        result_payload=result_payload,
    )


class TestInvEnricherObservability001:
    """INV-ENRICHER-OBSERVABILITY-001: per-enricher execution records are queryable."""

    def test_enricher_run_has_required_fields(self) -> None:
        """Each EnricherRun record contains enricher name, asset ID, status, version, timestamps."""
        asset_id = uuid.uuid4()
        run = _make_enricher_run(asset_id, "ffprobe", version="1.0")

        assert run.asset_id == asset_id
        assert run.enricher_name == "ffprobe"
        assert run.status == "succeeded"
        assert run.enricher_version == "1.0"
        assert run.started_at is not None
        assert run.completed_at is not None

    def test_one_record_per_enricher_per_asset(self) -> None:
        """A pipeline with multiple enrichers produces one record per enricher per asset."""
        asset_id = uuid.uuid4()
        runs = [
            _make_enricher_run(asset_id, "ffprobe"),
            _make_enricher_run(asset_id, "loudness"),
            _make_enricher_run(asset_id, "interstitial_type"),
        ]

        enricher_names = {r.enricher_name for r in runs}
        assert enricher_names == {"ffprobe", "loudness", "interstitial_type"}
        assert all(r.asset_id == asset_id for r in runs)

    def test_records_independently_queryable_by_enricher_name(self) -> None:
        """Retrieving FFprobe status does not require loading the entire ProcessorJob."""
        asset_id = uuid.uuid4()
        runs = [
            _make_enricher_run(asset_id, "ffprobe", status="succeeded"),
            _make_enricher_run(asset_id, "loudness", status="failed", error="timeout"),
        ]

        # Filter by enricher_name — independent query
        ffprobe_runs = [r for r in runs if r.enricher_name == "ffprobe"]
        assert len(ffprobe_runs) == 1
        assert ffprobe_runs[0].status == "succeeded"

        loudness_runs = [r for r in runs if r.enricher_name == "loudness"]
        assert len(loudness_runs) == 1
        assert loudness_runs[0].status == "failed"
        assert loudness_runs[0].error == "timeout"

    def test_failed_enricher_records_error(self) -> None:
        """Failed enricher execution records error message."""
        asset_id = uuid.uuid4()
        run = _make_enricher_run(
            asset_id,
            "loudness",
            status="failed",
            error="ffprobe not found",
        )

        assert run.status == "failed"
        assert run.error == "ffprobe not found"
        assert run.enricher_name == "loudness"

    def test_result_payload_stored(self) -> None:
        """Succeeded enricher records include result payload."""
        asset_id = uuid.uuid4()
        payload = {"duration_ms": 120000, "video_codec": "h264"}
        run = _make_enricher_run(
            asset_id,
            "ffprobe",
            result_payload=payload,
        )

        assert run.result_payload == payload

    def test_status_values_are_valid(self) -> None:
        """Status must be one of: pending, running, succeeded, failed."""
        asset_id = uuid.uuid4()
        valid_statuses = {"pending", "running", "succeeded", "failed"}
        for status in valid_statuses:
            run = _make_enricher_run(asset_id, "ffprobe", status=status)
            assert run.status == status

    def test_enrichment_progress_query(self) -> None:
        """get_enrichment_progress returns per-enricher status dict."""
        from retrovue.catalog.enrichment_progress import EnricherStatus, get_enrichment_progress

        asset_id = uuid.uuid4()
        now = datetime.now(UTC)

        # Mock DB session to return EnricherRun rows
        mock_run_ffprobe = _make_enricher_run(
            asset_id, "ffprobe", version="1.0", started_at=now, completed_at=now
        )
        mock_run_loudness = _make_enricher_run(
            asset_id, "loudness", version="1.0", status="failed",
            started_at=now, completed_at=now, error="timeout"
        )

        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            mock_run_ffprobe,
            mock_run_loudness,
        ]

        progress = get_enrichment_progress(db, asset_id)

        assert "ffprobe" in progress
        assert "loudness" in progress
        assert progress["ffprobe"].status == "succeeded"
        assert progress["ffprobe"].enricher_version == "1.0"
        assert progress["loudness"].status == "failed"
        assert progress["loudness"].error == "timeout"

    def test_execute_job_creates_enricher_run_records(self) -> None:
        """execute_job MUST create an EnricherRun record for each enricher it dispatches."""
        from retrovue.catalog.processor_runtime import execute_job
        from retrovue.domain.entities import Asset, EnricherRun

        asset_id = uuid.uuid4()
        asset = MagicMock(spec=Asset)
        asset.uuid = asset_id
        asset.uri = "/test/video.mp4"
        asset.canonical_uri = "/test/video.mp4"
        asset.size = 1000
        asset.is_deleted = False
        asset.state = "enriching"
        asset.duration_ms = None
        asset.container_id = None

        job = SimpleNamespace(
            id=uuid.uuid4(),
            target_id=asset_id,
            target_type="MEDIA",
        )

        # Track all objects added to the session
        added_objects: list[Any] = []
        db = MagicMock()
        db.get.return_value = asset
        db.add.side_effect = lambda obj: added_objects.append(obj)

        # Mock enricher that returns a simple enriched item
        mock_enricher = MagicMock()
        mock_item = MagicMock()
        mock_item.raw_labels = ["duration_ms:120000"]
        mock_item.probed = {"duration_ms": 120000}
        mock_item.editorial = {}
        mock_enricher.enrich.return_value = mock_item

        with patch(
            "retrovue.catalog.processor_runtime.get_processors_for_target",
            return_value=["ffprobe"],
        ), patch(
            "retrovue.catalog.processor_runtime._enricher_instance",
            return_value=mock_enricher,
        ), patch(
            "retrovue.catalog.processor_runtime.persist_asset_metadata",
        ):
            execute_job(db, job)

        # Assert that at least one EnricherRun was added
        enricher_runs = [obj for obj in added_objects if isinstance(obj, EnricherRun)]
        assert len(enricher_runs) >= 1, (
            "INV-ENRICHER-OBSERVABILITY-001 violated: execute_job did not create "
            "any EnricherRun records"
        )

        run = enricher_runs[0]
        assert run.asset_id == asset_id
        assert run.enricher_name == "ffprobe"
        assert run.status == "succeeded"
        assert run.enricher_version != ""
        assert run.started_at is not None
        assert run.completed_at is not None
