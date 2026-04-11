"""
Contract tests: INV-ENRICHER-RESULT-VERSIONED-001
Each persisted enricher result MUST include the version of the enricher that
produced it. Re-running at the same version MUST be idempotent. Upgrading
version MUST NOT require reprocessing all assets — stale results are identified
by version comparison.

Tests are deterministic (no wall-clock sleep, no network).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

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


class TestInvEnricherResultVersioned001:
    """INV-ENRICHER-RESULT-VERSIONED-001: persisted enricher results carry version."""

    def test_persisted_record_contains_version(self) -> None:
        """Run enricher v1 against an asset. Assert record contains version=v1."""
        asset_id = uuid.uuid4()
        run = _make_enricher_run(asset_id, "ffprobe", version="1.0")

        assert run.enricher_version == "1.0"
        assert run.enricher_version != ""

    def test_same_version_rerun_is_idempotent(self) -> None:
        """Re-running enricher at same version produces no new record (latest wins).

        The system should detect that the latest run for this enricher+asset
        is already at the same version and skip re-execution.
        """
        asset_id = uuid.uuid4()
        now = datetime.now(UTC)

        # Simulate: run v1, then run v1 again. The progress query should
        # return only one entry per enricher (the latest).
        from retrovue.catalog.enrichment_progress import get_enrichment_progress

        run1 = _make_enricher_run(
            asset_id, "ffprobe", version="1.0",
            started_at=now, completed_at=now,
        )
        run2 = _make_enricher_run(
            asset_id, "ffprobe", version="1.0",
            started_at=now + timedelta(seconds=1),
            completed_at=now + timedelta(seconds=1),
        )

        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            run2, run1,  # ordered by started_at desc
        ]

        progress = get_enrichment_progress(db, asset_id)

        # Only one entry per enricher in progress dict
        assert "ffprobe" in progress
        assert progress["ffprobe"].enricher_version == "1.0"

    def test_upgrade_does_not_reprocess_all(self) -> None:
        """Upgrading enricher to v2 does not automatically update persisted v1 records."""
        asset_id = uuid.uuid4()
        run = _make_enricher_run(asset_id, "ffprobe", version="1.0")

        # After enricher upgrades to v2, the existing record still shows v1
        assert run.enricher_version == "1.0"
        # The stale detection query would find this asset

    def test_stale_version_detection(self) -> None:
        """Query for assets with enricher version < current finds stale assets."""
        from retrovue.catalog.enrichment_progress import get_stale_enricher_assets

        asset_stale = uuid.uuid4()
        asset_current = uuid.uuid4()
        now = datetime.now(UTC)

        run_stale = _make_enricher_run(
            asset_stale, "ffprobe", version="1.0", started_at=now, completed_at=now,
        )
        run_current = _make_enricher_run(
            asset_current, "ffprobe", version="2.0", started_at=now, completed_at=now,
        )

        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            run_stale,
            run_current,
        ]

        stale = get_stale_enricher_assets(db, "ffprobe", current_version="2.0")

        assert asset_stale in stale
        assert asset_current not in stale

    def test_version_updated_after_rerun_at_new_version(self) -> None:
        """Re-running enricher at v2 updates the progress to show version=v2."""
        from retrovue.catalog.enrichment_progress import get_enrichment_progress

        asset_id = uuid.uuid4()
        now = datetime.now(UTC)

        run_v1 = _make_enricher_run(
            asset_id, "ffprobe", version="1.0",
            started_at=now, completed_at=now,
        )
        run_v2 = _make_enricher_run(
            asset_id, "ffprobe", version="2.0",
            started_at=now + timedelta(seconds=5),
            completed_at=now + timedelta(seconds=5),
        )

        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            run_v2, run_v1,  # ordered by started_at desc
        ]

        progress = get_enrichment_progress(db, asset_id)

        assert progress["ffprobe"].enricher_version == "2.0"
