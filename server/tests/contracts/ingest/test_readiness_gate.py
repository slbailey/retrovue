"""
Contract tests for INV-PROCESSOR-READINESS-GATE-001.

An asset MUST NOT transition to ready unless every processor with
required_for_readiness=True has completed (its produced_metadata fields
are populated on the asset).

Tests are deterministic (no wall-clock sleep, no real DB, no network).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from retrovue.catalog.processor_capability import (
    CAPABILITY_REGISTRY,
    ProcessorCapability,
    get_capability,
)
from retrovue.validators.readiness_gate import ReadinessGateValidator
from retrovue.validators.pipeline import ValidationPipeline
from retrovue.validators.auto_approve import try_auto_approve


def _make_asset(**overrides: object) -> SimpleNamespace:
    """Asset with all ffprobe-produced metadata populated by default."""
    defaults = dict(
        uuid="00000000-0000-0000-0000-000000000001",
        state="new",
        approved_for_broadcast=False,
        duration_ms=120_000,
        video_codec="h264",
        audio_codec="aac",
        container="mp4",
        container_format="mp4",
        bitrate=5_000_000,
        resolution="1920x1080",
        size=1_000_000,
        uri="/media/test.mp4",
        canonical_uri="/media/test.mp4",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# -- ProcessorCapability field --


class TestProcessorCapabilityRequiredForReadiness:
    """required_for_readiness field exists and is set correctly per registry."""

    def test_ffprobe_required_for_readiness(self) -> None:
        cap = get_capability("ffprobe")
        assert cap is not None
        assert cap.required_for_readiness is True

    def test_loudness_not_required_for_readiness(self) -> None:
        cap = get_capability("loudness")
        assert cap is not None
        assert cap.required_for_readiness is False

    def test_interstitial_type_not_required_for_readiness(self) -> None:
        cap = get_capability("interstitial-type")
        assert cap is not None
        assert cap.required_for_readiness is False

    def test_at_least_one_processor_required_for_readiness(self) -> None:
        required = [
            cap for cap in CAPABILITY_REGISTRY.values()
            if cap.required_for_readiness
        ]
        assert len(required) >= 1


# -- ReadinessGateValidator --


class TestReadinessGateValidator:
    """Validates INV-PROCESSOR-READINESS-GATE-001 enforcement."""

    def test_pass_when_all_required_metadata_present(self) -> None:
        asset = _make_asset()
        result = ReadinessGateValidator().validate(asset)
        assert result.passed
        assert result.validators["readiness_gate"].status == "pass"

    def test_fail_when_ffprobe_duration_ms_missing(self) -> None:
        asset = _make_asset(duration_ms=None)
        result = ReadinessGateValidator().validate(asset)
        assert not result.passed
        assert any(e.code == "READINESS_PROCESSOR_INCOMPLETE" for e in result.errors)
        assert any("ffprobe" in e.message for e in result.errors)

    def test_fail_when_ffprobe_video_codec_missing(self) -> None:
        asset = _make_asset(video_codec=None)
        result = ReadinessGateValidator().validate(asset)
        assert not result.passed
        assert any(e.code == "READINESS_PROCESSOR_INCOMPLETE" for e in result.errors)

    def test_fail_when_ffprobe_resolution_missing(self) -> None:
        asset = _make_asset(resolution=None)
        result = ReadinessGateValidator().validate(asset)
        assert not result.passed

    def test_fail_lists_missing_fields(self) -> None:
        asset = _make_asset(duration_ms=None, video_codec=None)
        result = ReadinessGateValidator().validate(asset)
        assert not result.passed
        # Error message should mention the missing fields
        error_messages = " ".join(e.message for e in result.errors)
        assert "duration_ms" in error_messages
        assert "video_codec" in error_messages

    def test_non_required_processors_ignored(self) -> None:
        """Loudness fields missing should not block readiness."""
        asset = _make_asset()  # no loudness_lufs, gain_db, etc.
        result = ReadinessGateValidator().validate(asset)
        assert result.passed


# -- Integration with auto_approve --


class TestReadinessGateInAutoApprove:
    """Readiness gate blocks auto-approval when required processor incomplete."""

    def test_auto_approve_blocked_by_missing_required_processor_data(self) -> None:
        asset = _make_asset(duration_ms=None)
        from retrovue.validators.duration import DurationValidator

        pipeline = ValidationPipeline([
            ReadinessGateValidator(),
            DurationValidator(),
        ])
        result = try_auto_approve(asset, pipeline)
        assert not result.passed
        assert asset.state == "new"
        assert asset.approved_for_broadcast is False

    def test_auto_approve_succeeds_with_all_required_data(self) -> None:
        asset = _make_asset()
        from retrovue.validators.duration import DurationValidator
        from retrovue.validators.codec import CodecValidator
        from retrovue.validators.container_format import ContainerFormatValidator
        from retrovue.validators.playability import PlayabilityValidator

        pipeline = ValidationPipeline([
            ReadinessGateValidator(),
            DurationValidator(),
            CodecValidator(),
            ContainerFormatValidator(),
            PlayabilityValidator(),
        ])
        result = try_auto_approve(asset, pipeline)
        assert result.passed
        assert asset.state == "ready"
        assert asset.approved_for_broadcast is True
