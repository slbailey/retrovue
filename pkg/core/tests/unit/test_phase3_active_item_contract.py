"""
Phase 3 — Active Schedule Item Resolver contract tests.

Unit tests only: fixed elapsed_in_grid_ms and mock config; no media, no tune-in.
"""

from __future__ import annotations

import pytest

from retrovue.runtime.active_item_resolver import (
    FILLER_START_MS,
    MockDurationConfig,
    resolve_active_item,
    SAMPLE_DURATION_MS,
)
from retrovue.runtime.grid import GRID_DURATION_MS
from retrovue.runtime.mock_schedule import ScheduleItem


def test_phase3_7_min_samplecontent():
    """Phase 3: elapsed_in_grid_ms = 420_000 (7:00) → samplecontent."""
    item = resolve_active_item(420_000)
    assert item.id == "samplecontent"


def test_phase3_26_min_filler():
    """Phase 3: elapsed_in_grid_ms = 1_560_000 (26:00) → filler."""
    item = resolve_active_item(1_560_000)
    assert item.id == "filler"


def test_phase3_boundary_below_filler_start_samplecontent():
    """Phase 3: elapsed_in_grid_ms < filler_start_ms → samplecontent."""
    item = resolve_active_item(1_498_000)  # 24:58
    assert item.id == "samplecontent"


def test_phase3_boundary_at_or_above_filler_start_filler():
    """Phase 3: elapsed_in_grid_ms >= filler_start_ms → filler."""
    assert resolve_active_item(FILLER_START_MS).id == "filler"
    assert resolve_active_item(1_499_001).id == "filler"
    assert resolve_active_item(1_560_000).id == "filler"


def test_phase3_grid_duration_consistency_assert():
    """Phase 3: Resolver asserts grid_duration_ms == Phase 1; mismatch raises."""
    with pytest.raises(ValueError, match="grid_duration_ms.*Phase 1|configuration error"):
        resolve_active_item(0, config=MockDurationConfig(grid_duration_ms=999_999))


def test_phase3_default_config_matches_phase1():
    """Default config grid_duration_ms matches Phase 1 GRID_DURATION_MS."""
    cfg = MockDurationConfig()
    assert cfg.grid_duration_ms == GRID_DURATION_MS
    assert cfg.sample_duration_ms == SAMPLE_DURATION_MS
    assert cfg.filler_start_ms == FILLER_START_MS
