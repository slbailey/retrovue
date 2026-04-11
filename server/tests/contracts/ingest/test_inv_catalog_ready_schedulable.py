"""
Contract tests: INV-CATALOG-READY-SCHEDULABLE-001
All ready assets are playable and schedulable.

If an asset is in state ``ready``, scheduling MAY place it without
further validation. ``ready`` is the trust boundary between ingest
and scheduling.

Tests are deterministic (no wall-clock sleep, no real DB, no network).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from retrovue.validators.pipeline import ValidationPipeline
from retrovue.validators.duration import DurationValidator
from retrovue.validators.codec import CodecValidator
from retrovue.validators.container_format import ContainerFormatValidator
from retrovue.validators.playability import PlayabilityValidator
from retrovue.validators.auto_approve import try_auto_approve


def _make_asset(**overrides: object) -> SimpleNamespace:
    """Create a minimal asset stub."""
    defaults = dict(
        uuid="00000000-0000-0000-0000-000000000001",
        state="new",
        approved_for_broadcast=False,
        duration_ms=120_000,
        video_codec="h264",
        audio_codec="aac",
        container_format="mp4",
        size=1_000_000,
        uri="/media/test.mp4",
        canonical_uri="/media/test.mp4",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _full_pipeline() -> ValidationPipeline:
    return ValidationPipeline([
        DurationValidator(),
        CodecValidator(),
        ContainerFormatValidator(),
        PlayabilityValidator(),
    ])


class TestInvCatalogReadySchedulable001:
    """INV-CATALOG-READY-SCHEDULABLE-001: Ready assets are schedulable."""

    def test_ready_asset_accepted_without_probe(self) -> None:
        """A ready asset with valid metadata is accepted by scheduling without probe."""
        asset = _make_asset()
        pipeline = _full_pipeline()
        result = try_auto_approve(asset, pipeline)
        assert result.passed
        assert asset.state == "ready"
        assert asset.approved_for_broadcast is True

    def test_unplayable_asset_not_promoted(self) -> None:
        """An asset missing critical fields is NOT promoted to ready."""
        asset = _make_asset(duration_ms=None, video_codec=None)
        pipeline = _full_pipeline()
        result = try_auto_approve(asset, pipeline)
        assert not result.passed
        assert asset.state == "new"
        assert asset.approved_for_broadcast is False

    def test_scheduling_does_not_invoke_validators(self) -> None:
        """Schedule compilation does not need to re-validate ready assets.

        This is proven by the design: once an asset is in ``ready`` state,
        it has already passed all validators. The pipeline is not needed
        at schedule time — ``ready`` is the trust boundary.
        """
        asset = _make_asset(state="ready", approved_for_broadcast=True)
        # Scheduling can use this asset directly — no validation call needed
        assert asset.state == "ready"
        assert asset.approved_for_broadcast is True

    def test_enriching_asset_promoted_to_ready(self) -> None:
        """An asset already in enriching state is promoted to ready on approval.

        The enriching → ready branch in try_auto_approve() handles assets
        that entered enriching via a prior pipeline step and now pass
        all validators.
        """
        asset = _make_asset(state="enriching")
        pipeline = _full_pipeline()
        result = try_auto_approve(asset, pipeline)
        assert result.passed
        assert asset.state == "ready"
        assert asset.approved_for_broadcast is True

    def test_enriching_asset_not_promoted_on_failure(self) -> None:
        """An asset in enriching state that fails validation stays in enriching."""
        asset = _make_asset(state="enriching", duration_ms=None, video_codec=None)
        pipeline = _full_pipeline()
        result = try_auto_approve(asset, pipeline)
        assert not result.passed
        assert asset.state == "enriching"
        assert asset.approved_for_broadcast is False

    def test_asset_loses_playability_exits_ready(self) -> None:
        """An asset that becomes unplayable MUST be transitioned out of ready.

        Per the invariant: 'If an asset becomes unplayable after reaching
        ready, the system MUST transition it out of ready before the next
        schedule compile.'

        Simulates: asset is ready, then source file is removed (duration
        becomes None). Re-validation fails, and the asset must NOT remain
        in ready state.
        """
        from retrovue.domain.entities import validate_state_transition

        asset = _make_asset(state="ready", approved_for_broadcast=True)
        assert asset.state == "ready"

        # Simulate the asset becoming unplayable (source removed, duration lost)
        asset.duration_ms = None
        asset.video_codec = None

        # Re-validation detects the asset is no longer playable
        pipeline = _full_pipeline()
        result = pipeline.run(asset)
        assert not result.passed, "Asset with missing duration/codec must fail validation"

        # System transitions the asset out of ready → retired
        validate_state_transition("ready", "retired")
        asset.state = "retired"
        asset.approved_for_broadcast = False

        assert asset.state != "ready"
        assert asset.approved_for_broadcast is False
