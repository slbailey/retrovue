"""Mock A/B schedule service implements get_block_at for BlockPlan (INV-EXEC-NO-STRUCTURE-001)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from retrovue.dev.mock_schedule_services import MockAlternatingScheduleService
from retrovue.runtime.clock import MasterClock


def test_mock_alternating_get_block_at_covers_utc_ms() -> None:
    clock = MasterClock()
    svc = MockAlternatingScheduleService(
        clock=clock,
        asset_a_path="/opt/retrovue/assets/SampleA.mp4",
        asset_b_path="/opt/retrovue/assets/SampleB.mp4",
        segment_seconds=30.0,
    )
    ok, err = svc.load_schedule(MockAlternatingScheduleService.MOCK_AB_CHANNEL_ID)
    assert ok and err is None

    # segment_index = 60_000 // 30_000 = 2 -> even -> asset A
    utc_ms = 60_000
    block = svc.get_block_at(MockAlternatingScheduleService.MOCK_AB_CHANNEL_ID, utc_ms)
    assert block is not None
    assert block.start_utc_ms <= utc_ms < block.end_utc_ms
    assert block.duration_ms == 30_000
    assert len(block.segments) == 1
    assert block.segments[0].asset_uri.endswith("SampleA.mp4")

    # segment_index = 31_000 // 30_000 = 1 -> odd -> asset B
    utc_ms_b = 31_000
    block_b = svc.get_block_at(MockAlternatingScheduleService.MOCK_AB_CHANNEL_ID, utc_ms_b)
    assert block_b is not None
    assert block_b.segments[0].asset_uri.endswith("SampleB.mp4")


def test_mock_alternating_get_block_at_wrong_channel_returns_none() -> None:
    clock = MasterClock()
    svc = MockAlternatingScheduleService(
        clock=clock,
        asset_a_path="/a.mp4",
        asset_b_path="/b.mp4",
        segment_seconds=10.0,
    )
    assert svc.get_block_at("other", 0) is None
