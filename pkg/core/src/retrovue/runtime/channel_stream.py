"""
Channel TS Stream Consumer.

Per-channel Unix Domain Socket (UDS) reader that consumes TS streams from the internal playout engine
and fans out to multiple HTTP clients.

Responsibilities:
- Connect to playout engine UDS socket per channel
- Read TS data in a loop
- Fan-out TS chunks to all active HTTP clients
- Handle playout engine disconnect/reconnect transparently
- Support test mode with injectable fake TS source
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Any, Callable, Protocol

_logger = logging.getLogger(__name__)

# =============================================================================
# AUDIT: INV-UDS-DRAIN timing instrumentation
# =============================================================================
_AUDIT_T0: int | None = None  # Thread started (monotonic_ns)
_AUDIT_T1: int | None = None  # Before first recv (monotonic_ns)
_AUDIT_T2: int | None = None  # After first recv returns data (monotonic_ns)
_AUDIT_FIRST_RECV_DONE = False
_AUDIT_LOCK = threading.Lock()


class TsSource(Protocol):
    """Protocol for TS data source (UDS or fake for tests)."""

    def read(self, size: int) -> bytes:
        """Read TS data (blocks until data available)."""
        ...

    def close(self) -> None:
        """Close the source."""
        ...


class UdsTsSource:
    """TS source that reads from Unix Domain Socket."""

    def __init__(self, socket_path: str | Path):
        self.socket_path = Path(socket_path)
        self.sock: socket.socket | None = None
        self._connected = False

    def connect(self, timeout: float = 5.0) -> bool:
        """Connect to UDS socket with timeout."""
        try:
            if not self.socket_path.exists():
                _logger.warning(
                    "UDS socket does not exist yet: %s (will retry)", self.socket_path
                )
                return False

            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(timeout)
            self.sock.connect(str(self.socket_path))
            self.sock.settimeout(None)  # Blocking mode for reads
            self._connected = True

            # AUDIT: Log actual kernel buffer sizes
            try:
                rcvbuf = self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
                sndbuf = self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF)
                _logger.info("[AUDIT-BUF] UdsTsSource socket: SO_RCVBUF=%d bytes, SO_SNDBUF=%d bytes",
                            rcvbuf, sndbuf)
                if rcvbuf < 131072:  # < 128KB
                    _logger.warning("[AUDIT-BUF] SO_RCVBUF < 128KB - risk of overrun during startup!")
            except Exception as e:
                _logger.warning("[AUDIT-BUF] Could not read socket buffer sizes: %s", e)

            _logger.info("Connected to UDS socket: %s", self.socket_path)
            return True
        except (OSError, socket.error) as e:
            _logger.warning("Failed to connect to UDS socket %s: %s", self.socket_path, e)
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None
            self._connected = False
            return False

    def read(self, size: int) -> bytes:
        """Read TS data from socket."""
        if not self.sock or not self._connected:
            raise IOError("Not connected to UDS socket")
        try:
            data = self.sock.recv(size)
            if not data:  # EOF
                _logger.warning(
                    "UDS socket closed by playout engine (EOF) for %s",
                    self.socket_path,
                )
                self._connected = False
                return b""
            return data
        except (OSError, socket.error) as e:
            _logger.error("UDS socket read error: %s", e)
            self._connected = False
            raise IOError(f"UDS read error: {e}") from e

    def close(self) -> None:
        """Close the UDS socket."""
        self._connected = False
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass  # Already closed or not connected
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
        _logger.info("Closed UDS socket: %s", self.socket_path)

    @property
    def is_connected(self) -> bool:
        """Check if connected to UDS."""
        return self._connected and self.sock is not None


class SocketTsSource:
    """TS source that reads from an already-connected socket (e.g. Air connected to our server)."""

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self._connected = True

        # AUDIT: Log actual kernel buffer sizes
        try:
            rcvbuf = sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
            sndbuf = sock.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF)
            _logger.info("[AUDIT-BUF] SocketTsSource socket: SO_RCVBUF=%d bytes, SO_SNDBUF=%d bytes",
                        rcvbuf, sndbuf)
            if rcvbuf < 131072:  # < 128KB
                _logger.warning("[AUDIT-BUF] SO_RCVBUF < 128KB - risk of overrun during startup!")
        except Exception as e:
            _logger.warning("[AUDIT-BUF] Could not read socket buffer sizes: %s", e)

    def read(self, size: int) -> bytes:
        if not self.sock or not self._connected:
            raise IOError("Socket not connected")
        try:
            data = self.sock.recv(size)
            if not data:
                self._connected = False
                return b""
            return data
        except (OSError, socket.error) as e:
            self._connected = False
            raise IOError(f"Socket read error: {e}") from e

    def close(self) -> None:
        self._connected = False
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass  # Already closed or not connected
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    @property
    def is_connected(self) -> bool:
        return self._connected and self.sock is not None


class FakeTsSource:
    """Fake TS source for tests (generates dummy TS data)."""

    def __init__(self, chunk_size: int = 188 * 10):
        self.chunk_size = chunk_size
        self._closed = False

    def read(self, size: int) -> bytes:
        """Generate fake TS data."""
        if self._closed:
            return b""
        # Generate minimal valid TS packet header + payload
        # TS packet = 188 bytes: sync byte (0x47) + header + payload
        chunk = b"\x47" + b"\x00" * min(size - 1, 187)
        if size > 188:
            # Multiple TS packets
            packets_needed = (size + 187) // 188
            chunk = chunk * packets_needed
            chunk = chunk[:size]
        return chunk

    def close(self) -> None:
        """Mark source as closed."""
        self._closed = True


class ChannelStream:
    """
    Per-channel TS stream consumer with fan-out to HTTP clients.

    Exactly one UDS reader per channel. Multiple HTTP clients subscribe
    to receive TS chunks via queues.
    """

    def __init__(
        self,
        channel_id: str,
        socket_path: str | Path | None = None,
        ts_source_factory: Callable[[], TsSource] | None = None,
    ):
        """
        Initialize ChannelStream for a channel.

        Args:
            channel_id: Channel identifier
            socket_path: UDS socket path (if None, uses ts_source_factory)
            ts_source_factory: Factory for creating TS source (for tests)
        """
        self.channel_id = channel_id
        self.socket_path = Path(socket_path) if socket_path else None
        self.ts_source_factory = ts_source_factory

        # Active subscribers (client_id -> queue)
        self.subscribers: dict[str, Queue[bytes]] = {}
        self.subscribers_lock = threading.Lock()

        # Reader thread
        self.reader_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._stopped = False

        # TS source
        self.ts_source: TsSource | None = None

        # Reconnect backoff
        self._reconnect_delays = [1.0, 2.0, 5.0, 10.0]
        self._current_reconnect_delay_index = 0

        # Debug: log first 16 bytes once per connection to verify TS sync 0x47
        self._first_chunk_logged = False

        self._logger = logging.getLogger(f"{__name__}.{channel_id}")

    def get_socket_path(self) -> Path:
        """Get the UDS socket path for this channel."""
        if self.socket_path:
            return self.socket_path
        # Use same logic as channel_manager_launch.get_uds_socket_path
        import os
        from pathlib import Path
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
        if runtime_dir:
            socket_dir = Path(runtime_dir) / "retrovue" / "air"
        else:
            socket_dir = Path("/tmp/retrovue/air")
        return socket_dir / f"channel_{self.channel_id}.sock"

    def _create_ts_source(self) -> TsSource:
        """Create TS source (UDS or fake for tests)."""
        if self.ts_source_factory:
            return self.ts_source_factory()
        socket_path = self.get_socket_path()
        return UdsTsSource(socket_path)

    def _connect_with_backoff(self) -> bool:
        """Connect to TS source with exponential backoff."""
        max_attempts = len(self._reconnect_delays)
        for attempt in range(max_attempts):
            if self._stop_event.is_set():
                return False

            if self.ts_source:
                try:
                    self.ts_source.close()
                except Exception:
                    pass

            self.ts_source = self._create_ts_source()

            if isinstance(self.ts_source, UdsTsSource):
                if self.ts_source.connect(timeout=2.0):
                    self._current_reconnect_delay_index = 0
                    return True
            else:
                # SocketTsSource (Air) or FakeTsSource: already connected / no connect
                self._logger.info(
                    "TS source ready for channel %s (socket from queue)",
                    self.channel_id,
                )
                self._current_reconnect_delay_index = 0
                return True

            if attempt < max_attempts - 1:
                delay = self._reconnect_delays[self._current_reconnect_delay_index]
                self._logger.info(
                    "Retrying UDS connect in %.1fs (attempt %d/%d) for channel %s",
                    delay,
                    attempt + 1,
                    max_attempts,
                    self.channel_id,
                )
                if self._stop_event.wait(timeout=delay):
                    return False
                self._current_reconnect_delay_index = min(
                    self._current_reconnect_delay_index + 1, len(self._reconnect_delays) - 1
                )

        return False

    def _reader_loop(self) -> None:
        """Background thread loop that reads TS data and fans out to subscribers."""
        global _AUDIT_T0, _AUDIT_T1, _AUDIT_T2, _AUDIT_FIRST_RECV_DONE

        self._logger.info("ChannelStream reader loop started for channel %s", self.channel_id)
        chunk_size = 188 * 10  # Read 10 TS packets at a time (188 bytes each)

        # AUDIT: Track inter-recv gaps for steady-state analysis
        _last_recv_return_ns: int | None = None
        _max_inter_recv_gap_ns: int = 0
        _local_first_recv_done = False

        while not self._stop_event.is_set():
            # Connect if needed (initial connection only - no reconnect after streaming starts)
            if not self.ts_source:
                if not self._connect_with_backoff():
                    # Phase 8.7: if initial connection fails, don't keep retrying forever
                    self._logger.info(
                        "Initial UDS connection failed for channel %s, stopping",
                        self.channel_id,
                    )
                    break

            # Check if source is connected (for UDS)
            # Phase 8.7: no reconnect loops - if disconnected after initial connect, stop
            if isinstance(self.ts_source, UdsTsSource) and not self.ts_source.is_connected:
                self._logger.warning(
                    "UDS source disconnected for channel %s, stopping (no reconnect per Phase 8.7)",
                    self.channel_id,
                )
                break

            # AUDIT: T1 - Record timestamp immediately before first recv
            if not _local_first_recv_done:
                with _AUDIT_LOCK:
                    if not _AUDIT_FIRST_RECV_DONE:
                        _AUDIT_T1 = time.monotonic_ns()
                        t0_val = _AUDIT_T0 or 0
                        self._logger.info(
                            "[AUDIT-T1] First recv() ENTERING at %d ns (T0→T1 = %.2f ms) for channel %s",
                            _AUDIT_T1, (_AUDIT_T1 - t0_val) / 1e6, self.channel_id
                        )

            # Read TS chunk
            try:
                _recv_enter_ns = time.monotonic_ns()
                chunk = self.ts_source.read(chunk_size)
                _recv_exit_ns = time.monotonic_ns()

                if not chunk:
                    # EOF or disconnect: playout engine closed the write side.
                    # Phase 8.7: no reconnect loops - stop reader.
                    self._logger.warning(
                        "TS source EOF for channel %s, stopping reader (no reconnect per Phase 8.7)",
                        self.channel_id,
                    )
                    break

                # AUDIT: T2 - Record timestamp when first recv returns data
                if not _local_first_recv_done:
                    with _AUDIT_LOCK:
                        if not _AUDIT_FIRST_RECV_DONE:
                            _AUDIT_T2 = _recv_exit_ns
                            _AUDIT_FIRST_RECV_DONE = True
                            t0_val = _AUDIT_T0 or 0
                            t1_val = _AUDIT_T1 or 0
                            self._logger.info(
                                "[AUDIT-T2] First recv() RETURNED DATA at %d ns "
                                "(T1→T2 = %.2f ms, T0→T2 = %.2f ms, %d bytes) for channel %s",
                                _AUDIT_T2,
                                (_AUDIT_T2 - t1_val) / 1e6,
                                (_AUDIT_T2 - t0_val) / 1e6,
                                len(chunk),
                                self.channel_id
                            )
                    _local_first_recv_done = True

                # AUDIT: Track inter-recv gaps (steady-state cadence proof)
                if _last_recv_return_ns is not None:
                    gap_ns = _recv_exit_ns - _last_recv_return_ns
                    if gap_ns > _max_inter_recv_gap_ns:
                        _max_inter_recv_gap_ns = gap_ns
                    if gap_ns > 40_000_000:  # > 40ms threshold
                        self._logger.warning(
                            "[AUDIT-GAP] Inter-recv gap %.2f ms EXCEEDS 40ms threshold for channel %s",
                            gap_ns / 1e6, self.channel_id
                        )
                _last_recv_return_ns = _recv_exit_ns

                # FIRST-ON-AIR: Verify first byte is 0x47 (MPEG-TS sync byte)
                if not self._first_chunk_logged and len(chunk) >= 16:
                    first_byte = chunk[0]
                    is_valid_ts = first_byte == 0x47
                    if is_valid_ts:
                        self._logger.info(
                            "FIRST-ON-AIR: Channel %s: First TS chunk verified "
                            "(0x47 sync byte present, %d bytes): %s",
                            self.channel_id,
                            len(chunk),
                            chunk[:16].hex(),
                        )
                    else:
                        self._logger.error(
                            "FIRST-ON-AIR: Channel %s: Invalid TS stream! "
                            "Expected 0x47 sync byte, got 0x%02x (%d bytes): %s",
                            self.channel_id,
                            first_byte,
                            len(chunk),
                            chunk[:16].hex(),
                        )
                    self._first_chunk_logged = True
            except IOError as e:
                # Phase 8.7: no reconnect loops - read error means stop
                self._logger.warning(
                    "TS read error for channel %s: %s, stopping (no reconnect per Phase 8.7)",
                    self.channel_id,
                    e,
                )
                break

            # Fan-out to all subscribers
            with self.subscribers_lock:
                for client_id, client_queue in self.subscribers.items():
                    try:
                        # Non-blocking put; if queue is full, drop this chunk for
                        # that client (backpressure: slow client misses data but
                        # stays subscribed — contract says no per-client buffering
                        # required and slow clients must not stall others).
                        client_queue.put_nowait(chunk)
                    except Full:
                        pass  # Expected: slow client, drop chunk
                    except Exception:
                        self._logger.warning(
                            "Unexpected fanout error for client %s", client_id, exc_info=True
                        )

        # AUDIT: Log max inter-recv gap observed during this session
        if _max_inter_recv_gap_ns > 0:
            self._logger.info(
                "[AUDIT-EXIT] Max inter-recv gap was %.2f ms for channel %s",
                _max_inter_recv_gap_ns / 1e6, self.channel_id
            )

        # Cleanup
        if self.ts_source:
            try:
                self.ts_source.close()
            except Exception:
                pass
            self.ts_source = None

        self._stopped = True
        self._logger.info("ChannelStream reader loop stopped for channel %s", self.channel_id)

    def start(self) -> None:
        """Start the UDS reader thread."""
        global _AUDIT_T0, _AUDIT_T1, _AUDIT_T2, _AUDIT_FIRST_RECV_DONE

        if self.reader_thread is not None and self.reader_thread.is_alive():
            return  # Already running

        self._stop_event.clear()
        self._stopped = False

        # AUDIT: Reset state for new session and record T0
        with _AUDIT_LOCK:
            _AUDIT_T0 = time.monotonic_ns()
            _AUDIT_T1 = None
            _AUDIT_T2 = None
            _AUDIT_FIRST_RECV_DONE = False
        self._logger.info("[AUDIT-T0] Reader thread spawning at %d ns for channel %s",
                         _AUDIT_T0, self.channel_id)

        self.reader_thread = threading.Thread(
            target=self._reader_loop, name=f"ChannelStream-{self.channel_id}", daemon=True
        )
        self.reader_thread.start()
        self._logger.info("ChannelStream started for channel %s", self.channel_id)

    def stop(self) -> None:
        """Stop the UDS reader thread and clean up (Phase 8.5/8.7: no ongoing work when no viewers). No wait for external I/O."""
        if self._stopped:
            return

        self._logger.info("[teardown] stopping reader loop for channel %s", self.channel_id)
        self._stop_event.set()

        # Close source first so reader thread unblocks from read() and can exit
        if self.ts_source:
            try:
                self.ts_source.close()
            except Exception:
                pass
            self.ts_source = None

        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=5.0)
            if self.reader_thread.is_alive():
                self._logger.warning("ChannelStream reader thread did not stop cleanly for channel %s", self.channel_id)

        # Clear all subscribers and signal EOF
        with self.subscribers_lock:
            for queue in self.subscribers.values():
                try:
                    queue.put_nowait(b"")
                except Exception:
                    pass
            self.subscribers.clear()

        self._stopped = True
        self._logger.info("ChannelStream stopped for channel %s", self.channel_id)

    def subscribe(self, client_id: str, queue_size: int = 100) -> Queue[bytes]:
        """
        Subscribe a new HTTP client to receive TS chunks.

        Args:
            client_id: Unique identifier for this client
            queue_size: Maximum queue size (default: 100 chunks)

        Returns:
            Queue that will receive TS chunks
        """
        queue: Queue[bytes] = Queue(maxsize=queue_size)

        with self.subscribers_lock:
            self.subscribers[client_id] = queue

        subscriber_count = len(self.subscribers)
        self._logger.info(
            "[channel %s] subscribers: %d (client %s connected)",
            self.channel_id,
            subscriber_count,
            client_id,
        )

        # Start reader if not already running
        if not self.reader_thread or not self.reader_thread.is_alive():
            self.start()

        return queue

    def unsubscribe(self, client_id: str) -> None:
        """Unsubscribe an HTTP client."""
        with self.subscribers_lock:
            removed = self.subscribers.pop(client_id, None)
            subscriber_count = len(self.subscribers)

        if removed is not None:
            self._logger.info(
                "[channel %s] subscribers: %d (client %s disconnected)",
                self.channel_id,
                subscriber_count,
                client_id,
            )

        # Phase 8.5: when last subscriber leaves, stop reader so no ongoing work until next tune-in
        # Check regardless of whether client was found (it may have been evicted by reader thread)
        if subscriber_count == 0:
            self.stop()

    def get_subscriber_count(self) -> int:
        """Get current number of active subscribers."""
        with self.subscribers_lock:
            return len(self.subscribers)

    def is_running(self) -> bool:
        """Check if reader thread is running."""
        return (
            self.reader_thread is not None
            and self.reader_thread.is_alive()
            and not self._stopped
        )


def generate_ts_stream(client_queue: Queue[bytes]) -> Any:
    """
    Generator function for FastAPI StreamingResponse.

    Reads TS chunks from client queue and yields them.
    Stops when queue receives empty bytes (EOF signal).

    Args:
        client_queue: Queue receiving TS chunks from ChannelStream

    Yields:
        TS data chunks (bytes)
    """
    consecutive_timeouts = 0
    # Exit after 10 seconds of no data during shutdown.
    # Must be > prebuffer time (2s) + encoder warmup (~3s) to allow initial buffering.
    max_consecutive_timeouts = 20
    while True:
        try:
            chunk = client_queue.get(timeout=0.5)
            consecutive_timeouts = 0  # Reset on successful read
            if not chunk:  # EOF signal
                break
            yield chunk
        except Empty:
            # Timeout - continue waiting (allows graceful shutdown on disconnect)
            # FastAPI will close connection if client disconnects
            consecutive_timeouts += 1
            # Safety exit: if no data for extended period, assume shutdown
            if consecutive_timeouts >= max_consecutive_timeouts:
                _logger.debug("generate_ts_stream exiting due to timeout (possible shutdown)")
                break
            continue
        except GeneratorExit:
            # Client disconnected
            break


async def generate_ts_stream_async(client_queue: Queue[bytes]) -> Any:
    """
    INV-IO-DRAIN-REALTIME: Async generator for live TS streaming.

    This async version yields to the event loop between chunks to ensure:
    - Non-blocking streaming
    - Backpressure-aware draining
    - Regular yielding to event loop
    - Flush-friendly chunk cadence
    - Clean disconnect semantics

    Args:
        client_queue: Queue receiving TS chunks from ChannelStream

    Yields:
        TS data chunks (bytes)
    """
    import asyncio

    consecutive_timeouts = 0
    max_consecutive_timeouts = 20  # 10 seconds at 0.5s timeout
    loop = asyncio.get_event_loop()

    while True:
        try:
            # Use run_in_executor to make the blocking get() async-friendly
            chunk = await loop.run_in_executor(
                None,
                lambda: client_queue.get(timeout=0.1)  # Short timeout for responsiveness
            )
            consecutive_timeouts = 0
            if not chunk:  # EOF signal
                break
            yield chunk
            # Yield to event loop after each chunk for flush opportunity
            await asyncio.sleep(0)
        except Empty:
            consecutive_timeouts += 1
            if consecutive_timeouts >= max_consecutive_timeouts * 5:  # Adjusted for shorter timeout
                _logger.debug("generate_ts_stream_async exiting due to timeout")
                break
            # Yield to event loop even when queue is empty
            await asyncio.sleep(0.01)
            continue
        except GeneratorExit:
            break
        except asyncio.CancelledError:
            break

