"""
INV-LIFECYCLE-OBSERVABILITY-001 — ChannelStream fanout metrics compliance.

Proves that ChannelStream disconnect and reconnect events emit structured
log events with required fields per RETA-75:

1. Backpressure disconnect: queue_bytes_at_detach in SLOW_CONSUMER_DISCONNECT
2. Write stall timeout: client_id in WRITE_TIMEOUT log
3. Reconnect: stream_state=existing|fresh in CLIENT_CONNECTED log
4. Client detach: queue_bytes_at_detach in CLIENT_DISCONNECTED log
"""
from __future__ import annotations

import asyncio
import logging
import socket
import threading
import time
from queue import Empty
from typing import Optional

import pytest

from retrovue.runtime.channel_stream import (
    BytesBoundedQueue,
    ChannelStream,
    generate_ts_stream_async,
)
from retrovue.runtime.clock import SystemClock

_TEST_CLOCK = SystemClock()


# ---------------------------------------------------------------------------
# Fixtures: reusable TS sources for controlled testing
# ---------------------------------------------------------------------------

class FloodTsSource:
    """TS source that emits data as fast as possible until closed."""

    def __init__(self, chunk_size: int = 188 * 20, stop_event: threading.Event | None = None):
        self.chunk_size = chunk_size
        self._closed = False
        self._stop_event = stop_event
        self._packet = b"\x47" + b"\x00" * 187

    def read(self, size: int) -> bytes:
        if self._closed or (self._stop_event and self._stop_event.is_set()):
            return b""
        packets = self.chunk_size // 188
        return (self._packet * packets)[: self.chunk_size]

    def close(self) -> None:
        self._closed = True

    def get_socket(self) -> Optional[socket.socket]:
        return None


class PacedTsSource:
    """TS source that emits data at a controlled rate."""

    def __init__(self, chunk_size: int = 188 * 10, stop_event: threading.Event | None = None):
        self.chunk_size = chunk_size
        self._closed = False
        self._stop_event = stop_event
        self._packet = b"\x47" + b"\x00" * 187

    def read(self, size: int) -> bytes:
        if self._closed or (self._stop_event and self._stop_event.is_set()):
            return b""
        time.sleep(0.01)  # pace reads
        packets = self.chunk_size // 188
        return (self._packet * packets)[: self.chunk_size]

    def close(self) -> None:
        self._closed = True

    def get_socket(self) -> Optional[socket.socket]:
        return None


# ---------------------------------------------------------------------------
# Test 1: SLOW_CONSUMER_DISCONNECT includes queue_bytes_at_detach
# ---------------------------------------------------------------------------

class TestBackpressureDisconnectQueueBytes:
    """INV-LIFECYCLE-OBSERVABILITY-001: backpressure disconnect MUST include
    queue_bytes_at_detach for post-mortem analysis."""

    def test_disconnect_log_includes_queue_bytes_at_detach(self, caplog):
        small_buffer = 188 * 5

        stream = ChannelStream(
            channel_id="test-bp-bytes",
            ts_source_factory=lambda stop_event: FloodTsSource(
                chunk_size=188 * 10, stop_event=stop_event
            ),
            client_buffer_max_bytes=small_buffer,
            backpressure_policy="disconnect",
            clock=_TEST_CLOCK,
        )

        try:
            with caplog.at_level(logging.INFO):
                q = stream.subscribe("bp-client")

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
                "SLOW_CONSUMER_DISCONNECT must be emitted on backpressure disconnect"
            )
            msg = disconnect_logs[0].getMessage()
            assert "queue_bytes_at_detach=" in msg, (
                "SLOW_CONSUMER_DISCONNECT must include queue_bytes_at_detach= "
                "structured field for post-mortem analysis"
            )
        finally:
            stream.stop()


# ---------------------------------------------------------------------------
# Test 2: WRITE_TIMEOUT includes client_id
# ---------------------------------------------------------------------------

class TestWriteTimeoutIncludesClientId:
    """INV-LIFECYCLE-OBSERVABILITY-001: write timeout log MUST include
    client_id for end-to-end traceability."""

    @pytest.mark.asyncio
    async def test_write_timeout_log_includes_client_id(self, caplog):
        q = BytesBoundedQueue(max_bytes=1024 * 1024)

        for _ in range(5):
            q.put_nowait(b"\x47" * 188)

        chunks_yielded = 0
        with caplog.at_level(logging.WARNING):
            from retrovue.runtime.clock import SystemClock
            gen = generate_ts_stream_async(
                q, clock=SystemClock(), write_timeout_s=0.0, client_id="timeout-client"
            )
            async for chunk in gen:
                chunks_yielded += 1
                if chunks_yielded > 5:
                    break  # safety

        timeout_logs = [
            r for r in caplog.records
            if "WRITE_TIMEOUT" in r.getMessage()
        ]
        assert len(timeout_logs) >= 1, (
            "WRITE_TIMEOUT must be emitted when yield exceeds threshold"
        )
        msg = timeout_logs[0].getMessage()
        assert "client_id=timeout-client" in msg, (
            "WRITE_TIMEOUT must include client_id= for end-to-end traceability"
        )


# ---------------------------------------------------------------------------
# Test 3: CLIENT_CONNECTED includes stream_state (existing vs fresh)
# ---------------------------------------------------------------------------

class TestClientConnectedStreamState:
    """INV-LIFECYCLE-OBSERVABILITY-001: CLIENT_CONNECTED MUST indicate whether
    the client attached to an existing running stream or triggered a fresh start."""

    def test_first_subscriber_logs_stream_state_fresh(self, caplog):
        """First subscriber on a stopped stream → stream_state=fresh."""
        stream = ChannelStream(
            channel_id="test-fresh",
            ts_source_factory=lambda stop_event: PacedTsSource(stop_event=stop_event),
            client_buffer_max_bytes=1024 * 1024,
            backpressure_policy="disconnect",
            clock=_TEST_CLOCK,
        )

        try:
            with caplog.at_level(logging.INFO):
                q = stream.subscribe("first-client")

            connect_logs = [
                r for r in caplog.records
                if "CLIENT_CONNECTED" in r.getMessage()
                and "first-client" in r.getMessage()
            ]
            assert len(connect_logs) >= 1
            msg = connect_logs[0].getMessage()
            assert "stream_state=fresh" in msg, (
                "CLIENT_CONNECTED for first subscriber must include stream_state=fresh"
            )
        finally:
            stream.stop()

    def test_second_subscriber_logs_stream_state_existing(self, caplog):
        """Second subscriber on an already-running stream → stream_state=existing."""
        stream = ChannelStream(
            channel_id="test-existing",
            ts_source_factory=lambda stop_event: PacedTsSource(stop_event=stop_event),
            client_buffer_max_bytes=1024 * 1024,
            backpressure_policy="disconnect",
            clock=_TEST_CLOCK,
        )

        try:
            q1 = stream.subscribe("existing-client-1")
            time.sleep(0.1)  # let stream start

            with caplog.at_level(logging.INFO):
                q2 = stream.subscribe("existing-client-2")

            connect_logs = [
                r for r in caplog.records
                if "CLIENT_CONNECTED" in r.getMessage()
                and "existing-client-2" in r.getMessage()
            ]
            assert len(connect_logs) >= 1
            msg = connect_logs[0].getMessage()
            assert "stream_state=existing" in msg, (
                "CLIENT_CONNECTED for subsequent subscriber must include stream_state=existing"
            )
        finally:
            stream.stop()


# ---------------------------------------------------------------------------
# Test 4: CLIENT_DISCONNECTED includes queue_bytes_at_detach
# ---------------------------------------------------------------------------

class TestClientDisconnectedQueueBytes:
    """INV-LIFECYCLE-OBSERVABILITY-001: CLIENT_DISCONNECTED MUST include
    queue_bytes_at_detach so operators can see buffered data at disconnect."""

    def test_unsubscribe_logs_queue_bytes_at_detach(self, caplog):
        stream = ChannelStream(
            channel_id="test-detach-bytes",
            ts_source_factory=lambda stop_event: PacedTsSource(stop_event=stop_event),
            client_buffer_max_bytes=1024 * 1024,
            backpressure_policy="disconnect",
            clock=_TEST_CLOCK,
        )

        try:
            q = stream.subscribe("detach-client")
            time.sleep(0.3)  # let some data accumulate

            with caplog.at_level(logging.INFO):
                stream.unsubscribe("detach-client", reason="test_disconnect")

            disconnect_logs = [
                r for r in caplog.records
                if "CLIENT_DISCONNECTED" in r.getMessage()
                and "detach-client" in r.getMessage()
            ]
            assert len(disconnect_logs) >= 1
            msg = disconnect_logs[0].getMessage()
            assert "queue_bytes_at_detach=" in msg, (
                "CLIENT_DISCONNECTED must include queue_bytes_at_detach= "
                "structured field"
            )
        finally:
            stream.stop()
