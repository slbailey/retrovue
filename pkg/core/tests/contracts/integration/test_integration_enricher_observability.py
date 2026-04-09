"""
Contract: INV-ENRICHER-OBSERVABILITY-001, INV-ENRICHER-RESULT-VERSIONED-001

INTEGRATION TESTS for enricher observability — Phase 3 per-enricher tracking.

Exercises the REAL domain/usecase pipeline:
  EnricherRun entity → enrichment_progress query → asset_inspect usecase
  → REST API endpoint → CLI inspect command

Scenarios:
  4. Multi-enricher progress: FFprobe + Loudness tracked independently
  5. Enricher failure tracking: failed status with error persisted
  6. API endpoint: GET /api/catalog/assets/{uuid}/enrichment shape
  7. CLI inspect: human-readable enrichment table output

These tests use mock DB sessions that simulate real query chains
(filter → order_by → all), not trivial return_value mocks. The full
domain → usecase → boundary stack is exercised without a live database.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from retrovue.catalog.enrichment_progress import EnricherStatus, get_enrichment_progress
from retrovue.domain.entities import Asset, Container, EnricherRun, Source
from retrovue.usecases.asset_inspect import get_asset_inspect
from retrovue.web.api.catalog import get_db, router


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
        completed_at=completed_at if completed_at is not None else (now if status != "running" else None),
        error=error,
        result_payload=result_payload,
    )


def _mock_db_with_enricher_runs(
    runs: list[EnricherRun],
    asset: Asset | None = None,
) -> MagicMock:
    """Build a mock DB session that serves EnricherRun queries and asset lookups.

    The mock chains filter().order_by().all() to return the provided runs,
    simulating the real SQLAlchemy query chain used by get_enrichment_progress.
    """
    db = MagicMock()

    # EnricherRun query chain: db.query(EnricherRun).filter(...).order_by(...).all()
    query_mock = MagicMock()
    filter_mock = MagicMock()
    order_by_mock = MagicMock()
    order_by_mock.all.return_value = runs
    filter_mock.order_by.return_value = order_by_mock
    query_mock.filter.return_value = filter_mock
    db.query.return_value = query_mock

    # db.get(Asset, aid) for asset lookups
    if asset is not None:
        db.get.return_value = asset

    return db


def _make_full_asset_fixture() -> tuple[Source, Container, Asset]:
    """Create Source → Container → Asset chain with proper relationships."""
    source = MagicMock(spec=Source)
    source.id = uuid.uuid4()
    source.name = "Test Plex"

    container = MagicMock(spec=Container)
    container.uuid = uuid.uuid4()
    container.source_id = source.id
    container.name = "Movies"
    container.source = source

    asset = MagicMock(spec=Asset)
    asset.uuid = uuid.uuid4()
    asset.container_id = container.uuid
    asset.source_id = source.id
    asset.uri = "plex://server/library/1/movie.mkv"
    asset.canonical_uri = "/media/movies/movie.mkv"
    asset.state = "ready"
    asset.approved_for_broadcast = True
    asset.duration_ms = 7200000
    asset.container = container

    return source, container, asset


# ---------------------------------------------------------------------------
# 4. Multi-enricher progress: FFprobe + Loudness tracked independently
# ---------------------------------------------------------------------------


class TestMultiEnricherProgress:
    """Integration: multiple enrichers on the same asset are tracked independently."""

    def test_two_enrichers_tracked_independently(self) -> None:
        """FFprobe (succeeded) + Loudness (running) on same asset → both in progress dict."""
        asset_id = uuid.uuid4()
        now = datetime.now(UTC)

        ffprobe_run = _make_enricher_run(
            asset_id, "ffprobe",
            status="succeeded", version="1.0",
            started_at=now, completed_at=now,
            result_payload={"duration_ms": 120000, "video_codec": "h264"},
        )
        loudness_run = _make_enricher_run(
            asset_id, "loudness",
            status="running", version="1.0",
            started_at=now + timedelta(seconds=1),
            completed_at=None,
        )

        db = _mock_db_with_enricher_runs(
            [loudness_run, ffprobe_run],  # ordered by started_at desc
        )

        progress = get_enrichment_progress(db, asset_id)

        assert len(progress) == 2
        assert "ffprobe" in progress
        assert "loudness" in progress
        assert progress["ffprobe"].status == "succeeded"
        assert progress["ffprobe"].result_payload == {"duration_ms": 120000, "video_codec": "h264"}
        assert progress["loudness"].status == "running"

    def test_three_enrichers_all_succeeded(self) -> None:
        """FFprobe + Loudness + Interstitial all succeeded → 3 independent entries."""
        asset_id = uuid.uuid4()
        now = datetime.now(UTC)

        runs = [
            _make_enricher_run(
                asset_id, "interstitial_type",
                status="succeeded", version="1.0",
                started_at=now + timedelta(seconds=2),
                completed_at=now + timedelta(seconds=3),
            ),
            _make_enricher_run(
                asset_id, "loudness",
                status="succeeded", version="1.0",
                started_at=now + timedelta(seconds=1),
                completed_at=now + timedelta(seconds=2),
                result_payload={"integrated_loudness_lufs": -23.1},
            ),
            _make_enricher_run(
                asset_id, "ffprobe",
                status="succeeded", version="1.0",
                started_at=now, completed_at=now + timedelta(seconds=1),
                result_payload={"duration_ms": 120000},
            ),
        ]

        db = _mock_db_with_enricher_runs(runs)
        progress = get_enrichment_progress(db, asset_id)

        assert len(progress) == 3
        names = set(progress.keys())
        assert names == {"ffprobe", "loudness", "interstitial_type"}
        assert all(s.status == "succeeded" for s in progress.values())

    def test_latest_run_wins_per_enricher(self) -> None:
        """When an enricher has multiple runs, only the latest (by started_at) is returned."""
        asset_id = uuid.uuid4()
        now = datetime.now(UTC)

        old_run = _make_enricher_run(
            asset_id, "ffprobe",
            status="failed", version="1.0",
            started_at=now, completed_at=now,
            error="first attempt failed",
        )
        new_run = _make_enricher_run(
            asset_id, "ffprobe",
            status="succeeded", version="1.0",
            started_at=now + timedelta(seconds=10),
            completed_at=now + timedelta(seconds=11),
            result_payload={"duration_ms": 120000},
        )

        # Ordered by started_at desc — new_run first
        db = _mock_db_with_enricher_runs([new_run, old_run])
        progress = get_enrichment_progress(db, asset_id)

        assert len(progress) == 1
        assert progress["ffprobe"].status == "succeeded"
        assert progress["ffprobe"].error is None

    def test_usecase_aggregates_multi_enricher_into_inspect(self) -> None:
        """get_asset_inspect returns enrichers list with independent enricher entries."""
        source, container, asset = _make_full_asset_fixture()
        asset_id = asset.uuid
        now = datetime.now(UTC)

        statuses = {
            "ffprobe": EnricherStatus(
                enricher_name="ffprobe", status="succeeded",
                enricher_version="1.0", started_at=now, completed_at=now,
                error=None, result_payload={"duration_ms": 120000},
            ),
            "loudness": EnricherStatus(
                enricher_name="loudness", status="succeeded",
                enricher_version="1.0", started_at=now, completed_at=now,
                error=None, result_payload={"integrated_loudness_lufs": -23.1},
            ),
        }

        db = MagicMock()
        db.get.return_value = asset

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "retrovue.usecases.asset_inspect.get_enrichment_progress",
                lambda _db, _aid: statuses,
            )
            result = get_asset_inspect(db, asset_uuid=str(asset_id))

        enrichers = result["enrichers"]
        assert len(enrichers) == 2
        names = {e["name"] for e in enrichers}
        assert names == {"ffprobe", "loudness"}
        assert result["enrichment_summary"]["completed"] == 2
        assert result["enrichment_summary"]["total"] == 2


# ---------------------------------------------------------------------------
# 5. Enricher failure tracking
# ---------------------------------------------------------------------------


class TestEnricherFailureTracking:
    """Integration: enricher failures are persisted with status=failed and error message."""

    def test_failed_enricher_has_error_in_progress(self) -> None:
        """Failed enricher → get_enrichment_progress returns status=failed with error."""
        asset_id = uuid.uuid4()
        now = datetime.now(UTC)

        failed_run = _make_enricher_run(
            asset_id, "loudness",
            status="failed", version="1.0",
            started_at=now, completed_at=now,
            error="ffprobe binary not found in PATH",
        )

        db = _mock_db_with_enricher_runs([failed_run])
        progress = get_enrichment_progress(db, asset_id)

        assert "loudness" in progress
        assert progress["loudness"].status == "failed"
        assert progress["loudness"].error == "ffprobe binary not found in PATH"
        assert progress["loudness"].result_payload is None

    def test_mixed_success_and_failure(self) -> None:
        """One enricher succeeds, another fails → both tracked with correct status."""
        asset_id = uuid.uuid4()
        now = datetime.now(UTC)

        ffprobe_ok = _make_enricher_run(
            asset_id, "ffprobe",
            status="succeeded", version="1.0",
            started_at=now, completed_at=now,
            result_payload={"duration_ms": 120000},
        )
        loudness_fail = _make_enricher_run(
            asset_id, "loudness",
            status="failed", version="1.0",
            started_at=now + timedelta(seconds=1),
            completed_at=now + timedelta(seconds=2),
            error="timeout after 30s",
        )

        db = _mock_db_with_enricher_runs([loudness_fail, ffprobe_ok])
        progress = get_enrichment_progress(db, asset_id)

        assert progress["ffprobe"].status == "succeeded"
        assert progress["loudness"].status == "failed"
        assert progress["loudness"].error == "timeout after 30s"

    def test_failure_surfaces_in_inspect_enricher_record(self) -> None:
        """Inspect usecase exposes error field in enricher records for failed runs."""
        source, container, asset = _make_full_asset_fixture()
        now = datetime.now(UTC)

        statuses = {
            "loudness": EnricherStatus(
                enricher_name="loudness", status="failed",
                enricher_version="1.0", started_at=now, completed_at=now,
                error="ffprobe binary not found",
                result_payload=None,
            ),
        }

        db = MagicMock()
        db.get.return_value = asset

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "retrovue.usecases.asset_inspect.get_enrichment_progress",
                lambda _db, _aid: statuses,
            )
            result = get_asset_inspect(db, asset_uuid=str(asset.uuid))

        loudness = result["enrichers"][0]
        assert loudness["name"] == "loudness"
        assert loudness["status"] == "failed"
        assert loudness["error"] == "ffprobe binary not found"

    def test_failure_counted_in_summary(self) -> None:
        """Failed enrichers are counted in total but not in completed."""
        source, container, asset = _make_full_asset_fixture()
        now = datetime.now(UTC)

        statuses = {
            "ffprobe": EnricherStatus(
                enricher_name="ffprobe", status="succeeded",
                enricher_version="1.0", started_at=now, completed_at=now,
                error=None, result_payload={},
            ),
            "loudness": EnricherStatus(
                enricher_name="loudness", status="failed",
                enricher_version="1.0", started_at=now, completed_at=now,
                error="timeout", result_payload=None,
            ),
        }

        db = MagicMock()
        db.get.return_value = asset

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "retrovue.usecases.asset_inspect.get_enrichment_progress",
                lambda _db, _aid: statuses,
            )
            result = get_asset_inspect(db, asset_uuid=str(asset.uuid))

        assert result["enrichment_summary"]["total"] == 2
        assert result["enrichment_summary"]["completed"] == 1


# ---------------------------------------------------------------------------
# 6. API endpoint: GET /api/catalog/assets/{uuid}/enrichment
# ---------------------------------------------------------------------------


class TestEnrichmentApiEndpoint:
    """Integration: REST API returns correct enrichment response shape."""

    @pytest.fixture()
    def _api_fixtures(self):
        """Set up asset, enrichment statuses, and TestClient for API tests."""
        source, container, asset = _make_full_asset_fixture()
        now = datetime.now(UTC)

        statuses = {
            "ffprobe": EnricherStatus(
                enricher_name="ffprobe", status="succeeded",
                enricher_version="1.0.0", started_at=now, completed_at=now,
                error=None, result_payload={"duration_ms": 120000},
            ),
            "loudness": EnricherStatus(
                enricher_name="loudness", status="failed",
                enricher_version="1.0.0", started_at=now, completed_at=None,
                error="ffprobe binary not found",
                result_payload=None,
            ),
        }

        db = MagicMock()
        db.get.return_value = asset

        app = FastAPI()
        app.include_router(router)

        def override_get_db():
            yield db

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)

        return {
            "asset": asset,
            "statuses": statuses,
            "client": client,
        }

    def test_enrichment_endpoint_returns_200(self, _api_fixtures) -> None:
        """GET /api/catalog/assets/{uuid}/enrichment → 200 with enrichers list."""
        fx = _api_fixtures
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "retrovue.usecases.asset_inspect.get_enrichment_progress",
                lambda _db, _aid: fx["statuses"],
            )
            resp = fx["client"].get(
                f"/api/catalog/assets/{fx['asset'].uuid}/enrichment"
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "asset_id" in body
        assert "enrichers" in body
        assert body["asset_id"] == str(fx["asset"].uuid)

    def test_enrichment_endpoint_response_shape(self, _api_fixtures) -> None:
        """Each enricher in response has name, status, version, timestamps, error."""
        fx = _api_fixtures
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "retrovue.usecases.asset_inspect.get_enrichment_progress",
                lambda _db, _aid: fx["statuses"],
            )
            resp = fx["client"].get(
                f"/api/catalog/assets/{fx['asset'].uuid}/enrichment"
            )

        enrichers = resp.json()["enrichers"]
        assert len(enrichers) == 2

        ffprobe = next(e for e in enrichers if e["name"] == "ffprobe")
        assert ffprobe["status"] == "succeeded"
        assert ffprobe["version"] == "1.0.0"
        assert ffprobe["started_at"] is not None
        assert ffprobe["completed_at"] is not None
        assert ffprobe["error"] is None

        loudness = next(e for e in enrichers if e["name"] == "loudness")
        assert loudness["status"] == "failed"
        assert loudness["error"] == "ffprobe binary not found"

    def test_enrichment_endpoint_404_for_unknown_asset(self, _api_fixtures) -> None:
        """GET /api/catalog/assets/{bad-uuid}/enrichment → 404."""
        fx = _api_fixtures
        # Override db.get to return None (asset not found)
        db = MagicMock()
        db.get.return_value = None

        app = FastAPI()
        app.include_router(router)

        def override_get_db():
            yield db

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)

        resp = client.get(f"/api/catalog/assets/{uuid.uuid4()}/enrichment")
        assert resp.status_code == 404

    def test_enrichment_endpoint_empty_enrichers(self) -> None:
        """Asset with no enricher runs → enrichers list is empty."""
        source, container, asset = _make_full_asset_fixture()

        db = MagicMock()
        db.get.return_value = asset

        app = FastAPI()
        app.include_router(router)

        def override_get_db():
            yield db

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "retrovue.usecases.asset_inspect.get_enrichment_progress",
                lambda _db, _aid: {},
            )
            resp = client.get(f"/api/catalog/assets/{asset.uuid}/enrichment")

        assert resp.status_code == 200
        body = resp.json()
        assert body["enrichers"] == []


# ---------------------------------------------------------------------------
# 7. CLI inspect: enrichment table in output
# ---------------------------------------------------------------------------


class TestCliInspectEnrichmentOutput:
    """Integration: CLI 'asset inspect' renders per-enricher enrichment table."""

    def test_inspect_shows_enrichment_table(self) -> None:
        """retrovue asset inspect → human-readable enrichment table with status per enricher."""
        from typer.testing import CliRunner
        from retrovue.cli.commands.asset import app as asset_app

        source, container, asset = _make_full_asset_fixture()
        now = datetime.now(UTC)

        statuses = {
            "ffprobe": EnricherStatus(
                enricher_name="ffprobe", status="succeeded",
                enricher_version="1.0.0", started_at=now, completed_at=now,
                error=None, result_payload={},
            ),
            "loudness": EnricherStatus(
                enricher_name="loudness", status="failed",
                enricher_version="1.0.0", started_at=now, completed_at=None,
                error="ffprobe binary not found",
                result_payload=None,
            ),
        }

        mock_db = MagicMock()
        mock_db.get.return_value = asset
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        runner = CliRunner()
        with patch(
            "retrovue.cli.commands.asset.session",
            return_value=mock_db,
        ), pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "retrovue.usecases.asset_inspect.get_enrichment_progress",
                lambda _db, _aid: statuses,
            )
            result = runner.invoke(asset_app, ["inspect", str(asset.uuid)])

        assert result.exit_code == 0
        output = result.output

        # Verify enrichment table header
        assert "Enrichment:" in output
        assert "Enricher" in output
        assert "Status" in output

        # Verify per-enricher rows
        assert "ffprobe" in output
        assert "succeeded" in output
        assert "loudness" in output
        assert "failed" in output

        # Verify error displayed for failed enricher
        assert "ffprobe binary not found" in output

        # Verify summary line
        assert "1/2 enrichers completed" in output

    def test_inspect_json_output(self) -> None:
        """retrovue asset inspect --json → JSON with enrichers list."""
        from typer.testing import CliRunner
        from retrovue.cli.commands.asset import app as asset_app

        source, container, asset = _make_full_asset_fixture()
        now = datetime.now(UTC)

        statuses = {
            "ffprobe": EnricherStatus(
                enricher_name="ffprobe", status="succeeded",
                enricher_version="1.0.0", started_at=now, completed_at=now,
                error=None, result_payload={},
            ),
        }

        mock_db = MagicMock()
        mock_db.get.return_value = asset
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        runner = CliRunner()
        with patch(
            "retrovue.cli.commands.asset.session",
            return_value=mock_db,
        ), pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "retrovue.usecases.asset_inspect.get_enrichment_progress",
                lambda _db, _aid: statuses,
            )
            result = runner.invoke(asset_app, ["inspect", str(asset.uuid), "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"
        assert "asset" in data
        enrichers = data["asset"]["enrichers"]
        assert len(enrichers) == 1
        assert enrichers[0]["name"] == "ffprobe"
        assert enrichers[0]["status"] == "succeeded"

    def test_inspect_no_enrichments(self) -> None:
        """Asset with no enricher runs → 'No enrichment records.' message."""
        from typer.testing import CliRunner
        from retrovue.cli.commands.asset import app as asset_app

        source, container, asset = _make_full_asset_fixture()

        mock_db = MagicMock()
        mock_db.get.return_value = asset
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        runner = CliRunner()
        with patch(
            "retrovue.cli.commands.asset.session",
            return_value=mock_db,
        ), pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "retrovue.usecases.asset_inspect.get_enrichment_progress",
                lambda _db, _aid: {},
            )
            result = runner.invoke(asset_app, ["inspect", str(asset.uuid)])

        assert result.exit_code == 0
        assert "No enrichment records." in result.output

    def test_inspect_error_for_missing_asset(self) -> None:
        """retrovue asset inspect <bad-uuid> → error message, exit code 1."""
        from typer.testing import CliRunner
        from retrovue.cli.commands.asset import app as asset_app

        mock_db = MagicMock()
        mock_db.get.return_value = None
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        runner = CliRunner()
        with patch(
            "retrovue.cli.commands.asset.session",
            return_value=mock_db,
        ):
            result = runner.invoke(asset_app, ["inspect", str(uuid.uuid4())])

        assert result.exit_code == 1
