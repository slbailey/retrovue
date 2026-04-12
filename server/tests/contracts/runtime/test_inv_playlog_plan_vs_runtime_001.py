"""
Contract tests — INV-PLAYLOG-PLAN-VS-RUNTIME-001

The Playlog Plan may persist segment-shaped JSON on PlaylistEvent rows, but the
executable timeline for AIR is the runtime playlog: join-aware transforms
(e.g. _apply_jip_to_segments) MUST run between persisted plan and emission.
"""
from __future__ import annotations

import copy

from retrovue.runtime.channel_manager import _apply_jip_to_segments


def _sample_playlog_plan_segments() -> list[dict]:
    """Minimal PlaylistEvent-style list (planned materialization)."""
    return [
        {
            "segment_index": 0,
            "segment_type": "content",
            "title": "A",
            "asset_uri": "/media/a.mp4",
            "asset_start_offset_ms": 0,
            "segment_duration_ms": 60_000,
        },
        {
            "segment_index": 1,
            "segment_type": "commercial",
            "title": "Ad",
            "asset_uri": "/ads/x.mp4",
            "asset_start_offset_ms": 0,
            "segment_duration_ms": 30_000,
        },
    ]


class TestInvPlaylogPlanVsRuntime001:
    """INV-PLAYLOG-PLAN-VS-RUNTIME-001: runtime playlog ≠ raw persisted plan under JIP."""

    def test_jip_transform_changes_segments_relative_to_persisted_plan(self):
        plan_segments = _sample_playlog_plan_segments()
        persisted_snapshot = copy.deepcopy(plan_segments)
        jip_offset_ms = 45_000
        total_ms = sum(s["segment_duration_ms"] for s in plan_segments)
        block_dur_ms = total_ms - jip_offset_ms

        runtime_segments = _apply_jip_to_segments(
            plan_segments, jip_offset_ms, block_dur_ms
        )

        assert runtime_segments != persisted_snapshot
        assert len(runtime_segments) <= len(persisted_snapshot)
        first = runtime_segments[0]
        assert first["asset_start_offset_ms"] == 45_000
        assert first["segment_duration_ms"] == 15_000

    def test_zero_jip_preserves_planned_list_for_this_shape(self):
        plan_segments = _sample_playlog_plan_segments()
        total_ms = sum(s["segment_duration_ms"] for s in plan_segments)
        runtime_segments = _apply_jip_to_segments(plan_segments, 0, total_ms)
        assert len(runtime_segments) == len(plan_segments)
        assert runtime_segments[0]["asset_start_offset_ms"] == 0
        assert runtime_segments[0]["segment_duration_ms"] == 60_000
