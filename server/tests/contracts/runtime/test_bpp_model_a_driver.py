"""Model A: BlockPlanProducer driver contract.

Validates the new producer's behavior under the Model A RPC surface:
  - start() invokes launch_air exactly once with the current segment's asset.
  - The driver thread issues one air_load_preview + one air_switch_to_live
    per subsequent segment boundary.
  - air_switch_to_live receives target_boundary_time_ms equal to the
    segment's scheduled start (INV-LEADTIME-MEASUREMENT-001 via clock).
  - air_load_preview is called with exact frame counts (INV-FRAME-002).
  - No retry / no polling: exactly one RPC per boundary
    (INV-CONTROL-NO-POLL-001).
  - stop() calls terminate_air once.
"""

from __future__ import annotations

import queue
import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from retrovue.runtime.block_plan_producer import (
    BlockPlanProducer,
    _frames_for_ms,
    _resolve_jip_position,
    _segment_boundary_utc_ms,
)
from retrovue.runtime.config import (
    ChannelConfig,
    DEFAULT_PROGRAM_FORMAT,
    MOCK_CHANNEL_CONFIG,
    ProgramFormat,
)
from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment


# ----------------------------------------------------------------------
# Test doubles
# ----------------------------------------------------------------------


class FakeClock:
    """Deterministic clock; advances only on explicit calls."""

    def __init__(self, start_utc_ms: int = 1_700_000_000_000):
        self._now_ms = int(start_utc_ms)
        self._mono_ns = 0

    def advance_ms(self, ms: int) -> None:
        self._now_ms += int(ms)
        self._mono_ns += int(ms) * 1_000_000

    def now_utc(self) -> datetime:
        return datetime.fromtimestamp(self._now_ms / 1000.0, tz=timezone.utc)

    def now_utc_ms(self) -> int:
        return self._now_ms

    def monotonic(self) -> float:
        return self._mono_ns / 1e9

    def monotonic_ms(self) -> int:
        return self._mono_ns // 1_000_000

    def monotonic_ns(self) -> int:
        return self._mono_ns


class StubExecutionReader:
    def __init__(self, blocks: list[ScheduledBlock]):
        self._blocks = blocks

    def get_current_execution_block(self, channel_id: str, now_ms: int):
        for b in self._blocks:
            if b.start_utc_ms <= now_ms < b.end_utc_ms:
                return b
        return None

    def get_next_execution_block(self, channel_id: str, after_utc_ms: int):
        for b in self._blocks:
            if b.start_utc_ms >= after_utc_ms:
                return b
        return None

    def get_execution_depth_ms(self, channel_id: str, now_ms: int) -> int:
        if not self._blocks:
            return 0
        return max(0, self._blocks[-1].end_utc_ms - now_ms)

    def get_playlist_event_by_block_id(self, channel_id: str, block_id: str):
        for b in self._blocks:
            if b.block_id == block_id:
                return b
        return None


def _make_channel_config(channel_id_int: int = 42) -> ChannelConfig:
    return ChannelConfig(
        channel_id="chan-a",
        number=channel_id_int,
        channel_id_int=channel_id_int,
        name="Test Channel",
        program_format=DEFAULT_PROGRAM_FORMAT,
        schedule_source="dsl",
    )


def _make_block(
    block_id: str,
    start_utc_ms: int,
    segment_durations_ms: list[int],
    asset_prefix: str = "asset",
) -> ScheduledBlock:
    segs: list[ScheduledSegment] = []
    for i, dur in enumerate(segment_durations_ms):
        segs.append(
            ScheduledSegment(
                segment_type="content",
                asset_uri=f"/media/{asset_prefix}_{i}.mp4",
                asset_start_offset_ms=0,
                segment_duration_ms=int(dur),
            )
        )
    total = sum(segment_durations_ms)
    return ScheduledBlock(
        block_id=block_id,
        start_utc_ms=int(start_utc_ms),
        end_utc_ms=int(start_utc_ms + total),
        segments=tuple(segs),
    )


# ----------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------


class TestFrameCountHelper:
    def test_exact_30_1(self):
        assert _frames_for_ms(1000, 30, 1) == 30
        assert _frames_for_ms(1500, 30, 1) == 45

    def test_exact_30000_1001(self):
        # 1 second at 29.97fps = 29 whole frames (integer floor)
        assert _frames_for_ms(1000, 30000, 1001) == 29
        # 1001ms at 29.97fps = 30 frames exactly
        assert _frames_for_ms(1001, 30000, 1001) == 30

    def test_zero_denominator(self):
        assert _frames_for_ms(1000, 30, 0) == 0


class TestSegmentBoundaryHelper:
    def test_absolute_boundaries(self):
        block = _make_block("b", 1_000_000, [5_000, 7_000, 3_000])
        assert _segment_boundary_utc_ms(block, 0) == 1_000_000
        assert _segment_boundary_utc_ms(block, 1) == 1_005_000
        assert _segment_boundary_utc_ms(block, 2) == 1_012_000


class TestJipPositionHelper:
    def test_jip_inside_first_segment(self):
        block = _make_block("b", 0, [10_000, 10_000, 10_000])
        assert _resolve_jip_position(block, 3_000) == (0, 3_000)

    def test_jip_inside_middle_segment(self):
        block = _make_block("b", 0, [10_000, 10_000, 10_000])
        assert _resolve_jip_position(block, 15_000) == (1, 5_000)

    def test_jip_at_segment_boundary_advances(self):
        block = _make_block("b", 0, [10_000, 10_000, 10_000])
        # exactly at seg[1] start
        assert _resolve_jip_position(block, 10_000) == (1, 0)

    def test_jip_past_end_clamps_to_last(self):
        block = _make_block("b", 0, [10_000, 10_000])
        assert _resolve_jip_position(block, 1_000_000) == (1, 0)


# ----------------------------------------------------------------------
# start() + driver: per-segment LoadPreview + SwitchToLive
# ----------------------------------------------------------------------


def _install_model_a_stubs(monkeypatch, load_calls, switch_calls):
    """Patch launch_air / air_load_preview / air_switch_to_live / terminate_air
    at the block_plan_producer import boundary."""
    import retrovue.runtime.block_plan_producer as bpp_mod

    def fake_launch_air(*, playout_request, clock, channel_config, **kwargs):
        load_calls.append({
            "phase": "launch",
            "channel_id": playout_request["channel_id"],
            "asset_path": playout_request["asset_path"],
            "start_pts": playout_request["start_pts"],
            "segment_id": playout_request["segment_id"],
        })
        proc = MagicMock()
        proc.poll.return_value = None  # "still alive"
        # Mimic launch_air's queue containing the accepted AIR socket
        rq: queue.Queue = queue.Queue()
        rq.put(MagicMock())
        return (proc, "/tmp/retrovue/air/test.sock", rq, "127.0.0.1:60000")

    def fake_load_preview(grpc_addr, channel_id_int, asset_path,
                          start_frame, frame_count, fps_num, fps_den,
                          timeout_s=90):
        load_calls.append({
            "phase": "driver",
            "grpc_addr": grpc_addr,
            "channel_id_int": channel_id_int,
            "asset_path": asset_path,
            "start_frame": start_frame,
            "frame_count": frame_count,
            "fps_numerator": fps_num,
            "fps_denominator": fps_den,
        })
        return True

    def fake_switch_to_live(grpc_addr, channel_id_int, *, clock,
                             timeout_s=30, target_boundary_time_ms=0):
        # Mirror the real impl: issued_at_time_ms is read from clock each call.
        issued_ms = clock.now_utc_ms()
        switch_calls.append({
            "grpc_addr": grpc_addr,
            "channel_id_int": channel_id_int,
            "target_boundary_time_ms": target_boundary_time_ms,
            "issued_at_time_ms": issued_ms,
        })
        # RESULT_CODE_OK=1
        return (True, 1, "")

    terminate_calls: list[object] = []

    def fake_terminate_air(process):
        terminate_calls.append(process)

    monkeypatch.setattr(bpp_mod, "launch_air", fake_launch_air)
    monkeypatch.setattr(bpp_mod, "air_load_preview", fake_load_preview)
    monkeypatch.setattr(bpp_mod, "air_switch_to_live", fake_switch_to_live)
    monkeypatch.setattr(bpp_mod, "terminate_air", fake_terminate_air)
    return terminate_calls


class TestStartLaunchAir:
    def test_start_invokes_launch_air_with_first_segment(self, monkeypatch):
        clock = FakeClock(start_utc_ms=0)
        block = _make_block("B0", 0, [30_000, 30_000])
        reader = StubExecutionReader([block])
        cfg = _make_channel_config(channel_id_int=7)

        loads: list[dict] = []
        switches: list[dict] = []
        _install_model_a_stubs(monkeypatch, loads, switches)

        producer = BlockPlanProducer(
            channel_id="chan-a",
            clock=clock,
            configuration={},
            channel_config=cfg,
            execution_reader=reader,
            evidence_endpoint="",
        )

        ok = producer.start(clock.now_utc(), jip_offset_ms=0)
        try:
            assert ok is True
            assert producer.status.value == "running"
            assert producer.socket_path == "/tmp/retrovue/air/test.sock"
            # launch_air called exactly once.
            launch_events = [c for c in loads if c.get("phase") == "launch"]
            assert len(launch_events) == 1
            assert launch_events[0]["asset_path"] == "/media/asset_0.mp4"
            assert launch_events[0]["start_pts"] == 0
            assert launch_events[0]["channel_id"] == "chan-a"
        finally:
            producer.stop()

    def test_start_with_jip_plays_active_segment(self, monkeypatch):
        clock = FakeClock(start_utc_ms=15_000)  # 15s into block
        block = _make_block("B0", 0, [10_000, 10_000, 10_000])
        reader = StubExecutionReader([block])
        cfg = _make_channel_config(channel_id_int=1)

        loads: list[dict] = []
        switches: list[dict] = []
        _install_model_a_stubs(monkeypatch, loads, switches)

        producer = BlockPlanProducer(
            channel_id="chan-a",
            clock=clock,
            channel_config=cfg,
            execution_reader=reader,
        )

        ok = producer.start(clock.now_utc(), jip_offset_ms=15_000)
        try:
            assert ok is True
            launch = [c for c in loads if c.get("phase") == "launch"][0]
            # jip=15000 → active segment is seg[1] with 5000ms offset inside it
            assert launch["asset_path"] == "/media/asset_1.mp4"
            assert launch["start_pts"] == 5_000
        finally:
            producer.stop()


class TestDriverPerSegmentRpcs:
    def test_driver_issues_one_preview_one_switch_per_boundary(self, monkeypatch):
        clock = FakeClock(start_utc_ms=0)
        block = _make_block("B0", 0, [30_000, 30_000, 30_000])
        reader = StubExecutionReader([block])
        cfg = _make_channel_config(channel_id_int=9)

        loads: list[dict] = []
        switches: list[dict] = []
        _install_model_a_stubs(monkeypatch, loads, switches)

        producer = BlockPlanProducer(
            channel_id="chan-a",
            clock=clock,
            channel_config=cfg,
            execution_reader=reader,
        )

        assert producer.start(clock.now_utc(), jip_offset_ms=0) is True

        # Advance the clock so the driver crosses seg[1] and seg[2] boundaries.
        # Give the driver a few ticks to observe the clock jump and issue RPCs.
        deadline = 5.0
        polled_enough = False
        import time as _time
        start_real = _time.monotonic()
        clock.advance_ms(120_000)  # well past both boundaries
        while _time.monotonic() - start_real < deadline:
            _time.sleep(0.05)
            driver_loads = [c for c in loads if c.get("phase") == "driver"]
            if len(driver_loads) >= 2 and len(switches) >= 2:
                polled_enough = True
                break

        producer.stop()

        assert polled_enough, (
            f"driver did not issue expected RPCs in time: "
            f"driver_loads={[c for c in loads if c.get('phase') == 'driver']}, "
            f"switches={switches}"
        )

        driver_loads = [c for c in loads if c.get("phase") == "driver"]
        # Exactly two subsequent segment switches (seg[1], seg[2]).
        assert len(driver_loads) == 2, driver_loads
        assert len(switches) == 2, switches

        # INV-FRAME-002: exact frame_count per segment (30s @ 30000/1001 = 898 frames).
        fps_num, fps_den = DEFAULT_PROGRAM_FORMAT.frame_rate_num, DEFAULT_PROGRAM_FORMAT.frame_rate_den
        expected_fc = (30_000 * fps_num) // (1000 * fps_den)
        for lp in driver_loads:
            assert lp["frame_count"] == expected_fc
            assert lp["fps_numerator"] == fps_num
            assert lp["fps_denominator"] == fps_den

        # Preview URIs are seg[1], seg[2] in order.
        assert driver_loads[0]["asset_path"] == "/media/asset_1.mp4"
        assert driver_loads[1]["asset_path"] == "/media/asset_2.mp4"

        # INV-LEADTIME-MEASUREMENT-001: target_boundary_time_ms equals the
        # segment's absolute scheduled start. seg[1] = 30_000, seg[2] = 60_000.
        assert switches[0]["target_boundary_time_ms"] == 30_000
        assert switches[1]["target_boundary_time_ms"] == 60_000
        # issued_at_time_ms was read from the injected clock each call
        # (present and monotonic-non-decreasing).
        assert switches[0]["issued_at_time_ms"] <= switches[1]["issued_at_time_ms"]

        # INV-CONTROL-NO-POLL-001: one RPC per boundary, no retry.
        # (We already asserted exactly 2+2 above.)


class TestStopTerminatesAir:
    def test_stop_calls_terminate_air_once(self, monkeypatch):
        clock = FakeClock(start_utc_ms=0)
        block = _make_block("B0", 0, [30_000, 30_000])
        reader = StubExecutionReader([block])
        cfg = _make_channel_config(channel_id_int=3)

        loads: list[dict] = []
        switches: list[dict] = []
        terminate_calls = _install_model_a_stubs(monkeypatch, loads, switches)

        producer = BlockPlanProducer(
            channel_id="chan-a", clock=clock,
            channel_config=cfg, execution_reader=reader,
        )
        producer.start(clock.now_utc(), jip_offset_ms=0)

        producer.stop(reason="unit_test")

        assert len(terminate_calls) == 1
        assert producer.status.value == "stopped"
        assert producer.socket_path is None
        # stop() is idempotent.
        producer.stop(reason="again")
        assert len(terminate_calls) == 1

    def test_stop_without_start_is_noop(self, monkeypatch):
        clock = FakeClock(start_utc_ms=0)
        cfg = _make_channel_config()
        terminate_calls = _install_model_a_stubs(monkeypatch, [], [])

        producer = BlockPlanProducer(
            channel_id="chan-a", clock=clock,
            channel_config=cfg, execution_reader=StubExecutionReader([]),
        )
        assert producer.stop() is True
        assert terminate_calls == []
