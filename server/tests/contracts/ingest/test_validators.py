"""
Contract tests for core validators (duration, codec, container, playability).

Each validator MUST return the canonical result shape per
INV-VALIDATOR-OUTPUT-SHAPE-001.

Tests are deterministic (no wall-clock sleep, no real DB, no network).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from retrovue.validators.duration import DurationValidator
from retrovue.validators.codec import CodecValidator
from retrovue.validators.container_format import ContainerFormatValidator
from retrovue.validators.playability import PlayabilityValidator
from retrovue.validators.pipeline import ValidationPipeline


def _make_asset(**overrides: object) -> SimpleNamespace:
    defaults = dict(
        uuid="00000000-0000-0000-0000-000000000001",
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


# -- Duration Validator --

class TestDurationValidator:
    def test_pass_with_valid_duration(self) -> None:
        asset = _make_asset(duration_ms=120_000)
        result = DurationValidator().validate(asset)
        assert result.passed
        assert result.validators["duration"].status == "pass"

    def test_fail_missing_duration(self) -> None:
        asset = _make_asset(duration_ms=None)
        result = DurationValidator().validate(asset)
        assert not result.passed
        assert result.validators["duration"].status == "fail"
        assert any(e.code == "DURATION_MISSING" for e in result.errors)

    def test_fail_zero_duration(self) -> None:
        asset = _make_asset(duration_ms=0)
        result = DurationValidator().validate(asset)
        assert not result.passed
        assert any(e.code == "DURATION_NON_POSITIVE" for e in result.errors)

    def test_fail_negative_duration(self) -> None:
        asset = _make_asset(duration_ms=-100)
        result = DurationValidator().validate(asset)
        assert not result.passed


# -- Codec Validator --

class TestCodecValidator:
    def test_pass_with_both_codecs(self) -> None:
        asset = _make_asset(video_codec="h264", audio_codec="aac")
        result = CodecValidator().validate(asset)
        assert result.passed
        assert result.validators["codec"].status == "pass"

    def test_fail_no_video_codec(self) -> None:
        asset = _make_asset(video_codec=None, audio_codec="aac")
        result = CodecValidator().validate(asset)
        assert not result.passed
        assert any(e.code == "VIDEO_CODEC_MISSING" for e in result.errors)

    def test_warn_no_audio_codec(self) -> None:
        asset = _make_asset(video_codec="h264", audio_codec=None)
        result = CodecValidator().validate(asset)
        assert result.passed  # warning, not failure
        assert result.validators["codec"].status == "warn"
        assert any(w.code == "AUDIO_CODEC_MISSING" for w in result.warnings)


# -- Container Format Validator --

class TestContainerFormatValidator:
    def test_pass_with_format(self) -> None:
        asset = _make_asset(container_format="mp4")
        result = ContainerFormatValidator().validate(asset)
        assert result.passed

    def test_fail_missing_format(self) -> None:
        asset = _make_asset(container_format=None)
        result = ContainerFormatValidator().validate(asset)
        assert not result.passed
        assert any(e.code == "CONTAINER_FORMAT_MISSING" for e in result.errors)


# -- Playability Validator --

class TestPlayabilityValidator:
    def test_pass_playable_asset(self) -> None:
        asset = _make_asset()
        result = PlayabilityValidator().validate(asset)
        assert result.passed

    def test_fail_no_duration(self) -> None:
        asset = _make_asset(duration_ms=None)
        result = PlayabilityValidator().validate(asset)
        assert not result.passed
        assert any(e.code == "PLAYABILITY_NO_DURATION" for e in result.errors)

    def test_fail_no_video_codec(self) -> None:
        asset = _make_asset(video_codec=None)
        result = PlayabilityValidator().validate(asset)
        assert not result.passed
        assert any(e.code == "PLAYABILITY_NO_VIDEO_CODEC" for e in result.errors)

    def test_fail_zero_size(self) -> None:
        asset = _make_asset(size=0)
        result = PlayabilityValidator().validate(asset)
        assert not result.passed
        assert any(e.code == "PLAYABILITY_ZERO_SIZE" for e in result.errors)

    def test_fail_no_uri(self) -> None:
        asset = _make_asset(uri=None, canonical_uri=None)
        result = PlayabilityValidator().validate(asset)
        assert not result.passed
        assert any(e.code == "PLAYABILITY_NO_URI" for e in result.errors)

    def test_fail_multiple_issues(self) -> None:
        asset = _make_asset(duration_ms=None, video_codec=None, size=0, uri=None, canonical_uri=None)
        result = PlayabilityValidator().validate(asset)
        assert not result.passed
        assert len(result.errors) == 4


# -- Pipeline --

class TestValidationPipeline:
    def test_all_pass(self) -> None:
        asset = _make_asset()
        pipeline = ValidationPipeline([
            DurationValidator(),
            CodecValidator(),
            ContainerFormatValidator(),
            PlayabilityValidator(),
        ])
        result = pipeline.run(asset)
        assert result.passed
        assert "duration" in result.validators
        assert "codec" in result.validators
        assert "container" in result.validators
        assert "playability" in result.validators

    def test_one_fail_makes_aggregate_fail(self) -> None:
        asset = _make_asset(duration_ms=None)
        pipeline = ValidationPipeline([
            DurationValidator(),
            CodecValidator(),
        ])
        result = pipeline.run(asset)
        assert not result.passed
        assert result.validators["duration"].status == "fail"
        assert result.validators["codec"].status == "pass"

    def test_empty_pipeline_passes(self) -> None:
        asset = _make_asset()
        result = ValidationPipeline().run(asset)
        assert result.passed
