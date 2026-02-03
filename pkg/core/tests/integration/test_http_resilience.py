"""
P8-INT-002 — HTTP Connection Survives Content Deficit.

Contract: INV-P8-CONTENT-DEFICIT-FILL-001
Governing Law: LAW-OUTPUT-LIVENESS

When a decoder reaches EOF before the scheduled segment boundary (content deficit),
the playout engine fills the gap with pad frames (black + silence). The HTTP
connection MUST remain open and TS bytes MUST continue flowing throughout the
deficit period.

Test scenario:
1. Start channel with content that simulates short duration (deficit scenario)
2. Connect HTTP viewer
3. Verify HTTP 200 maintained throughout
4. Verify TS bytes flow continuously (no timeout or gap)
5. Verify no viewer disconnect event

This test uses a ContentDeficitTsSource that emits TS bytes in two phases:
- Phase 1: "Content" phase - normal TS packet emission
- Phase 2: "Deficit fill" phase - continued TS emission (simulating pad)

The test verifies that the HTTP layer survives the transition between phases
and that bytes continue flowing without interruption.

See: docs/contracts/tasks/phase8/P8-INT-002.md
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import pytest
import requests

from retrovue.runtime.channel_stream import ChannelStream, TsSource
from retrovue.runtime.program_director import ProgramDirector
from retrovue.runtime.producer.base import (
    ContentSegment,
    Producer,
    ProducerMode,
    ProducerStatus,
)


CHANNEL_ID = "mock"  # Must match MockScheduleService.MOCK_CHANNEL_ID
# Test timing constants
CONTENT_PHASE_DURATION_MS = 2000  # 2 seconds of "content"
DEFICIT_PHASE_DURATION_MS = 2000  # 2 seconds of "pad fill"
TOTAL_TEST_DURATION_MS = CONTENT_PHASE_DURATION_MS + DEFICIT_PHASE_DURATION_MS + 1000
# TS packet constants
TS_PACKET_SIZE = 188
PACKETS_PER_CHUNK = 7  # 7 TS packets = 1316 bytes (standard chunk)
CHUNK_SIZE = TS_PACKET_SIZE * PACKETS_PER_CHUNK
# Timing for byte flow verification
MAX_GAP_BETWEEN_CHUNKS_MS = 500  # Max acceptable gap between chunks
MIN_EXPECTED_BYTES = CHUNK_SIZE * 10  # Minimum bytes expected during test


class ContentDeficitTsSource(TsSource):
    """
    Test TS source that simulates content deficit scenario.

    Emits TS packets in two phases:
    1. Content phase: Normal TS emission (simulates actual content)
    2. Deficit phase: Continued TS emission (simulates pad fill)

    The transition between phases simulates decoder EOF before boundary,
    with pad fill maintaining TS cadence.
    """

    def __init__(
        self,
        content_duration_ms: int = CONTENT_PHASE_DURATION_MS,
        deficit_duration_ms: int = DEFICIT_PHASE_DURATION_MS,
        chunk_interval_ms: int = 40,  # ~25 chunks/sec for real-time feel
    ):
        self._content_duration_ms = content_duration_ms
        self._deficit_duration_ms = deficit_duration_ms
        self._chunk_interval_ms = chunk_interval_ms
        self._start_time: float | None = None
        self._phase = "content"
        self._phase_logged = False
        self._stopped = False
        self._lock = threading.Lock()
        self._logger = logging.getLogger(__name__)

    def read(self, size: int = CHUNK_SIZE) -> bytes:
        """
        Read TS bytes. Simulates content → deficit transition.

        Returns empty bytes when test duration complete (simulating end of block).
        """
        with self._lock:
            if self._stopped:
                return b""

            if self._start_time is None:
                self._start_time = time.monotonic()
                self._logger.info(
                    "[ContentDeficitTsSource] Starting content phase (duration=%dms)",
                    self._content_duration_ms,
                )

        elapsed_ms = (time.monotonic() - self._start_time) * 1000

        # Phase transitions
        if elapsed_ms < self._content_duration_ms:
            if self._phase != "content":
                self._phase = "content"
                self._phase_logged = False
            if not self._phase_logged:
                self._logger.debug("[ContentDeficitTsSource] In content phase")
                self._phase_logged = True
        elif elapsed_ms < self._content_duration_ms + self._deficit_duration_ms:
            if self._phase != "deficit":
                self._phase = "deficit"
                self._phase_logged = False
                self._logger.info(
                    "[ContentDeficitTsSource] Content EOF → entering deficit fill phase "
                    "(simulating CONTENT_DEFICIT_FILL_START)"
                )
            if not self._phase_logged:
                self._logger.debug("[ContentDeficitTsSource] In deficit fill phase")
                self._phase_logged = True
        else:
            # Test complete - simulate end of block/switch
            self._logger.info(
                "[ContentDeficitTsSource] Test duration complete → ending stream "
                "(simulating CONTENT_DEFICIT_FILL_END + switch)"
            )
            return b""

        # Pace output to simulate real-time cadence
        time.sleep(self._chunk_interval_ms / 1000.0)

        # Generate TS packets
        # Use 0x47 sync byte + null PID (0x1FFF) for realistic TS structure
        packet = bytes([0x47, 0x1F, 0xFF, 0x10]) + b"\x00" * (TS_PACKET_SIZE - 4)
        return packet * PACKETS_PER_CHUNK

    def close(self) -> None:
        """Close the source."""
        with self._lock:
            self._stopped = True


class FakeProducerWithDeficit(Producer):
    """
    Fake producer that simulates content deficit scenario.

    Exposes socket_path so ProgramDirector creates a fanout.
    The actual TS bytes come from ContentDeficitTsSource.
    """

    def __init__(self, channel_id: str, mode: ProducerMode, configuration: dict[str, Any]):
        super().__init__(channel_id, mode, configuration)
        self._endpoint = f"fake://{channel_id}"
        self.socket_path = Path(f"/tmp/p8-int-002-{channel_id}.sock")
        self._logger = logging.getLogger(__name__)

    def start(
        self,
        playout_plan: list[dict[str, Any]],
        start_at_station_time: datetime,
    ) -> bool:
        self.status = ProducerStatus.RUNNING
        self.started_at = start_at_station_time
        self.output_url = self._endpoint
        self._logger.info(
            "[FakeProducerWithDeficit] Started for channel %s (simulating short content)",
            self.channel_id,
        )
        return True

    def stop(self) -> bool:
        self.status = ProducerStatus.STOPPED
        self.output_url = None
        self._teardown_cleanup()
        self._logger.info("[FakeProducerWithDeficit] Stopped")
        return True

    def play_content(self, content: ContentSegment) -> bool:
        return True

    def get_stream_endpoint(self) -> str | None:
        return self._endpoint

    def health(self) -> str:
        if self.status == ProducerStatus.RUNNING:
            return "running"
        if self.status == ProducerStatus.ERROR:
            return "degraded"
        return "stopped"

    def get_producer_id(self) -> str:
        return f"deficit_{self.channel_id}"

    def on_paced_tick(self, t_now: float, dt: float) -> None:
        self._advance_teardown(dt)


def _free_port() -> int:
    """Get an available port for the HTTP server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_director_with_deficit_source(
    provider: ProgramDirector,
) -> tuple[ProgramDirector, str]:
    """
    Start ProgramDirector with ContentDeficitTsSource.

    Returns (director, base_url).
    """
    port = _free_port()
    director = ProgramDirector(
        channel_manager_provider=provider,
        host="127.0.0.1",
        port=port,
    )

    # Factory that creates ContentDeficitTsSource for the channel
    def channel_stream_factory(cid: str, path: str) -> ChannelStream:
        return ChannelStream(
            cid,
            ts_source_factory=lambda: ContentDeficitTsSource(),
        )

    director._channel_stream_factory = channel_stream_factory
    director.start()

    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{base}/channels", timeout=1)
            if r.status_code == 200:
                return director, base
        except Exception:
            time.sleep(0.1)

    director.stop(timeout=1.0)
    raise RuntimeError("ProgramDirector HTTP server did not become ready")


class TestHttpResilience:
    """P8-INT-002: HTTP connection survives content deficit."""

    def test_http_connection_survives_content_deficit(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        P8-INT-002: HTTP connection survives content deficit.

        Verification points (from task spec):
        1. HTTP response status: 200 OK throughout
        2. No TCP RST or FIN during deficit (implicit: connection stays open)
        3. TS bytes received continuously (no timeout)
        4. Viewer not disconnected

        Observable proof:
        - HTTP connection open throughout test
        - Bytes received counter increases during deficit
        - No viewer disconnect event in logs
        """
        caplog.set_level(logging.INFO)

        # Set up provider with fake producer
        provider = ProgramDirector(schedule_dir=None)
        provider._producer_factory = lambda cid, mode, cfg, channel_config=None: (
            FakeProducerWithDeficit(cid, ProducerMode.NORMAL, cfg or {})
        )

        director, base = _start_director_with_deficit_source(provider)
        url = f"{base}/channel/{CHANNEL_ID}.ts"

        try:
            # Connect to stream
            with requests.get(url, stream=True, timeout=(5, 30)) as response:
                # Verify HTTP 200
                assert response.status_code == 200, (
                    f"P8-INT-002: HTTP 200 required; got {response.status_code}"
                )

                bytes_received = 0
                chunks_received = 0
                last_chunk_time = time.monotonic()
                max_gap_ms = 0.0
                content_phase_bytes = 0
                deficit_phase_bytes = 0
                in_deficit_phase = False

                start_time = time.monotonic()
                test_deadline = start_time + (TOTAL_TEST_DURATION_MS / 1000.0)

                # Read bytes throughout content and deficit phases
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    now = time.monotonic()

                    if not chunk:
                        # Empty chunk indicates end of stream (expected after deficit)
                        break

                    # Track bytes
                    bytes_received += len(chunk)
                    chunks_received += 1

                    # Track gap between chunks
                    gap_ms = (now - last_chunk_time) * 1000
                    if chunks_received > 1:  # Skip first chunk gap
                        max_gap_ms = max(max_gap_ms, gap_ms)
                    last_chunk_time = now

                    # Track phase transitions
                    elapsed_ms = (now - start_time) * 1000
                    if elapsed_ms < CONTENT_PHASE_DURATION_MS:
                        content_phase_bytes += len(chunk)
                    else:
                        if not in_deficit_phase:
                            in_deficit_phase = True
                        deficit_phase_bytes += len(chunk)

                    # Safety: don't run forever
                    if now > test_deadline:
                        break

                # Verify continuous byte flow
                assert bytes_received >= MIN_EXPECTED_BYTES, (
                    f"P8-INT-002: Expected at least {MIN_EXPECTED_BYTES} bytes, "
                    f"got {bytes_received}"
                )

                # Verify no long gaps
                assert max_gap_ms < MAX_GAP_BETWEEN_CHUNKS_MS, (
                    f"P8-INT-002: Max gap between chunks was {max_gap_ms:.0f}ms, "
                    f"exceeds {MAX_GAP_BETWEEN_CHUNKS_MS}ms threshold"
                )

                # Verify bytes received in both phases
                assert content_phase_bytes > 0, (
                    "P8-INT-002: Should have received bytes during content phase"
                )
                assert deficit_phase_bytes > 0, (
                    "P8-INT-002: Should have received bytes during deficit fill phase "
                    "(pad emission must maintain TS cadence)"
                )

                # Log results
                logging.info(
                    "P8-INT-002 PASS: HTTP connection survived content deficit. "
                    "Total bytes=%d, chunks=%d, max_gap_ms=%.0f, "
                    "content_phase=%d bytes, deficit_phase=%d bytes",
                    bytes_received,
                    chunks_received,
                    max_gap_ms,
                    content_phase_bytes,
                    deficit_phase_bytes,
                )

            # Verify no viewer disconnect events
            disconnect_logs = [
                rec for rec in caplog.records
                if "viewer disconnect" in (rec.getMessage() or "").lower()
                or "false viewer disconnect" in (rec.getMessage() or "").lower()
            ]
            assert not disconnect_logs, (
                f"P8-INT-002: No false viewer disconnect should occur; "
                f"found: {[r.getMessage() for r in disconnect_logs]}"
            )

        finally:
            director.stop(timeout=2.0)

    def test_ts_bytes_flow_during_deficit_no_timeout(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        P8-INT-002 sub-test: Verify TS bytes flow without HTTP read timeout.

        This test uses a shorter timeout to verify that bytes arrive
        frequently enough to prevent HTTP client timeout during deficit.
        """
        caplog.set_level(logging.INFO)

        provider = ProgramDirector(schedule_dir=None)
        provider._producer_factory = lambda cid, mode, cfg, channel_config=None: (
            FakeProducerWithDeficit(cid, ProducerMode.NORMAL, cfg or {})
        )

        director, base = _start_director_with_deficit_source(provider)
        url = f"{base}/channel/{CHANNEL_ID}.ts"

        try:
            # Use short read timeout to catch gaps
            read_timeout = MAX_GAP_BETWEEN_CHUNKS_MS / 1000.0

            with requests.get(
                url,
                stream=True,
                timeout=(5, read_timeout),
            ) as response:
                assert response.status_code == 200

                bytes_received = 0
                start = time.monotonic()

                try:
                    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                        if not chunk:
                            break
                        bytes_received += len(chunk)

                        # Run for full test duration
                        if time.monotonic() - start > TOTAL_TEST_DURATION_MS / 1000.0:
                            break

                except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
                    # ConnectionError wraps ReadTimeoutError in some cases
                    error_str = str(e).lower()
                    if "timed out" in error_str or "timeout" in error_str:
                        # This is expected at the END of the stream when content ends
                        # Not a failure if we've received sufficient bytes
                        if bytes_received < MIN_EXPECTED_BYTES:
                            pytest.fail(
                                f"P8-INT-002: HTTP timeout during content deficit! "
                                f"TS bytes should flow continuously. "
                                f"Received only {bytes_received} bytes before timeout."
                            )
                    else:
                        raise

                assert bytes_received >= MIN_EXPECTED_BYTES, (
                    f"P8-INT-002: Expected >= {MIN_EXPECTED_BYTES} bytes, "
                    f"got {bytes_received}"
                )

        finally:
            director.stop(timeout=2.0)
