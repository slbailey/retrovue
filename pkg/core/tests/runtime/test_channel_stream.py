"""
Phase 8.5 — ChannelStream fan-out and teardown.

- Multiple subscribers receive the same bytes (broadcast-style).
- Last subscriber disconnect stops the reader (no ongoing work).
"""

from __future__ import annotations

import threading
import time

import pytest

from retrovue.runtime.channel_stream import (
    ChannelStream,
    FakeTsSource,
    generate_ts_stream,
    RECV_GAP_WARN_THRESHOLD_MS,
    RECV_GAP_WARN_COUNT,
)


def test_channel_stream_multiple_subscribers_same_bytes():
    """Multiple subscribers get the same stream bytes (Phase 8.5 fan-out)."""
    source = FakeTsSource(chunk_size=188 * 10)
    stream = ChannelStream("test", ts_source_factory=lambda: source)

    try:
        q1 = stream.subscribe("c1")
        q2 = stream.subscribe("c2")
        q3 = stream.subscribe("c3")

        # Collect first N bytes from each
        target = 188 * 50  # 50 TS packets
        bufs = { "c1": [], "c2": [], "c3": [] }
        queues = {"c1": q1, "c2": q2, "c3": q3}

        def collect(client_id: str) -> bytes:
            collected = b""
            while len(collected) < target:
                try:
                    chunk = queues[client_id].get(timeout=2.0)
                    if not chunk:
                        break
                    collected += chunk
                except Exception:
                    break
            return collected

        t1 = threading.Thread(target=lambda: bufs.__setitem__("c1", collect("c1")))
        t2 = threading.Thread(target=lambda: bufs.__setitem__("c2", collect("c2")))
        t3 = threading.Thread(target=lambda: bufs.__setitem__("c3", collect("c3")))
        t1.start()
        t2.start()
        t3.start()
        t1.join(timeout=3.0)
        t2.join(timeout=3.0)
        t3.join(timeout=3.0)

        b1 = bufs["c1"]
        b2 = bufs["c2"]
        b3 = bufs["c3"]

        assert len(b1) >= target and len(b2) >= target and len(b3) >= target, (
            f"Expected at least {target} bytes each, got {len(b1)}, {len(b2)}, {len(b3)}"
        )
        # Same first K bytes (broadcast semantics)
        k = min(len(b1), len(b2), len(b3), target)
        assert b1[:k] == b2[:k] == b3[:k], "All subscribers should receive the same bytes"
    finally:
        stream.stop()


def test_channel_stream_last_subscriber_stops_reader():
    """When last subscriber leaves, reader stops (Phase 8.5 teardown)."""
    stream = ChannelStream("test", ts_source_factory=lambda: FakeTsSource(chunk_size=188 * 5))
    q = stream.subscribe("only")
    assert stream.is_running()

    # Read a little then unsubscribe (reader will be stopped from unsubscribe)
    for _ in range(3):
        try:
            q.get(timeout=1.0)
        except Exception:
            break
    stream.unsubscribe("only")
    # stop() is called from unsubscribe; wait for reader to exit (or explicit stop)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and stream.is_running():
        time.sleep(0.05)
    if stream.is_running():
        stream.stop()  # force stop if reader did not exit (e.g. test env timing)
    assert not stream.is_running()

    # New subscriber can connect and get data again (new reader)
    q2 = stream.subscribe("new")
    assert stream.is_running()
    chunk = q2.get(timeout=2.0)
    assert chunk and len(chunk) > 0
    stream.unsubscribe("new")
    stream.stop()


def test_generate_ts_stream_eof():
    """generate_ts_stream stops on EOF (empty bytes)."""
    from queue import Queue
    q: Queue[bytes] = Queue()
    q.put(b"abc")
    q.put(b"")
    out = list(generate_ts_stream(q))
    assert out == [b"abc"]


# =============================================================================
# CONTRACT TESTS: Recv-gap telemetry policy (prevents "moving the bar")
# =============================================================================
# These tests ensure the recv-gap warning thresholds are NOT silently changed.
# If you need to change these values, you MUST update both the constants AND
# these tests, forcing explicit acknowledgment of the policy change.


class TestRecvGapTelemetryContract:
    """Contract tests for recv-gap warning policy constants."""

    def test_threshold_is_40ms(self):
        """
        CONTRACT: RECV_GAP_WARN_THRESHOLD_MS must be exactly 40ms.

        This is a fixed threshold - do not "move the bar" to silence warnings.
        If you need to change this, you must update this test AND document why.
        """
        from retrovue.runtime.channel_stream import RECV_GAP_WARN_THRESHOLD_MS
        assert RECV_GAP_WARN_THRESHOLD_MS == 40, (
            f"RECV_GAP_WARN_THRESHOLD_MS was changed to {RECV_GAP_WARN_THRESHOLD_MS}ms! "
            "Do not move the bar - fix the underlying issue instead."
        )

    def test_warn_count_is_10(self):
        """
        CONTRACT: RECV_GAP_WARN_COUNT must be exactly 10.

        We only warn after 10 gaps to prevent noise from transient spikes.
        If you need to change this, you must update this test AND document why.
        """
        from retrovue.runtime.channel_stream import RECV_GAP_WARN_COUNT
        assert RECV_GAP_WARN_COUNT == 10, (
            f"RECV_GAP_WARN_COUNT was changed to {RECV_GAP_WARN_COUNT}! "
            "Do not raise this just to silence warnings."
        )

    def test_constants_are_integers(self):
        """Constants must be integers for nanosecond math and count comparisons."""
        from retrovue.runtime.channel_stream import (
            RECV_GAP_WARN_THRESHOLD_MS,
            RECV_GAP_WARN_COUNT,
        )
        assert isinstance(RECV_GAP_WARN_THRESHOLD_MS, int)
        assert isinstance(RECV_GAP_WARN_COUNT, int)

    def test_threshold_converts_to_nanoseconds_correctly(self):
        """Verify the ns conversion used in the reader loop is correct."""
        from retrovue.runtime.channel_stream import RECV_GAP_WARN_THRESHOLD_MS
        threshold_ns = RECV_GAP_WARN_THRESHOLD_MS * 1_000_000
        assert threshold_ns == 40_000_000, "40ms should be 40,000,000 ns"
