"""
Phase 4 — PlayoutPipeline contract tests.

Unit tests: fixed inputs, assert exact PlayoutSegment fields (ms). No execution, no Air.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from retrovue.runtime.asset_metadata import SAMPLECONTENT, FILLER
from retrovue.runtime.mock_schedule import ScheduleItem
from retrovue.runtime.playout_pipeline import PlayoutSegment, build_playout_segment

UTC = timezone.utc
BASE = datetime(2025, 1, 15, 0, 0, 0, tzinfo=UTC)
CHANNEL_ID = "mock"


def test_phase4_10_07_samplecontent():
    """Phase 4: 10:07 → samplecontent @ start_offset_ms = 420_000 (7 min), hard stop 10:30. Uses Phase 2.5 Asset."""
    grid_start = BASE.replace(hour=10, minute=0, second=0, microsecond=0)
    grid_end = BASE.replace(hour=10, minute=30, second=0, microsecond=0)
    elapsed_ms = 420_000  # 7:00
    item = ScheduleItem("samplecontent")

    segment, cid = build_playout_segment(
        item, grid_start, grid_end, elapsed_ms, CHANNEL_ID,
        samplecontent_asset=SAMPLECONTENT, filler_asset=FILLER,
    )
    assert cid == CHANNEL_ID
    assert segment.asset_path == SAMPLECONTENT.asset_path
    assert segment.start_offset_ms == 420_000
    assert segment.hard_stop_time_ms == int(grid_end.timestamp() * 1000)


def test_phase4_10_26_filler():
    """Phase 4: 10:26 → filler @ start_offset_ms = elapsed - sample_duration (from Asset), hard stop 10:30."""
    grid_start = BASE.replace(hour=10, minute=0, second=0, microsecond=0)
    grid_end = BASE.replace(hour=10, minute=30, second=0, microsecond=0)
    # 26 min = 1_560_000 ms; minus samplecontent.duration_ms (1_499_904) = 60_096 ms into filler
    elapsed_ms = 1_560_000
    item = ScheduleItem("filler")

    segment, cid = build_playout_segment(
        item, grid_start, grid_end, elapsed_ms, CHANNEL_ID,
        samplecontent_asset=SAMPLECONTENT, filler_asset=FILLER,
    )
    assert cid == CHANNEL_ID
    assert segment.asset_path == FILLER.asset_path
    assert segment.start_offset_ms == elapsed_ms - SAMPLECONTENT.duration_ms  # 60_096
    assert segment.hard_stop_time_ms == int(grid_end.timestamp() * 1000)


def test_phase4_10_30_boundary_samplecontent():
    """Phase 4: 10:30 (boundary) → samplecontent @ start_offset_ms = 0, hard stop 11:00."""
    grid_start = BASE.replace(hour=10, minute=30, second=0, microsecond=0)
    grid_end = BASE.replace(hour=11, minute=0, second=0, microsecond=0)
    elapsed_ms = 0
    item = ScheduleItem("samplecontent")

    segment, cid = build_playout_segment(
        item, grid_start, grid_end, elapsed_ms, CHANNEL_ID,
        samplecontent_asset=SAMPLECONTENT, filler_asset=FILLER,
    )
    assert segment.asset_path == SAMPLECONTENT.asset_path
    assert segment.start_offset_ms == 0
    assert segment.hard_stop_time_ms == int(grid_end.timestamp() * 1000)


def test_phase4_every_invocation_new_instance():
    """Phase 4: Every invocation creates a new segment (no reuse/mutation)."""
    grid_start = BASE.replace(hour=10, minute=0, second=0, microsecond=0)
    grid_end = BASE.replace(hour=10, minute=30, second=0, microsecond=0)
    item = ScheduleItem("samplecontent")

    seg1, _ = build_playout_segment(
        item, grid_start, grid_end, 0, CHANNEL_ID,
        samplecontent_asset=SAMPLECONTENT, filler_asset=FILLER,
    )
    seg2, _ = build_playout_segment(
        item, grid_start, grid_end, 0, CHANNEL_ID,
        samplecontent_asset=SAMPLECONTENT, filler_asset=FILLER,
    )
    assert seg1 is not seg2
    assert seg1 == seg2  # value equality
