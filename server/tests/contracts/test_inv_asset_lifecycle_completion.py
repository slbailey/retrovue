"""Contract tests: INV-ASSET-LIFECYCLE-COMPLETION-001

An asset MUST NOT remain in "enriching" after execute_job() completes.
Every code path — success, partial success, exception — MUST evaluate
the state transition before returning or re-raising.

Root cause: when a processor raises an exception, execute_job() re-raises
at line 423 BEFORE reaching the state transition at line 450. The asset
stays in "enriching" permanently.

Fix: move state transition into a finally block so it executes on every
code path.
"""

from __future__ import annotations

from retrovue.runtime.clock import SystemClock

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

try:
    from retrovue.catalog.processor_runtime import (
        ProcessingContext,
        execute_job,
        RUN_STATUS_COMPLETED,
        RUN_STATUS_FAILED,
    )
    from retrovue.domain.entities import (
        Asset,
        AssetEditorial,
        AssetProbed,
        Container,
        ProcessorRun,
        ProcessorOutput,
        validate_state_transition,
    )
except ImportError:
    pytest.skip(
        "retrovue.catalog.processor_runtime dependencies not available",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------


class _FakeAsset:
    """Minimal asset for execute_job tests."""

    def __init__(
        self,
        *,
        state: str = "enriching",
        duration_ms: int | None = None,
    ):
        self.uuid = uuid.uuid4()
        self.uri = "/mnt/interstitials/test.mp4"
        self.canonical_uri = "/mnt/interstitials/test.mp4"
        self.size = 1024000
        self.file_size = 1024000
        self.file_mtime = 1700000000.0
        self.is_deleted = False
        self.state = state
        self.duration_ms = duration_ms
        self.container_id = uuid.uuid4()
        self.video_codec = None
        self.audio_codec = None
        self.container_format = None


class _FakeContainer:
    def __init__(self, name: str = "station_ids"):
        self.name = name
        self.uuid = uuid.uuid4()


class _FakeJob:
    def __init__(self, target_id, target_type: str = "MEDIA"):
        self.id = uuid.uuid4()
        self.target_id = target_id
        self.target_type = target_type


class _TrackingSession:
    """Fake DB session that tracks state changes."""

    def __init__(self, asset: _FakeAsset, container: _FakeContainer | None = None):
        self._asset = asset
        self._container = container
        self.added: list[Any] = []
        self.committed = False

    def get(self, model_class: type, key: Any) -> Any:
        if model_class is Asset or getattr(model_class, "__name__", "") == "Asset":
            return self._asset if key == self._asset.uuid else None
        if model_class is Container or getattr(model_class, "__name__", "") == "Container":
            return self._container
        return None

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.committed = True

    def flush(self) -> None:
        pass

    def query(self, *args, **kwargs):
        return _FakeQuery()


class _FakeQuery:
    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return None


# ===========================================================================
# Test 1 — Asset reaches "ready" when requirements met
# ===========================================================================


class TestAssetReachesReadyWhenRequirementsMet:
    """When duration_ms > 0 after processors complete, state → ready."""

    # Tier: 1 | Structural invariant
    def test_enriching_to_ready_with_duration(self):
        """Asset in 'enriching' with duration_ms set → state = 'ready'."""
        asset = _FakeAsset(state="enriching", duration_ms=5000)
        container = _FakeContainer(name="station_ids")
        db = _TrackingSession(asset, container)
        job = _FakeJob(target_id=asset.uuid, target_type="ASSET")

        try:
            execute_job(db, job, clock=SystemClock())
        except Exception:
            pass  # enricher may fail, but state should still transition

        assert asset.state == "ready", (
            f"INV-ASSET-LIFECYCLE-COMPLETION-001: asset with duration_ms=5000 "
            f"must reach 'ready', got '{asset.state}'"
        )


# ===========================================================================
# Test 2 — Asset transitions on processor failure
# ===========================================================================


class TestAssetTransitionsOnProcessorFailure:
    """When a processor raises, asset must NOT remain in 'enriching'."""

    # Tier: 1 | Structural invariant — ROOT CAUSE TEST
    def test_exception_does_not_leave_asset_enriching(self):
        """CRITICAL: When execute_job raises, asset state must not be 'enriching'.

        Before fix: exception at line 423 re-raised before state transition
        at line 450 → asset stuck in 'enriching' permanently.
        """
        asset = _FakeAsset(state="enriching", duration_ms=None)
        container = _FakeContainer(name="station_ids")
        db = _TrackingSession(asset, container)
        job = _FakeJob(target_id=asset.uuid, target_type="ASSET")

        # Make the enricher raise to trigger the exception path
        from retrovue.adapters.enrichers.interstitial_type_enricher import InterstitialTypeEnricher
        original_enrich = InterstitialTypeEnricher.enrich

        def _raise_on_enrich(self, item):
            raise RuntimeError("simulated processor crash")

        with patch.object(InterstitialTypeEnricher, "enrich", _raise_on_enrich):
            with pytest.raises(RuntimeError, match="simulated processor crash"):
                execute_job(db, job, clock=SystemClock())

        # INVARIANT: state must NOT be "enriching" after exception
        assert asset.state != "enriching", (
            f"INV-ASSET-LIFECYCLE-COMPLETION-001: asset must not remain "
            f"'enriching' after processor exception, got '{asset.state}'"
        )

    # Tier: 1 | Structural invariant
    def test_failed_processor_with_duration_still_promotes(self):
        """If duration_ms was already set before failure, asset should still
        reach 'ready' despite the processor exception.
        """
        asset = _FakeAsset(state="enriching", duration_ms=5000)
        container = _FakeContainer(name="station_ids")
        db = _TrackingSession(asset, container)
        job = _FakeJob(target_id=asset.uuid, target_type="ASSET")

        from retrovue.adapters.enrichers.interstitial_type_enricher import InterstitialTypeEnricher

        def _raise_on_enrich(self, item):
            raise RuntimeError("crash after duration was set")

        with patch.object(InterstitialTypeEnricher, "enrich", _raise_on_enrich):
            with pytest.raises(RuntimeError):
                execute_job(db, job, clock=SystemClock())

        assert asset.state == "ready", (
            f"Asset with duration_ms=5000 should reach 'ready' even after "
            f"processor failure, got '{asset.state}'"
        )


# ===========================================================================
# Test 3 — Asset does not remain enriching after all processors complete
# ===========================================================================


class TestAssetDoesNotRemainEnrichingAfterCompletion:
    """After execute_job returns (success or exception), state != 'enriching'."""

    # Tier: 1 | Structural invariant
    def test_successful_completion_without_duration(self):
        """All processors succeed but no duration_ms → state = 'new' (not 'enriching')."""
        asset = _FakeAsset(state="enriching", duration_ms=None)
        container = _FakeContainer(name="station_ids")
        db = _TrackingSession(asset, container)
        job = _FakeJob(target_id=asset.uuid, target_type="ASSET")

        try:
            execute_job(db, job, clock=SystemClock())
        except Exception:
            pass

        assert asset.state != "enriching", (
            f"INV-ASSET-LIFECYCLE-COMPLETION-001: after all processors complete, "
            f"state must not be 'enriching', got '{asset.state}'"
        )

    # Tier: 1 | Structural invariant
    def test_successful_completion_with_duration(self):
        """All processors succeed with duration_ms → state = 'ready'."""
        asset = _FakeAsset(state="enriching", duration_ms=5000)
        container = _FakeContainer(name="station_ids")
        db = _TrackingSession(asset, container)
        job = _FakeJob(target_id=asset.uuid, target_type="ASSET")

        try:
            execute_job(db, job, clock=SystemClock())
        except Exception:
            pass

        assert asset.state == "ready"


# ===========================================================================
# Test 4 — Missing required data prevents ready but not indefinite enriching
# ===========================================================================


class TestMissingDataPreventsReadyNotStuck:
    """Missing duration_ms → state = 'new', not stuck in 'enriching'."""

    # Tier: 1 | Structural invariant
    def test_no_duration_demotes_to_new(self):
        """Asset without duration_ms after processors → state = 'new'."""
        asset = _FakeAsset(state="enriching", duration_ms=None)
        container = _FakeContainer(name="station_ids")
        db = _TrackingSession(asset, container)
        job = _FakeJob(target_id=asset.uuid, target_type="ASSET")

        try:
            execute_job(db, job, clock=SystemClock())
        except Exception:
            pass

        assert asset.state == "new", (
            f"Asset without duration_ms should demote to 'new', got '{asset.state}'"
        )


# ===========================================================================
# Test 5 — State transition is idempotent for non-enriching states
# ===========================================================================


class TestStateTransitionIdempotent:
    """Assets not in 'enriching' should not have their state changed."""

    # Tier: 1 | Structural invariant
    def test_ready_asset_stays_ready(self):
        """Asset already in 'ready' should not be demoted."""
        asset = _FakeAsset(state="ready", duration_ms=5000)
        container = _FakeContainer(name="station_ids")
        db = _TrackingSession(asset, container)
        job = _FakeJob(target_id=asset.uuid, target_type="ASSET")

        try:
            execute_job(db, job, clock=SystemClock())
        except Exception:
            pass

        assert asset.state == "ready"

    # Tier: 1 | Structural invariant
    def test_new_asset_stays_new(self):
        """Asset in 'new' should not be changed by execute_job."""
        asset = _FakeAsset(state="new", duration_ms=None)
        container = _FakeContainer(name="station_ids")
        db = _TrackingSession(asset, container)
        job = _FakeJob(target_id=asset.uuid, target_type="ASSET")

        try:
            execute_job(db, job, clock=SystemClock())
        except Exception:
            pass

        assert asset.state == "new"
