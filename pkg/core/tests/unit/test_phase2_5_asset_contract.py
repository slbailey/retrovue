"""
Phase 2.5 — Asset metadata contract tests.

No file I/O, no ffprobe. Validates duration rules and immutability.
"""

from __future__ import annotations

import pytest

from retrovue.runtime.asset_metadata import Asset, SAMPLECONTENT, FILLER
from retrovue.runtime.grid import GRID_DURATION_MS


def test_phase25_asset_duration_is_integer_ms():
    """Phase 2.5: Asset durations are integers (ms)."""
    assert isinstance(SAMPLECONTENT.duration_ms, int)
    assert isinstance(FILLER.duration_ms, int)


def test_phase25_asset_duration_positive():
    """Phase 2.5: duration_ms > 0."""
    assert SAMPLECONTENT.duration_ms > 0
    assert FILLER.duration_ms > 0


def test_phase25_samplecontent_duration_less_than_grid():
    """Phase 2.5: samplecontent duration_ms < grid_duration_ms."""
    assert SAMPLECONTENT.duration_ms < GRID_DURATION_MS


def test_phase25_asset_immutable():
    """Phase 2.5: Asset objects are immutable (frozen)."""
    with pytest.raises(Exception):  # FrozenInstanceError
        SAMPLECONTENT.duration_ms = 999  # type: ignore[misc]


def test_phase25_fixture_durations_match_contract():
    """Phase 2.5: Example fixture durations per contract."""
    assert SAMPLECONTENT.duration_ms == 1_499_904
    assert FILLER.duration_ms == 3_650_455
    assert SAMPLECONTENT.asset_id == "samplecontent"
    assert SAMPLECONTENT.asset_path == "assets/samplecontent.mp4"
    assert FILLER.asset_id == "filler"
    assert FILLER.asset_path == "assets/filler.mp4"


def test_phase25_asset_rejects_non_positive_duration():
    """Phase 2.5: Asset rejects duration_ms <= 0."""
    with pytest.raises(ValueError, match="duration_ms must be positive"):
        Asset(asset_id="x", asset_path="/x", duration_ms=0)
    with pytest.raises(ValueError, match="duration_ms must be positive"):
        Asset(asset_id="x", asset_path="/x", duration_ms=-1)


def test_phase25_phase3_config_from_assets():
    """Phase 2.5: Phase 3 consumes asset.duration_ms via MockDurationConfig.from_assets (no file I/O)."""
    from retrovue.runtime.active_item_resolver import MockDurationConfig, resolve_active_item

    config = MockDurationConfig.from_assets(SAMPLECONTENT)
    assert config.filler_start_ms == SAMPLECONTENT.duration_ms
    assert config.sample_duration_ms == SAMPLECONTENT.duration_ms

    # Boundary at authoritative duration: just below → samplecontent, at or above → filler
    assert resolve_active_item(SAMPLECONTENT.duration_ms - 1, config=config).id == "samplecontent"
    assert resolve_active_item(SAMPLECONTENT.duration_ms, config=config).id == "filler"
