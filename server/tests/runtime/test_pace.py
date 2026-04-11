from __future__ import annotations

import threading
import time

import pytest

from retrovue.runtime.clock import RealTimeMasterClock, SteppedMasterClock
from retrovue.runtime.pace import PaceController, PaceParticipant


class RecordingParticipant(PaceParticipant):
    def __init__(self) -> None:
        self.records: list[tuple[float, float]] = []

    def on_paced_tick(self, t_now: float, dt: float) -> None:
        self.records.append((t_now, dt))


def test_pace_controller_real_time_smoke():
    sleep_calls: list[float] = []

    def fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)
        time.sleep(duration)

    clock = RealTimeMasterClock()
    controller = PaceController(clock=clock, target_hz=20.0, sleep_fn=fake_sleep)
    participant = RecordingParticipant()
    controller.add_participant(participant)

    runner = threading.Thread(target=controller.run_forever, daemon=True)
    runner.start()
    time.sleep(0.12)
    controller.stop()
    runner.join(timeout=1.0)

    assert participant.records, "expected paced ticks"
    frame_interval = 1.0 / 20.0
    max_dt = frame_interval * 3.0 + 1e-6
    for _, dt in participant.records:
        assert 0.0 < dt <= max_dt
    assert sleep_calls, "real-time mode should perform sleeps"
    assert all(call > 0 for call in sleep_calls)


def test_pace_controller_stepped_advances_and_clamps():
    clock = SteppedMasterClock()
    controller = PaceController(clock=clock, target_hz=10.0, sleep_fn=None)
    participant = RecordingParticipant()
    controller.add_participant(participant)

    # Initial tick (no advance yet) still occurs with default frame interval.
    controller.run_once()
    assert participant.records[-1][1] == pytest.approx(0.1)

    # Run once without advancing time: should not produce a tick.
    assert controller.run_once() is False

    # Advance by a large amount; dt should be clamped to 3 frames (0.3s).
    clock.advance(1.0)
    controller.run_once()
    assert participant.records[-1][1] == pytest.approx(0.3)


def test_participant_can_remove_itself_safely():
    clock = SteppedMasterClock()
    controller = PaceController(clock=clock, target_hz=10.0, sleep_fn=None)

    class SelfRemoving(PaceParticipant):
        def __init__(self) -> None:
            self.count = 0

        def on_paced_tick(self, t_now: float, dt: float) -> None:
            self.count += 1
            controller.remove_participant(self)

    participant = SelfRemoving()
    controller.add_participant(participant)
    controller.run_once()
    # Second run should not call the participant because it removed itself.
    controller.run_once()
    assert participant.count == 1



