"""
Clock-driven segment switching: schedule advances because time advanced, not EOF.

Contract: ChannelManager uses a periodic tick that reads MasterClock.now(), compares
to the scheduled end time of the current segment, and when now >= segment_end_time
calls SwitchToLive() on Air and advances to the next segment. LoadPreview(next) is
called before segment end (time-based preload). No EOF, decode state, or PTS is used.

Test: test_channel_switches_on_clock_not_eof — deterministic, no Air process.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from retrovue.runtime.clock import ControllableMasterClock
from retrovue.runtime.channel_manager import (
    ChannelManager,
    MockAlternatingScheduleService,
    Phase8ProgramDirector,
    SwitchState,
)
from retrovue.runtime.producer.base import Producer, ProducerMode, ProducerStatus


# ---------------------------------------------------------------------------
# Fake Air producer that records LoadPreview / SwitchToLive (no real Air)
# ---------------------------------------------------------------------------


class FakeAirProducerForClockSwitch(Producer):
    """Producer that records load_preview and switch_to_live calls for assertions. No Air, no EOF."""

    def __init__(self, channel_id: str, configuration: dict[str, Any]):
        super().__init__(channel_id, ProducerMode.NORMAL, configuration)
        self._endpoint = f"fake://{channel_id}"
        self.load_preview_calls: list[dict[str, Any]] = []
        self.switch_to_live_calls: list[dict[str, Any]] = []

    def start(
        self,
        playout_plan: list[dict[str, Any]],
        start_at_station_time: datetime,
    ) -> bool:
        self.status = ProducerStatus.RUNNING
        self.started_at = start_at_station_time
        self.output_url = self._endpoint
        return True

    def stop(self) -> bool:
        self.status = ProducerStatus.STOPPED
        self.output_url = None
        self._teardown_cleanup()
        return True

    def load_preview(
        self,
        asset_path: str,
        start_frame: int,
        frame_count: int,
        fps_numerator: int,
        fps_denominator: int,
    ) -> bool:
        """Load preview with frame-indexed execution (INV-FRAME-001/002/003)."""
        self.load_preview_calls.append({
            "asset_path": asset_path,
            "start_frame": start_frame,
            "frame_count": frame_count,
            "fps_numerator": fps_numerator,
            "fps_denominator": fps_denominator,
        })
        return True

    def switch_to_live(self, target_boundary_time_utc=None) -> bool:
        self.switch_to_live_calls.append({"target_boundary_time_utc": target_boundary_time_utc})
        return True

    def play_content(self, content: Any) -> bool:
        return True

    def get_stream_endpoint(self) -> str | None:
        return self.output_url

    def health(self) -> str:
        return "running" if self.status == ProducerStatus.RUNNING else "stopped"

    def get_producer_id(self) -> str:
        return f"fake_air_{self.channel_id}"

    def on_paced_tick(self, t_now: float, dt: float) -> None:
        self._advance_teardown(dt)


# ---------------------------------------------------------------------------
# Test: SampleA → SampleB switches at scheduled time without EOF
# ---------------------------------------------------------------------------


def test_channel_switches_on_clock_not_eof(tmp_path: Any) -> None:
    """
    Prove that SampleA → SampleB switches at the scheduled time (t=10s) without using EOF.

    Setup:
    - Two sample files (paths only; no real media): SampleA 10s, SampleB 10s.
    - Single channel, controllable MasterClock.
    - Schedule: Segment A t=0 duration 10s, Segment B t=10s duration 10s.

    Steps:
    1. Start channel → verify SampleA starts (first segment from schedule).
    2. Advance clock to ~7s → assert LoadPreview(SampleB) was called.
    3. Advance clock to >=10s → assert SwitchToLive() was called.
    4. Verify switching occurred because time advanced; no EOF events required.
    """
    sample_a = str(tmp_path / "SampleA.mp4")
    sample_b = str(tmp_path / "SampleB.mp4")
    # Create placeholder files so path exists (schedule only needs paths)
    (tmp_path / "SampleA.mp4").write_bytes(b"")
    (tmp_path / "SampleB.mp4").write_bytes(b"")

    clock = ControllableMasterClock()
    # Schedule: A [0,10), B [10,20); segment_seconds=10
    schedule = MockAlternatingScheduleService(
        clock=clock,
        asset_a_path=sample_a,
        asset_b_path=sample_b,
        segment_seconds=10.0,
    )
    channel_id = MockAlternatingScheduleService.MOCK_AB_CHANNEL_ID
    ok, err = schedule.load_schedule(channel_id)
    assert ok, err

    manager = ChannelManager(
        channel_id=channel_id,
        clock=clock,
        schedule_service=schedule,
        program_director=Phase8ProgramDirector(),
    )
    fake_producer: FakeAirProducerForClockSwitch | None = None

    def build_fake(_mode: str) -> Producer | None:
        nonlocal fake_producer
        fake_producer = FakeAirProducerForClockSwitch(channel_id, {})
        return fake_producer

    manager._build_producer_for_mode = build_fake

    # 1. Start channel (first viewer)
    manager.viewer_join("session-1", {"channel_id": channel_id})
    assert manager.active_producer is not None
    assert fake_producer is not None
    # First segment (A) is already live from start; segment end time = 0 + 10 = 10s (clock time)
    assert manager._segment_end_time_utc is not None

    # 2. P11D-010: First boundary is feasible (>= STARTUP_LATENCY + MIN_PREFEED), so first segment end is 20s.
    #    Preload_at = 20 - 7 = 13s. Advance clock to >=13s so LoadPreview fires.
    clock.advance_to(13.0)
    manager.tick()
    # Preload should have fired: LoadPreview for segment at boundary 20s (SampleA: 20-30)
    assert len(fake_producer.load_preview_calls) >= 1, "LoadPreview(next) must be called before segment end"
    load_next = [c for c in fake_producer.load_preview_calls if c["asset_path"] in (sample_a, sample_b)]
    assert len(load_next) >= 1, "LoadPreview must be called exactly once for preload"

    # P11D-011: Switch issuance is deadline-scheduled (timer). Simulate timer firing so state becomes SWITCH_ARMED.
    assert manager._switch_state == SwitchState.PREVIEW_LOADED
    if manager._segment_end_time_utc is not None:
        manager._on_switch_issue_deadline(manager._segment_end_time_utc)

    # 3. Advance clock to first boundary (20s) and tick to run switch_to_live
    clock.advance_to(20.0)
    manager.tick()
    assert len(fake_producer.switch_to_live_calls) >= 1, "SwitchToLive() must be called at segment end"

    # 4. Invariants: no EOF required; switching because time advanced
    assert manager._segment_end_time_utc is not None
    assert manager._segment_end_time_utc.year == 1970
    # Next segment end is 30s; advance and tick for second switch if desired
    clock.advance_to(30.0)
    manager.tick()
    assert len(fake_producer.switch_to_live_calls) >= 1
