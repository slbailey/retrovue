"""
INV-SLOW-CONSUMER-DISCONNECT-001 — Contract tests.

Proves:
1. disconnect policy: overflowing client gets EOF sentinel + subscriber removal
2. disconnect is logged with structured fields (client_id, channel_id, reason)
3. drop_oldest policy: overflowing client stays connected (regression guard)
4. per-client state is fully cleaned up after disconnect (no leaks)
5. SLOW_CONSUMER_DISCONNECT log emitted with reason=backpressure_disconnect
6. write timeout in async generator closes dead client connection
"""
from __future__ import annotations

import asyncio
import logging
import socket
import threading
import time
from queue import Empty
from typing import Optional
from unittest.mock import ANY

import pytest

from retrovue.runtime.channel_stream import (
    BackpressurePolicy,
    BytesBoundedQueue,
    ChannelStream,
    generate_ts_stream_async,
)


# ---------------------------------------------------------------------------
# Fixtures: A fast TS source that floods data to trigger overflow quickly
# ---------------------------------------------------------------------------

class FloodTsSource:
    """TS source that emits data as fast as possible until closed."""

    def __init__(self, chunk_size: int = 188 * 20, stop_event: threading.Event | None = None):
        self.chunk_size = chunk_size
        self._closed = False
        self._stop_event = stop_event
        self._packet = b"\x47" + b"\x00" * 187  # one TS packet

    def read(self, size: int) -> bytes:
        if self._closed or (self._stop_event and self._stop_event.is_set()):
            return b""
        # Return chunk_size worth of valid TS sync bytes
        packets = self.chunk_size // 188
        return (self._packet * packets)[: self.chunk_size]

    def close(self) -> None:
        self._closed = True

    def get_socket(self) -> Optional[socket.socket]:
        return None


# ---------------------------------------------------------------------------
# Test 1: disconnect policy sends EOF and removes subscriber
# ---------------------------------------------------------------------------

class TestDisconnectPolicyRemovesSlowClient:
    """INV-SLOW-CONSUMER-DISCONNECT-001: overflow + disconnect → EOF + removal."""

    def test_overflow_sends_eof_and_removes_subscriber(self):
        """When a client queue overflows under disconnect policy, the client
        receives an EOF sentinel (b'') and is removed from subscribers."""
        # Small buffer so overflow happens quickly
        small_buffer = 188 * 5  # ~940 bytes — will overflow fast

        stream = ChannelStream(
            channel_id="test-disconnect",
            ts_source_factory=lambda stop_event: FloodTsSource(
                chunk_size=188 * 10, stop_event=stop_event
            ),
            client_buffer_max_bytes=small_buffer,
            backpressure_policy="disconnect",
        )

        try:
            # Subscribe a "slow" client that never reads
            q = stream.subscribe("slow-client")

            # Wait for the fanout loop to detect overflow and disconnect
            deadline = time.monotonic() + 5.0
            eof_received = False
            while time.monotonic() < deadline:
                try:
                    chunk = q.get(timeout=0.1)
                    if chunk == b"":
                        eof_received = True
                        break
                except Exception:
                    continue

            assert eof_received, (
                "Slow client must receive EOF sentinel (b'') when queue overflows "
                "under disconnect policy"
            )

            # Client must be removed from subscribers
            time.sleep(0.1)  # allow fanout to finish removal
            with stream.subscribers_lock:
                assert "slow-client" not in stream.subscribers, (
                    "Disconnected client must be removed from subscribers dict"
                )
        finally:
            stream.stop()


# ---------------------------------------------------------------------------
# Test 2: disconnect is logged with structured fields
# ---------------------------------------------------------------------------

class TestDisconnectStructuredLogging:
    """INV-SLOW-CONSUMER-DISCONNECT-001: disconnect event must log structured fields."""

    def test_backpressure_log_contains_client_id(self, caplog):
        """The BACKPRESSURE log event must include client_id for traceability."""
        small_buffer = 188 * 5

        stream = ChannelStream(
            channel_id="test-log-fields",
            ts_source_factory=lambda stop_event: FloodTsSource(
                chunk_size=188 * 10, stop_event=stop_event
            ),
            client_buffer_max_bytes=small_buffer,
            backpressure_policy="disconnect",
        )

        try:
            with caplog.at_level(logging.WARNING):
                q = stream.subscribe("logged-client")

                # Wait for disconnect
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline:
                    try:
                        chunk = q.get(timeout=0.1)
                        if chunk == b"":
                            break
                    except Exception:
                        continue

            # Check that a BACKPRESSURE log was emitted with client_id
            bp_logs = [
                r for r in caplog.records
                if "BACKPRESSURE" in r.getMessage()
            ]
            assert len(bp_logs) >= 1, (
                "At least one BACKPRESSURE log must be emitted on slow client disconnect"
            )
            # Verify structured fields in the log message
            bp_msg = bp_logs[0].getMessage()
            assert "client_id=" in bp_msg, (
                "BACKPRESSURE log must include client_id= structured field"
            )
            assert "logged-client" in bp_msg, (
                "BACKPRESSURE log must contain the actual client_id value"
            )
        finally:
            stream.stop()


# ---------------------------------------------------------------------------
# Test 3: drop_oldest policy keeps client connected (regression guard)
# ---------------------------------------------------------------------------

class TestDropOldestKeepsClientConnected:
    """Regression guard: drop_oldest must NOT disconnect slow clients."""

    def test_overflow_with_drop_oldest_keeps_subscriber(self):
        """Under drop_oldest policy, a slow client remains subscribed even when
        its queue overflows — it receives degraded data but is not disconnected."""
        small_buffer = 188 * 5

        stream = ChannelStream(
            channel_id="test-drop-oldest",
            ts_source_factory=lambda stop_event: FloodTsSource(
                chunk_size=188 * 10, stop_event=stop_event
            ),
            client_buffer_max_bytes=small_buffer,
            backpressure_policy="drop_oldest",
        )

        try:
            q = stream.subscribe("slow-drop-client")

            # Let data flow for a while — enough for overflow to occur
            time.sleep(1.0)

            # Client must still be subscribed
            with stream.subscribers_lock:
                assert "slow-drop-client" in stream.subscribers, (
                    "Under drop_oldest policy, slow client must remain subscribed"
                )

            # Client must still be able to read (not EOF)
            got_data = False
            try:
                chunk = q.get(timeout=1.0)
                if chunk and chunk != b"":
                    got_data = True
            except Exception:
                pass

            assert got_data, (
                "Under drop_oldest policy, slow client must still receive data "
                "(possibly with gaps from dropped chunks)"
            )
        finally:
            stream.stop()


# ---------------------------------------------------------------------------
# Test 4: per-client state cleanup after disconnect (no leaks)
# ---------------------------------------------------------------------------

class TestClientStateCleanupOnDisconnect:
    """After disconnect, all per-client state must be cleaned up."""

    def test_backpressure_log_state_cleaned_on_disconnect(self):
        """When a client is disconnected, its backpressure throttle state
        must not leak in _backpressure_log_last."""
        small_buffer = 188 * 5

        stream = ChannelStream(
            channel_id="test-cleanup",
            ts_source_factory=lambda stop_event: FloodTsSource(
                chunk_size=188 * 10, stop_event=stop_event
            ),
            client_buffer_max_bytes=small_buffer,
            backpressure_policy="disconnect",
        )

        try:
            q = stream.subscribe("cleanup-client")

            # Wait for disconnect
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                try:
                    chunk = q.get(timeout=0.1)
                    if chunk == b"":
                        break
                except Exception:
                    continue

            time.sleep(0.1)

            # Subscriber entry must be removed
            with stream.subscribers_lock:
                assert "cleanup-client" not in stream.subscribers

            # Backpressure log throttle state should be cleaned up
            with stream._backpressure_log_lock:
                assert "cleanup-client" not in stream._backpressure_log_last, (
                    "Per-client backpressure log throttle state must be cleaned up "
                    "after disconnect to prevent memory leaks"
                )
        finally:
            stream.stop()


# ---------------------------------------------------------------------------
# Test 5: SLOW_CONSUMER_DISCONNECT structured log with reason field
# ---------------------------------------------------------------------------

class TestDisconnectReasonLog:
    """INV-SLOW-CONSUMER-DISCONNECT-001: disconnect event MUST log
    client_id, channel_id, and reason=backpressure_disconnect."""

    def test_disconnect_log_contains_reason_field(self, caplog):
        """The SLOW_CONSUMER_DISCONNECT log must include reason=backpressure_disconnect."""
        small_buffer = 188 * 5

        stream = ChannelStream(
            channel_id="test-reason-log",
            ts_source_factory=lambda stop_event: FloodTsSource(
                chunk_size=188 * 10, stop_event=stop_event
            ),
            client_buffer_max_bytes=small_buffer,
            backpressure_policy="disconnect",
        )

        try:
            with caplog.at_level(logging.INFO):
                q = stream.subscribe("reason-client")

                # Wait for disconnect
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline:
                    try:
                        chunk = q.get(timeout=0.1)
                        if chunk == b"":
                            break
                    except Exception:
                        continue

            disconnect_logs = [
                r for r in caplog.records
                if "SLOW_CONSUMER_DISCONNECT" in r.getMessage()
            ]
            assert len(disconnect_logs) >= 1, (
                "SLOW_CONSUMER_DISCONNECT log must be emitted on backpressure disconnect"
            )
            msg = disconnect_logs[0].getMessage()
            assert "reason=backpressure_disconnect" in msg, (
                "Disconnect log must include reason=backpressure_disconnect"
            )
            assert "client_id=reason-client" in msg, (
                "Disconnect log must include client_id"
            )
            assert "channel_id=test-reason-log" in msg, (
                "Disconnect log must include channel_id"
            )
        finally:
            stream.stop()


# ---------------------------------------------------------------------------
# Test 6: write timeout in async generator closes connection
# ---------------------------------------------------------------------------

class TestWriteTimeoutClosesConnection:
    """INV-SLOW-CONSUMER-DISCONNECT-001: async generator must break on write timeout."""

    @pytest.mark.asyncio
    async def test_yield_stall_exceeding_timeout_breaks_generator(self):
        """If a yield (TCP write) takes longer than write_timeout_s,
        the async generator must exit to sever the connection."""
        q = BytesBoundedQueue(max_bytes=1024 * 1024)

        # Feed a few chunks so the generator has data to yield
        for _ in range(3):
            q.put_nowait(b"\x47" * 188)

        chunks_yielded = 0
        gen = generate_ts_stream_async(q, write_timeout_s=0.0)
        # write_timeout_s=0.0 means any non-zero yield time triggers break.
        # The first yield will take some non-zero wall time, so the generator
        # should break after yielding at most one batch.
        async for chunk in gen:
            chunks_yielded += 1
            if chunks_yielded > 5:
                break  # safety — should not reach here

        # Generator exited after yielding data (write timeout triggered)
        assert chunks_yielded >= 1, "Generator must yield at least one batch before timeout"
        assert chunks_yielded <= 2, (
            "Generator must stop after detecting write timeout, not continue indefinitely"
        )
