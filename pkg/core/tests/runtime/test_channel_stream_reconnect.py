"""
INV-CHANNEL-STREAM-RECONNECT-001: ChannelStream reconnects on upstream EOF.

When AIR crashes, the read side of the UDS gets EOF. ChannelStream must
reconnect via the factory (which resolves the *current* producer's socket
queue) instead of exiting.

Uses ``socketpair()`` for real EOF semantics:
1. Create socketpair — write end simulates AIR, read end goes to ChannelStream.
2. Write TS data → verify subscriber receives it.
3. Close write end → reader sees real EOF.
4. Factory is called again with a new socketpair.
5. Write more data → verify subscriber receives it again.
6. Same subscriber queue throughout (no interruption).
"""

from __future__ import annotations

import socket
import threading
import time
from queue import Empty

import pytest

from retrovue.runtime.channel_stream import ChannelStream, SocketTsSource


# TS sync byte (0x47) followed by padding to make a valid-looking 188-byte packet.
_TS_PACKET = b"\x47" + b"\x00" * 187


def _make_ts_chunk(n_packets: int = 10) -> bytes:
    return _TS_PACKET * n_packets


def _read_from_queue(q, min_bytes: int, timeout_s: float) -> bytes:
    """Read from subscriber queue until min_bytes collected or timeout."""
    data = b""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and len(data) < min_bytes:
        try:
            chunk = q.get(timeout=0.5)
            if chunk:
                data += chunk
        except Empty:
            continue
    return data


class _SimulatedAir:
    """Simulates the AIR write side of a socketpair.

    Each ``start()`` creates a fresh socketpair: the read end is stored in
    ``read_socket`` (for the factory) and the write end is used internally
    to push TS data.
    """

    def __init__(self) -> None:
        self.read_socket: socket.socket | None = None
        self._write_socket: socket.socket | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.generation = 0

    def start(self) -> None:
        """Create a new socketpair and start writing TS data."""
        self._stop.clear()
        r, w = socket.socketpair()
        self.read_socket = r
        self._write_socket = w
        self.generation += 1
        self._thread = threading.Thread(
            target=self._writer, daemon=True,
            name=f"SimAir-writer-gen{self.generation}",
        )
        self._thread.start()

    def _writer(self) -> None:
        chunk = _make_ts_chunk(10)
        while not self._stop.is_set():
            try:
                self._write_socket.sendall(chunk)
            except (BrokenPipeError, OSError):
                break
            self._stop.wait(0.01)

    def crash(self) -> None:
        """Simulate AIR crash: close the write end -> read side gets EOF."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._write_socket:
            self._write_socket.close()
            self._write_socket = None
        # read_socket left open -- ChannelStream still holds it, will see EOF

    def stop(self) -> None:
        """Full cleanup (both sides)."""
        self.crash()
        if self.read_socket:
            try:
                self.read_socket.close()
            except Exception:
                pass
            self.read_socket = None


# Tier: 3 | Integration simulation
def test_channel_stream_stop_interrupts_blocking_factory():
    """
    INV-CHANNEL-STREAM-SHUTDOWN-001

    When stop() is called, the upstream reader thread MUST exit within 5 seconds
    even if the ts_source_factory is in the middle of a blocking wait.

    Reproduces the CTRL+C shutdown scenario:
    - AIR exits → EOF → reader enters reconnect → factory blocks (e.g. queue.get)
    - stop() is called
    - Before fix: factory receives no stop_event → time.sleep(10s) → thread stuck
    - After fix: factory receives stop_event and exits within the deadline
    """
    air = _SimulatedAir()
    air.start()

    factory_blocking = threading.Event()
    call_count = 0

    def ts_source_factory(stop_event=None) -> SocketTsSource:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            sock = air.read_socket
            air.read_socket = None
            return SocketTsSource(sock)
        # Reconnect attempt: simulate production factory blocking on queue.get.
        # INV-CHANNEL-STREAM-SHUTDOWN-001: stop_event MUST be passed and MUST
        # unblock this wait; without it the factory sleeps 10s and the thread
        # cannot stop within the 5s deadline.
        factory_blocking.set()
        if stop_event is not None:
            stop_event.wait()
        else:
            time.sleep(10.0)
        raise RuntimeError("Factory cancelled or timed out")

    stream = ChannelStream(channel_id="shutdown-test", ts_source_factory=ts_source_factory)

    try:
        q = stream.subscribe("viewer-1")

        data = _read_from_queue(q, min_bytes=188 * 5, timeout_s=3.0)
        assert len(data) >= 188 * 5, "Phase 1: expected initial data"

        air.crash()  # EOF → reader enters reconnect → factory blocks
        assert factory_blocking.wait(timeout=3.0), "Factory should be called for reconnect"

        t0 = time.monotonic()
        stream.stop()
        elapsed = time.monotonic() - t0

        assert not stream.reader_thread.is_alive(), (
            "INV-CHANNEL-STREAM-SHUTDOWN-001: reader thread must exit after stop()"
        )
        assert elapsed < 5.0, (
            f"INV-CHANNEL-STREAM-SHUTDOWN-001: stop() took {elapsed:.1f}s (>5s). "
            f"Factory must receive and honor stop_event."
        )
    finally:
        stream.stop()
        air.stop()


# Tier: 3 | Integration simulation
def test_channel_stream_reconnect_on_eof():
    """
    INV-CHANNEL-STREAM-RECONNECT-001

    ChannelStream must reconnect via factory after upstream EOF.
    Same subscriber queue receives data from both the first and
    second simulated AIR sessions.
    """
    air = _SimulatedAir()
    factory_call_count = 0
    factory_ready = threading.Event()

    def ts_source_factory(stop_event=None) -> SocketTsSource:
        nonlocal factory_call_count
        factory_call_count += 1
        # Wait for AIR to be (re)started if needed
        if air.read_socket is None:
            factory_ready.wait(timeout=10.0)
        sock = air.read_socket
        air.read_socket = None  # consumed
        assert sock is not None, "Factory called but no socket available"
        return SocketTsSource(sock)

    # --- Phase 1: First AIR session ---
    air.start()
    stream = ChannelStream(
        channel_id="reconnect-test",
        ts_source_factory=ts_source_factory,
    )

    try:
        q = stream.subscribe("viewer-1")

        # Read a few chunks from the first session
        data_phase1 = _read_from_queue(q, min_bytes=188 * 20, timeout_s=5.0)

        assert len(data_phase1) >= 188 * 20, (
            f"Phase 1: expected >=3760 bytes, got {len(data_phase1)}"
        )
        assert data_phase1[0] == 0x47, "Phase 1: first byte should be TS sync"
        assert factory_call_count == 1, (
            f"Factory should have been called once, was called {factory_call_count} times"
        )

        # --- Phase 2: Crash AIR -> EOF on read side ---
        air.crash()

        # Give reader loop time to see EOF and enter reconnect
        time.sleep(0.3)

        # --- Phase 3: Restart AIR -> factory called again ---
        air.start()
        factory_ready.set()  # unblock factory if it's waiting

        # Read data from the second session (same queue!)
        data_phase3 = _read_from_queue(q, min_bytes=188 * 20, timeout_s=10.0)

        assert len(data_phase3) >= 188 * 20, (
            f"Phase 3: expected >=3760 bytes after reconnect, got {len(data_phase3)}"
        )
        assert data_phase3[0] == 0x47, "Phase 3: first byte should be TS sync"
        assert factory_call_count >= 2, (
            f"Factory should have been called at least twice (initial + reconnect), "
            f"was called {factory_call_count} times"
        )

    finally:
        stream.stop()
        air.stop()


# Tier: 3 | Integration simulation
def test_channel_stream_reconnect_factory_transient_failure():
    """
    Factory may temporarily fail (RuntimeError) during recovery swap.
    ChannelStream should retry via _connect_with_backoff and eventually
    succeed once the factory returns a valid source.
    """
    air = _SimulatedAir()
    factory_call_count = 0
    fail_count = 0
    factory_ready = threading.Event()

    def ts_source_factory(stop_event=None) -> SocketTsSource:
        nonlocal factory_call_count, fail_count
        factory_call_count += 1
        # Fail the first reconnect attempt to simulate transient state
        if factory_call_count == 2:
            fail_count += 1
            raise RuntimeError("Transient: no active_producer yet")
        # Wait for socket to be available
        if air.read_socket is None:
            factory_ready.wait(timeout=10.0)
        if air.read_socket is None:
            raise RuntimeError("No socket available after wait")
        sock = air.read_socket
        air.read_socket = None
        return SocketTsSource(sock)

    air.start()
    stream = ChannelStream(
        channel_id="reconnect-transient-test",
        ts_source_factory=ts_source_factory,
    )

    try:
        q = stream.subscribe("viewer-1")

        # Phase 1: normal data
        data = _read_from_queue(q, min_bytes=188 * 10, timeout_s=5.0)
        assert len(data) >= 188 * 10, f"Phase 1 expected data, got {len(data)}"

        # Phase 2: crash, then restart
        air.crash()
        time.sleep(0.3)
        air.start()
        factory_ready.set()

        # Phase 3: data resumes despite one factory failure
        data2 = _read_from_queue(q, min_bytes=188 * 10, timeout_s=15.0)

        assert len(data2) >= 188 * 10, (
            f"Phase 3: expected data after transient factory failure, got {len(data2)}"
        )
        assert fail_count == 1, "Factory should have failed once (transient)"
        assert factory_call_count >= 3, (
            f"Factory should have been called >=3 times (1 initial + 1 fail + 1 success), "
            f"was called {factory_call_count} times"
        )
    finally:
        stream.stop()
        air.stop()
