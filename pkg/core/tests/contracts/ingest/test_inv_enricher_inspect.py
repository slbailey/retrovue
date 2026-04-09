"""
Contract tests: INV-ENRICHER-OBSERVABILITY-001 (inspect surface)

The asset inspect usecase and enrichment API endpoint MUST expose
per-enricher status for any asset, consuming get_enrichment_progress().

CLI and API MUST delegate to usecases (INV-CLI-NO-BUSINESS-LOGIC-001,
INV-API-NO-BUSINESS-LOGIC-001).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from retrovue.catalog.enrichment_progress import EnricherStatus
from retrovue.domain.entities import Asset, Container, EnricherRun, Source


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_source(name: str = "Test Plex") -> Source:
    src = MagicMock(spec=Source)
    src.id = uuid.uuid4()
    src.name = name
    return src


def _make_container(source: Source, name: str = "Movies") -> Container:
    c = MagicMock(spec=Container)
    c.uuid = uuid.uuid4()
    c.source_id = source.id
    c.name = name
    c.source = source
    return c


def _make_asset(container: Container) -> Asset:
    a = MagicMock(spec=Asset)
    a.uuid = uuid.uuid4()
    a.container_id = container.uuid
    a.source_id = container.source_id
    a.uri = "plex://server/library/1/movie.mkv"
    a.canonical_uri = "/media/movies/movie.mkv"
    a.state = "ready"
    a.approved_for_broadcast = True
    a.duration_ms = 7200000
    a.container = container
    return a


def _make_enricher_statuses() -> dict[str, EnricherStatus]:
    now = datetime.now(UTC)
    return {
        "ffprobe": EnricherStatus(
            enricher_name="ffprobe",
            status="succeeded",
            enricher_version="1.0.0",
            started_at=now,
            completed_at=now,
            error=None,
            result_payload={"duration_ms": 7200000},
        ),
        "interstitial_type": EnricherStatus(
            enricher_name="interstitial_type",
            status="succeeded",
            enricher_version="1.0.0",
            started_at=now,
            completed_at=now,
            error=None,
            result_payload={},
        ),
        "loudness": EnricherStatus(
            enricher_name="loudness",
            status="failed",
            enricher_version="1.0.0",
            started_at=now,
            completed_at=None,
            error="ffprobe binary not found",
            result_payload=None,
        ),
    }


# ---------------------------------------------------------------------------
# Usecase: get_asset_inspect
# ---------------------------------------------------------------------------

class TestGetAssetInspect:
    """The asset inspect usecase returns asset state + per-enricher status."""

    def test_returns_asset_fields(self) -> None:
        """Inspect result includes asset uuid, state, approval, source, container."""
        from retrovue.usecases.asset_inspect import get_asset_inspect

        source = _make_source("Main Plex")
        container = _make_container(source, "Movies")
        asset = _make_asset(container)

        db = MagicMock()
        db.get.return_value = asset

        # Mock enrichment progress to return empty
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "retrovue.usecases.asset_inspect.get_enrichment_progress",
                lambda _db, _aid: {},
            )
            result = get_asset_inspect(db, asset_uuid=str(asset.uuid))

        assert result["uuid"] == str(asset.uuid)
        assert result["state"] == "ready"
        assert result["approved_for_broadcast"] is True
        assert result["source_name"] == "Main Plex"
        assert result["container_name"] == "Movies"

    def test_returns_enricher_list(self) -> None:
        """Inspect result includes per-enricher status records."""
        from retrovue.usecases.asset_inspect import get_asset_inspect

        source = _make_source()
        container = _make_container(source)
        asset = _make_asset(container)
        statuses = _make_enricher_statuses()

        db = MagicMock()
        db.get.return_value = asset

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "retrovue.usecases.asset_inspect.get_enrichment_progress",
                lambda _db, _aid: statuses,
            )
            result = get_asset_inspect(db, asset_uuid=str(asset.uuid))

        enrichers = result["enrichers"]
        assert len(enrichers) == 3
        names = {e["name"] for e in enrichers}
        assert names == {"ffprobe", "interstitial_type", "loudness"}

    def test_enricher_record_shape(self) -> None:
        """Each enricher record contains name, status, version, timestamps, error."""
        from retrovue.usecases.asset_inspect import get_asset_inspect

        source = _make_source()
        container = _make_container(source)
        asset = _make_asset(container)
        statuses = _make_enricher_statuses()

        db = MagicMock()
        db.get.return_value = asset

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "retrovue.usecases.asset_inspect.get_enrichment_progress",
                lambda _db, _aid: statuses,
            )
            result = get_asset_inspect(db, asset_uuid=str(asset.uuid))

        ffprobe = next(e for e in result["enrichers"] if e["name"] == "ffprobe")
        assert ffprobe["status"] == "succeeded"
        assert ffprobe["version"] == "1.0.0"
        assert ffprobe["started_at"] is not None
        assert ffprobe["completed_at"] is not None
        assert ffprobe["error"] is None

        loudness = next(e for e in result["enrichers"] if e["name"] == "loudness")
        assert loudness["status"] == "failed"
        assert loudness["error"] == "ffprobe binary not found"

    def test_enrichment_summary(self) -> None:
        """Inspect result includes enrichment_summary with completed/total counts."""
        from retrovue.usecases.asset_inspect import get_asset_inspect

        source = _make_source()
        container = _make_container(source)
        asset = _make_asset(container)
        statuses = _make_enricher_statuses()

        db = MagicMock()
        db.get.return_value = asset

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "retrovue.usecases.asset_inspect.get_enrichment_progress",
                lambda _db, _aid: statuses,
            )
            result = get_asset_inspect(db, asset_uuid=str(asset.uuid))

        summary = result["enrichment_summary"]
        assert summary["total"] == 3
        assert summary["completed"] == 2  # ffprobe + interstitial_type succeeded

    def test_missing_asset_raises(self) -> None:
        """ValueError raised for nonexistent asset UUID."""
        from retrovue.usecases.asset_inspect import get_asset_inspect

        db = MagicMock()
        db.get.return_value = None

        with pytest.raises(ValueError, match="Asset not found"):
            get_asset_inspect(db, asset_uuid=str(uuid.uuid4()))

    def test_invalid_uuid_raises(self) -> None:
        """ValueError raised for malformed UUID string."""
        from retrovue.usecases.asset_inspect import get_asset_inspect

        db = MagicMock()
        with pytest.raises(ValueError, match="Asset not found"):
            get_asset_inspect(db, asset_uuid="not-a-uuid")


# ---------------------------------------------------------------------------
# Enrichment summary helper (for wiring into existing surfaces)
# ---------------------------------------------------------------------------

class TestGetEnrichmentSummary:
    """The enrichment summary helper returns completed/total counts."""

    def test_summary_shape(self) -> None:
        from retrovue.usecases.asset_inspect import get_enrichment_summary

        statuses = _make_enricher_statuses()

        db = MagicMock()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "retrovue.usecases.asset_inspect.get_enrichment_progress",
                lambda _db, _aid: statuses,
            )
            summary = get_enrichment_summary(db, asset_id=uuid.uuid4())

        assert summary["total"] == 3
        assert summary["completed"] == 2

    def test_empty_enrichment(self) -> None:
        from retrovue.usecases.asset_inspect import get_enrichment_summary

        db = MagicMock()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "retrovue.usecases.asset_inspect.get_enrichment_progress",
                lambda _db, _aid: {},
            )
            summary = get_enrichment_summary(db, asset_id=uuid.uuid4())

        assert summary["total"] == 0
        assert summary["completed"] == 0
