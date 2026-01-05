from __future__ import annotations

import time

from retrovue.runtime.clock import RealTimeMasterClock, SteppedMasterClock
from retrovue.runtime.program_director import ProgramDirector


def test_program_director_start_stop_without_channels():
    clock = RealTimeMasterClock()
    director = ProgramDirector(clock=clock, target_hz=15.0)

    director.start()
    thread = getattr(director, "_pace_thread", None)
    assert thread is not None
    assert thread.daemon is True
    assert thread.name == "program-director-pace"

    # Give the pacing loop a moment to spin.
    time.sleep(0.05)
    director.stop(timeout=1.0)

    # Second stop should be idempotent.
    director.stop(timeout=1.0)

    thread = getattr(director, "_pace_thread", None)
    assert thread is None or not thread.is_alive()


def test_program_director_stepped_clock_no_sleep():
    clock = SteppedMasterClock()
    director = ProgramDirector(clock=clock, target_hz=10.0, sleep_fn=None)

    director.start()
    # Because sleep_fn=None and clock is stepped, advance time so the loop emits ticks.
    clock.advance(0.1)
    time.sleep(0.01)
    director.stop(timeout=1.0)

    thread = getattr(director, "_pace_thread", None)
    assert thread is None or not thread.is_alive()

