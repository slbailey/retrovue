"""
Phase 5 — ChannelManager timing & prefeed contract tests.

Stepped clock + recording sink; assert ordering, no duplicate LoadPreview, immutability.
"""

from __future__ import annotations

import pytest

from retrovue.runtime.playout_pipeline import PlayoutSegment
from retrovue.runtime.segment_orchestrator import RecordingSink, SegmentOrchestrator

CHANNEL_ID = "mock"
PREFEED_WINDOW_MS = 60_000  # 1 minute

# Fixed segments for tests (epoch ms)
T0_MS = 1_000_000_000_000  # first segment ends at T0 + 30min
SEG_A = PlayoutSegment(
    asset_path="assets/samplecontent.mp4",
    start_offset_ms=0,
    hard_stop_time_ms=T0_MS + 1_800_000,  # 30 min later
)
SEG_B = PlayoutSegment(
    asset_path="assets/filler.mp4",
    start_offset_ms=0,
    hard_stop_time_ms=T0_MS + 3_600_000,  # 1 hour from T0
)
SEG_C = PlayoutSegment(
    asset_path="assets/samplecontent.mp4",
    start_offset_ms=0,
    hard_stop_time_ms=T0_MS + 5_400_000,
)


def _make_now(ms: int):
    return lambda: ms


def test_phase5_load_preview_by_deadline():
    """Phase 5: LoadPreview issued no later than hard_stop_time_ms - prefeed_window_ms."""
    now_ms = T0_MS  # "current" time
    sink = RecordingSink()
    deadline_ms = SEG_A.hard_stop_time_ms - PREFEED_WINDOW_MS  # T0 + 30min - 1min

    def get_next(prev_end_ms: int | None):
        if prev_end_ms is None:
            return SEG_A
        if prev_end_ms == SEG_A.hard_stop_time_ms:
            return SEG_B
        return None

    orch = SegmentOrchestrator(
        get_now_epoch_ms=_make_now(now_ms),
        prefeed_window_ms=PREFEED_WINDOW_MS,
        sink=sink,
        channel_id=CHANNEL_ID,
        get_next_segment=get_next,
    )
    orch.tick()
    # Bootstrap: LoadPreview(SEG_A), SwitchToLive
    assert len(sink.load_preview_calls) == 1
    assert sink.load_preview_calls[0][0] == SEG_A
    assert len(sink.switch_to_live_calls) == 1

    # Advance time to just after prefeed deadline for next (SEG_B)
    orch.get_now_epoch_ms = _make_now(deadline_ms + 1)
    orch.tick()
    assert len(sink.load_preview_calls) == 2
    assert sink.load_preview_calls[1][0] == SEG_B
    # LoadPreview for SEG_B happened by deadline (we're at deadline+1)


def test_phase5_switch_to_live_at_boundary():
    """Phase 5: SwitchToLive at boundary (after LoadPreview for that segment)."""
    sink = RecordingSink()
    now_ms = T0_MS
    calls: list[int] = []

    def get_next(prev_end_ms: int | None):
        if prev_end_ms is None:
            return SEG_A
        if prev_end_ms == SEG_A.hard_stop_time_ms:
            return SEG_B
        return None

    def now_fn():
        calls.append(1)
        return now_ms

    orch = SegmentOrchestrator(
        get_now_epoch_ms=now_fn,
        prefeed_window_ms=PREFEED_WINDOW_MS,
        sink=sink,
        channel_id=CHANNEL_ID,
        get_next_segment=get_next,
    )
    orch.tick()
    assert len(sink.switch_to_live_calls) == 1
    # Advance to just before boundary
    boundary = SEG_A.hard_stop_time_ms
    orch.get_now_epoch_ms = _make_now(boundary - 1)
    orch.tick()
    assert len(sink.switch_to_live_calls) == 1
    # Advance to boundary
    orch.get_now_epoch_ms = _make_now(boundary)
    orch.tick()
    assert len(sink.switch_to_live_calls) == 2


def test_phase5_no_duplicate_load_preview_same_segment():
    """Phase 5: CM does not issue duplicate LoadPreview for same next segment on re-evaluation."""
    sink = RecordingSink()
    deadline_ms = SEG_A.hard_stop_time_ms - PREFEED_WINDOW_MS

    def get_next(prev_end_ms: int | None):
        if prev_end_ms is None:
            return SEG_A
        if prev_end_ms == SEG_A.hard_stop_time_ms:
            return SEG_B
        return None

    orch = SegmentOrchestrator(
        get_now_epoch_ms=_make_now(T0_MS),
        prefeed_window_ms=PREFEED_WINDOW_MS,
        sink=sink,
        channel_id=CHANNEL_ID,
        get_next_segment=get_next,
    )
    orch.tick()
    assert len(sink.load_preview_calls) == 1
    # Re-evaluate multiple times after prefeed deadline but before boundary
    orch.get_now_epoch_ms = _make_now(deadline_ms + 1000)
    orch.tick()
    orch.tick()
    orch.tick()
    # Still only one LoadPreview for SEG_B (no duplicates)
    assert len(sink.load_preview_calls) == 2
    assert sink.load_preview_calls[1][0] == SEG_B


def test_phase5_segments_immutable():
    """Phase 5: Segments are immutable; orchestrator does not mutate issued segments."""
    seg = PlayoutSegment(asset_path="a", start_offset_ms=0, hard_stop_time_ms=T0_MS)
    with pytest.raises(Exception):  # FrozenInstanceError
        seg.start_offset_ms = 999  # type: ignore[misc]
    sink = RecordingSink()
    orch = SegmentOrchestrator(
        get_now_epoch_ms=_make_now(T0_MS - 1),
        prefeed_window_ms=PREFEED_WINDOW_MS,
        sink=sink,
        channel_id=CHANNEL_ID,
        get_next_segment=lambda _: seg,
    )
    orch.tick()
    assert sink.load_preview_calls[0][0] is seg
    assert sink.load_preview_calls[0][0].start_offset_ms == 0


def test_phase5_orchestrator_drives_timeline():
    """Phase 5: CM drives the timeline; tests trigger evaluation explicitly (no wait for Air)."""
    sink = RecordingSink()
    now_ms = [T0_MS]

    def get_next(prev_end_ms: int | None):
        if prev_end_ms is None:
            return SEG_A
        return None

    orch = SegmentOrchestrator(
        get_now_epoch_ms=lambda: now_ms[0],
        prefeed_window_ms=PREFEED_WINDOW_MS,
        sink=sink,
        channel_id=CHANNEL_ID,
        get_next_segment=get_next,
    )
    orch.tick()
    assert len(sink.load_preview_calls) == 1
    assert len(sink.switch_to_live_calls) == 1
    # We drove by calling tick(); no "wait for Air to ask"
    now_ms[0] = SEG_A.hard_stop_time_ms
    orch.tick()
    assert len(sink.switch_to_live_calls) == 2
