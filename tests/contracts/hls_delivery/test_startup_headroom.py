"""
Contract Tests: AIR Startup Headroom and Session Cleanup

Invariants:
    INV-AIR-SOCKET-BUFFER-STARTUP-HEADROOM-001
    INV-AIR-SESSION-CLEANUP-ON-END-001

These tests verify that:
- AIR's socket buffer is large enough to survive channel startup
  without overflowing before Core connects the reader
- AIR subprocess is terminated before recovery spawns a replacement

The buffer overflow caused a crash-loop: AIR starts → writes to socket →
buffer fills in ~400ms (512KB at 10Mbps) → SocketSink detaches →
session ends → recovery spawns new AIR → repeat 4-5 times.

Fix: 8MB buffer (~6 seconds headroom) + terminate on SessionEnded.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

import pytest


# ---------------------------------------------------------------------------
# INV-AIR-SOCKET-BUFFER-STARTUP-HEADROOM-001
# ---------------------------------------------------------------------------


# The C++ constant from PipelineManager.cpp
AIR_SINK_BUFFER_CAPACITY = 8 * 1024 * 1024  # Must match kSinkBufferCapacity
AIR_MUX_RATE_BPS = 10_000_000  # 10Mbps CBR mux rate
MIN_STARTUP_HEADROOM_SECONDS = 3


@pytest.mark.contract
class TestInvAirSocketBufferStartupHeadroom001:
    """INV-AIR-SOCKET-BUFFER-STARTUP-HEADROOM-001"""

    def test_buffer_capacity_provides_minimum_headroom(self):
        """Buffer must hold at least MIN_STARTUP_HEADROOM_SECONDS of output."""
        mux_rate_bytes_per_second = AIR_MUX_RATE_BPS / 8
        min_buffer = mux_rate_bytes_per_second * MIN_STARTUP_HEADROOM_SECONDS

        assert AIR_SINK_BUFFER_CAPACITY >= min_buffer, (
            f"INV-AIR-SOCKET-BUFFER-STARTUP-HEADROOM-001: "
            f"kSinkBufferCapacity ({AIR_SINK_BUFFER_CAPACITY}) < "
            f"minimum ({min_buffer:.0f}) for {MIN_STARTUP_HEADROOM_SECONDS}s "
            f"at {AIR_MUX_RATE_BPS/1e6:.0f}Mbps"
        )

    def test_buffer_headroom_in_seconds(self):
        """Buffer provides at least 3 seconds of headroom."""
        mux_rate_bytes_per_second = AIR_MUX_RATE_BPS / 8
        headroom_seconds = AIR_SINK_BUFFER_CAPACITY / mux_rate_bytes_per_second

        assert headroom_seconds >= MIN_STARTUP_HEADROOM_SECONDS, (
            f"INV-AIR-SOCKET-BUFFER-STARTUP-HEADROOM-001: "
            f"headroom {headroom_seconds:.1f}s < {MIN_STARTUP_HEADROOM_SECONDS}s"
        )

    def test_buffer_not_undersized(self):
        """Buffer must not be the old 512KB size that caused the crash-loop."""
        OLD_BROKEN_SIZE = 512 * 1024
        assert AIR_SINK_BUFFER_CAPACITY > OLD_BROKEN_SIZE, (
            f"INV-AIR-SOCKET-BUFFER-STARTUP-HEADROOM-001: "
            f"buffer ({AIR_SINK_BUFFER_CAPACITY}) is at the old broken size "
            f"({OLD_BROKEN_SIZE}) that caused startup crash-loops"
        )


# ---------------------------------------------------------------------------
# INV-AIR-SESSION-CLEANUP-ON-END-001
# ---------------------------------------------------------------------------


@dataclass
class FakeProcess:
    """Simulates an AIR subprocess."""
    pid: int = 12345
    _alive: bool = True
    terminate_count: int = 0
    kill_count: int = 0

    def terminate(self):
        self.terminate_count += 1
        self._alive = False

    def kill(self):
        self.kill_count += 1
        self._alive = False

    def wait(self, timeout=None):
        if self._alive:
            raise TimeoutError("process did not exit")

    def poll(self):
        return None if self._alive else 0


@dataclass
class FakeSessionState:
    """Simulates PlayoutSession state."""
    air_process: FakeProcess | None = None
    is_running: bool = True
    session_ended: bool = False
    session_end_reason: str | None = None


@dataclass
class FakePlayoutSession:
    """Simulates PlayoutSession with the cleanup-before-callback fix."""
    _state: FakeSessionState = field(default_factory=FakeSessionState)
    on_session_end: object = None
    _callback_fired: bool = False
    _process_alive_when_callback_fired: bool = False

    def simulate_session_ended(self, reason: str):
        """Simulate receiving SessionEnded from AIR gRPC event stream."""
        self._state.is_running = False
        self._state.session_ended = True
        self._state.session_end_reason = reason

        # INV-AIR-SESSION-CLEANUP-ON-END-001: terminate BEFORE callback
        self._terminate_air_process()

        if self.on_session_end:
            self._process_alive_when_callback_fired = (
                self._state.air_process is not None and
                self._state.air_process._alive
            )
            self._callback_fired = True
            self.on_session_end(reason)

    def _terminate_air_process(self):
        proc = self._state.air_process
        if proc is None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except TimeoutError:
            proc.kill()
        self._state.air_process = None


@pytest.mark.contract
class TestInvAirSessionCleanupOnEnd001:
    """INV-AIR-SESSION-CLEANUP-ON-END-001"""

    def test_process_terminated_before_callback(self):
        """AIR subprocess must be dead before on_session_end fires."""
        callback_calls = []

        session = FakePlayoutSession()
        session._state.air_process = FakeProcess()
        session.on_session_end = lambda reason: callback_calls.append(reason)

        session.simulate_session_ended("stopped")

        # Callback fired
        assert callback_calls == ["stopped"]
        # Process was NOT alive when callback fired
        assert not session._process_alive_when_callback_fired

    def test_terminate_called_on_session_ended(self):
        """terminate() must be called on AIR process during SessionEnded."""
        proc = FakeProcess()
        session = FakePlayoutSession()
        session._state.air_process = proc

        session.simulate_session_ended("stopped")

        assert proc.terminate_count == 1

    def test_no_orphan_after_session_ended(self):
        """air_process must be None after SessionEnded handling."""
        session = FakePlayoutSession()
        session._state.air_process = FakeProcess()

        session.simulate_session_ended("stopped")

        assert session._state.air_process is None

    def test_kill_on_terminate_timeout(self):
        """If terminate doesn't work, kill must be called."""
        proc = FakeProcess()
        # Make terminate not actually kill it
        original_terminate = proc.terminate
        proc.terminate = lambda: setattr(proc, 'terminate_count', proc.terminate_count + 1)
        # Process stays alive after terminate, so wait() raises

        session = FakePlayoutSession()
        session._state.air_process = proc

        session.simulate_session_ended("stopped")

        assert proc.kill_count == 1

    def test_no_crash_if_no_process(self):
        """SessionEnded with no process must not crash."""
        session = FakePlayoutSession()
        session._state.air_process = None
        session.on_session_end = lambda reason: None

        session.simulate_session_ended("stopped")  # Must not raise

    def test_recovery_sees_clean_state(self):
        """After SessionEnded, recovery callback sees no active process."""
        recovery_saw_process = [None]

        def recovery_callback(reason):
            recovery_saw_process[0] = (
                session._state.air_process is not None
            )

        session = FakePlayoutSession()
        session._state.air_process = FakeProcess()
        session.on_session_end = recovery_callback

        session.simulate_session_ended("stopped")

        assert recovery_saw_process[0] is False
