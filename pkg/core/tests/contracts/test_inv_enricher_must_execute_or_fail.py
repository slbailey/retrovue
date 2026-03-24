"""Contract tests: INV-ENRICHER-MUST-EXECUTE-OR-FAIL-001

If an enricher is configured for an asset, it MUST either execute
successfully OR produce a visible error.  It MUST NOT silently skip.

These tests validate:
  1. _enricher_instance raises EnricherConstructionError (not silent None)
  2. execute_job records failed ProcessorRun for construction failures
  3. Structured log emits enricher_construction_failed event
  4. Legitimate skips (unregistered processor_id) still return None
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

try:
    from retrovue.catalog.processor_runtime import (
        EnricherConstructionError,
        _enricher_instance,
        execute_job,
        RUN_STATUS_FAILED,
    )
    from retrovue.adapters.enrichers.interstitial_type_enricher import (
        InterstitialTypeEnricher,
    )
except ImportError:
    pytest.skip(
        "retrovue.catalog.processor_runtime dependencies not available",
        allow_module_level=True,
    )


# ===========================================================================
# Step 1 — _enricher_instance raises on construction failure
# ===========================================================================


class TestEnricherInstanceRaises:
    """_enricher_instance MUST raise EnricherConstructionError, not return None."""

    # Tier: 1 | Structural invariant
    def test_empty_collection_name_raises(self):
        """Empty collection_name → EnricherConstructionError, not None."""
        with pytest.raises(EnricherConstructionError) as exc_info:
            _enricher_instance("interstitial-type", "")

        assert exc_info.value.processor_id == "interstitial-type"
        assert "collection_name" in exc_info.value.reason.lower() or "empty" in exc_info.value.reason.lower()

    # Tier: 1 | Structural invariant
    def test_unknown_collection_name_raises(self):
        """Unknown collection_name → EnricherConstructionError."""
        with pytest.raises(EnricherConstructionError) as exc_info:
            _enricher_instance("interstitial-type", "not_a_collection")

        assert exc_info.value.processor_id == "interstitial-type"
        assert "not_a_collection" in exc_info.value.reason

    # Tier: 1 | Structural invariant
    def test_valid_collection_name_succeeds(self):
        """Known collection_name → returns enricher instance (no exception)."""
        result = _enricher_instance("interstitial-type", "station_ids")
        assert result is not None
        assert isinstance(result, InterstitialTypeEnricher)

    # Tier: 1 | Structural invariant
    def test_unregistered_processor_returns_none(self):
        """Processor not in ENRICHERS → returns None (legitimate skip)."""
        result = _enricher_instance("nonexistent-processor", "")
        assert result is None

    # Tier: 1 | Structural invariant
    def test_error_contains_invariant_id(self):
        """Error message must reference the invariant for traceability."""
        with pytest.raises(EnricherConstructionError, match="INV-ENRICHER-MUST-EXECUTE-OR-FAIL-001"):
            _enricher_instance("interstitial-type", "")

    # Tier: 1 | Structural invariant
    def test_error_preserves_cause(self):
        """EnricherConstructionError must chain the original exception."""
        with pytest.raises(EnricherConstructionError) as exc_info:
            _enricher_instance("interstitial-type", "bad_name")

        assert exc_info.value.__cause__ is not None


# ===========================================================================
# Step 2 — execute_job records failed run for construction failure
# ===========================================================================


class _FakeJob:
    """Minimal job stand-in for execute_job tests."""
    def __init__(self, target_id: str = "test-uuid", target_type: str = "ASSET"):
        self.id = "job-001"
        self.target_id = target_id
        self.target_type = target_type


class _FakeAsset:
    """Minimal asset stand-in."""
    def __init__(self, uuid: str = "test-uuid"):
        self.uuid = uuid
        self.uri = "/mnt/interstitials/test.mp4"
        self.canonical_uri = "/mnt/interstitials/test.mp4"
        self.size = 1024000
        self.file_size = 1024000
        self.file_mtime = 1700000000.0
        self.is_deleted = False
        self.state = "enriching"
        self.duration_ms = None
        self.container_id = "container-001"
        self.video_codec = None
        self.audio_codec = None
        self.container_format = None


class _FakeContainer:
    def __init__(self, name: str = ""):
        self.name = name
        self.uuid = "container-001"


class _TrackingSession:
    """Fake session that tracks added objects."""
    def __init__(self, asset: _FakeAsset, container: _FakeContainer | None = None):
        self._asset = asset
        self._container = container
        self.added: list[Any] = []
        self._editorial_payload: dict | None = None

    def get(self, model_class: type, key: Any) -> Any:
        from retrovue.domain.entities import Asset, Container, AssetProbed, AssetEditorial
        if model_class is Asset or (hasattr(model_class, '__name__') and model_class.__name__ == 'Asset'):
            return self._asset if str(key) == str(self._asset.uuid) else None
        if model_class is Container or (hasattr(model_class, '__name__') and model_class.__name__ == 'Container'):
            return self._container
        if model_class is AssetProbed or (hasattr(model_class, '__name__') and model_class.__name__ == 'AssetProbed'):
            return None
        if model_class is AssetEditorial or (hasattr(model_class, '__name__') and model_class.__name__ == 'AssetEditorial'):
            return None
        return None

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        pass

    def flush(self) -> None:
        pass


class TestExecuteJobRecordsFailure:
    """execute_job MUST record a failed ProcessorRun when enricher construction fails."""

    # Tier: 2 | Scheduling logic invariant
    def test_construction_failure_produces_failed_run_record(self):
        """When enricher construction fails, a ProcessorRun with status=failed
        must be persisted — the failure is NOT silently skipped.
        """
        asset = _FakeAsset()
        # Container with empty name → interstitial-type enricher will fail
        container = _FakeContainer(name="")
        db = _TrackingSession(asset, container)
        job = _FakeJob()

        # execute_job should NOT raise — it catches construction errors
        # and records them as failed runs, then continues with other processors.
        # But it may raise on the final state transition. We catch that.
        try:
            execute_job(db, job)
        except Exception:
            pass

        # Find ProcessorRun records that were added
        from retrovue.domain.entities import ProcessorRun
        run_records = [
            obj for obj in db.added
            if isinstance(obj, ProcessorRun)
        ]

        # Must have at least one failed run for interstitial-type
        failed_runs = [
            r for r in run_records
            if r.processor_id == "interstitial-type" and r.status == RUN_STATUS_FAILED
        ]
        assert len(failed_runs) >= 1, (
            f"INV-ENRICHER-MUST-EXECUTE-OR-FAIL-001: expected failed ProcessorRun "
            f"for 'interstitial-type', got run records: "
            f"{[(r.processor_id, r.status) for r in run_records]}"
        )

        # Error message must explain the failure
        assert failed_runs[0].error_message is not None
        assert "INV-ENRICHER-MUST-EXECUTE-OR-FAIL-001" in failed_runs[0].error_message

    # Tier: 2 | Scheduling logic invariant
    def test_construction_failure_logs_error(self, capsys):
        """Construction failure must emit enricher_construction_failed log.

        structlog writes to stdout, not the standard logging framework,
        so we capture stdout instead of using caplog.
        """
        asset = _FakeAsset()
        container = _FakeContainer(name="")
        db = _TrackingSession(asset, container)
        job = _FakeJob()

        try:
            execute_job(db, job)
        except Exception:
            pass

        captured = capsys.readouterr()
        assert "enricher_construction_failed" in captured.out, (
            f"Expected enricher_construction_failed in stdout. "
            f"Got: {captured.out[:500]}"
        )
        assert "interstitial-type" in captured.out


# ===========================================================================
# Step 3 — enricher execution failure (not construction) still recorded
# ===========================================================================


class TestEnricherExecutionFailureVisible:
    """Enricher runtime exceptions (during enrich()) are already recorded
    as failed ProcessorRun by the existing try/except in execute_job.
    This test verifies that behavior still holds.
    """

    # Tier: 2 | Scheduling logic invariant
    def test_runtime_exception_produces_failed_run(self):
        """If enricher.enrich() raises, the run is recorded as failed."""
        asset = _FakeAsset()
        container = _FakeContainer(name="station_ids")
        db = _TrackingSession(asset, container)
        job = _FakeJob()

        # Patch the enricher to raise during enrich()
        def _broken_enrich(item):
            raise RuntimeError("simulated enricher crash")

        with patch.object(
            InterstitialTypeEnricher, "enrich", side_effect=_broken_enrich,
        ):
            with pytest.raises(RuntimeError, match="simulated enricher crash"):
                execute_job(db, job)

        from retrovue.domain.entities import ProcessorRun
        run_records = [
            obj for obj in db.added
            if isinstance(obj, ProcessorRun)
        ]

        failed_runs = [
            r for r in run_records
            if r.processor_id == "interstitial-type" and r.status == RUN_STATUS_FAILED
        ]
        assert len(failed_runs) >= 1, (
            "Runtime enricher failure must produce a failed ProcessorRun"
        )
        assert "simulated enricher crash" in (failed_runs[0].error_message or "")


# ===========================================================================
# Step 4 — no silent skip: every configured processor has a run record
# ===========================================================================


class TestNoSilentSkip:
    """Every processor_id resolved for a job's target_type must produce
    a ProcessorRun record — either completed or failed, never absent.
    """

    # Tier: 1 | Structural invariant
    def test_construction_failure_not_absent_from_runs(self):
        """A construction-failed enricher must NOT be absent from run records.

        Before fix: _enricher_instance returned None, loop skipped with
        `continue`, no run record created → silent absence.

        After fix: EnricherConstructionError caught, failed run recorded.
        """
        asset = _FakeAsset()
        container = _FakeContainer(name="")  # Will cause construction failure
        db = _TrackingSession(asset, container)
        job = _FakeJob()

        try:
            execute_job(db, job)
        except Exception:
            pass

        from retrovue.domain.entities import ProcessorRun
        run_records = [
            obj for obj in db.added
            if isinstance(obj, ProcessorRun)
        ]

        processor_ids_in_runs = {r.processor_id for r in run_records}

        # interstitial-type is in CAPABILITY_REGISTRY for ASSET target_type
        # and must appear in run records even when construction fails
        assert "interstitial-type" in processor_ids_in_runs, (
            f"INV-ENRICHER-MUST-EXECUTE-OR-FAIL-001: 'interstitial-type' "
            f"must appear in run records (even as failed), not silently absent. "
            f"Found: {processor_ids_in_runs}"
        )
