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
import select
import socket
import threading
import time
from collections import deque
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Any, Callable, Literal, Optional, Protocol

from .clock import AuthoritativeClock
from .ts_ring_buffer import TsRingBuffer


class BytesBoundedQueue:
    """
    Thread-safe queue with a byte-size cap. When full, oldest chunks are dropped.
    Used for per-client TS buffers so backpressure is per-client only.
    """

    def __init__(self, max_bytes: int) -> None:
        self._max_bytes = max(64 * 1024, max_bytes)
        self._lock = threading.Lock()
        self._chunks: deque[bytes] = deque()
        self._current_bytes = 0
        self._not_empty = threading.Condition(self._lock)
        self._closed = False

    def put_nowait(self, chunk: bytes) -> bool:
        """Enqueue chunk; drop oldest if over cap. Returns True if any chunk was dropped. Accepts b'' as EOF."""
        if self._closed:
            return False
        had_eviction = False
        with self._lock:
            if self._closed:
                return False
            while self._chunks and self._current_bytes + len(chunk) > self._max_bytes:
                old = self._chunks.popleft()
                self._current_bytes -= len(old)
                had_eviction = True
            self._chunks.append(chunk)
            self._current_bytes += len(chunk)
            self._not_empty.notify()
        return had_eviction

    def get(self, timeout: Optional[float] = None) -> Optional[bytes]:
        """Block until a chunk is available or timeout. Returns None if closed or timeout."""
        with self._not_empty:
            while not self._closed and not self._chunks:
                if timeout is not None:
                    if not self._not_empty.wait(timeout=timeout):
                        raise Empty
                else:
                    self._not_empty.wait()
            if self._closed:
                return None
            if not self._chunks:
                raise Empty
            chunk = self._chunks.popleft()
            self._current_bytes -= len(chunk)
            return chunk

    def drain_many(self, max_bytes: int = 65536) -> Optional[bytes]:
        """Drain up to max_bytes of queued data as a single consolidated buffer.

        Returns None if closed, raises Empty if no data and timeout not applicable.
        Reduces per-chunk overhead in the async HTTP drain path.
        """
        with self._not_empty:
            while not self._closed and not self._chunks:
                if not self._not_empty.wait(timeout=0.1):
                    raise Empty
            if self._closed:
                return None
            if not self._chunks:
                raise Empty
            # Check for EOF sentinel
            if self._chunks[0] == b"":
                self._chunks.popleft()
                return b""
            parts: list[bytes] = []
            collected = 0
            while self._chunks and collected < max_bytes:
                chunk = self._chunks[0]
                if chunk == b"":
                    break  # EOF sentinel — leave it for next call
                self._chunks.popleft()
                self._current_bytes -= len(chunk)
                parts.append(chunk)
                collected += len(chunk)
            if not parts:
                raise Empty
            return b"".join(parts) if len(parts) > 1 else parts[0]

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._not_empty.notify_all()

    @property
    def current_bytes(self) -> int:
        with self._lock:
            return self._current_bytes

    @property
    def current_chunk_count(self) -> int:
        with self._lock:
            return len(self._chunks)

_SpikeKind = Literal["work_spike", "scheduling_jitter", "no_spike"]


def _classify_upstream_spike(
    duration_ms: float,
    select_ms: float,
    recv_ms: float,
    put_ms: float,
    threshold_ms: float,
) -> _SpikeKind:
    """
    INV-HTTP-UPSTREAM-SPIKE-001: Classify an upstream loop iteration.

    WARNING fires only when data-path work (recv+put) exceeds the threshold.
    A spike dominated by select() is OS scheduling / GC jitter — socket buffers
    absorb the gap and no data-path problem exists.  Downgrade to DEBUG.
    """
    if duration_ms <= threshold_ms:
        return "no_spike"
    if recv_ms + put_ms > threshold_ms:
        return "work_spike"
    return "scheduling_jitter"


_logger = logging.getLogger(__name__)

# =============================================================================
# CORE_TRANSPORT_DIAG: Per-stage timing instrumentation for slope analysis.
# Proves or falsifies whether Core delivery is bursty when AIR output is uniform.
# =============================================================================
# Diagnostic constants — set per-instance from resolved_config in ChannelStream.__init__.
# Module-level values are sentinels for code outside the class (pre-instance).
_DIAG_ENABLED = os.environ.get("RETROVUE_DIAG", "0") == "1"
_DIAG_STARTUP_EVENTS = 200
_DIAG_STEADY_INTERVAL = 100

# =============================================================================
# AUDIT: INV-UDS-DRAIN timing instrumentation
# =============================================================================
_AUDIT_T0: int | None = None  # Thread started (monotonic_ns)
_AUDIT_T1: int | None = None  # Before first recv (monotonic_ns)
_AUDIT_T2: int | None = None  # After first recv returns data (monotonic_ns)
_AUDIT_FIRST_RECV_DONE = False
_AUDIT_LOCK = threading.Lock()

# =============================================================================
# RECV-GAP TELEMETRY CONSTANTS (Contract: do not change without updating tests)
# =============================================================================
# These constants define the recv-gap warning policy. They are NOT correctness
# signals - recv gaps depend on socket buffering, OS scheduling, and encoder
# cadence. This telemetry exists only to detect systemic issues, not to enforce
# frame-level timing guarantees.
#
# Policy: Emit at most ONE warning per session, only if we observe >= 10 gaps
# exceeding the threshold. This prevents log spam while still surfacing patterns.
# Streaming constants — set per-instance from resolved_config in ChannelStream.__init__.
# Module-level values are sentinels for type annotations and pre-instance code.
RECV_GAP_WARN_THRESHOLD_MS: int = 40
RECV_GAP_WARN_COUNT: int = 10
SLOW_CLIENT_PUT_TIMEOUT_S: float = 3.0
BACKPRESSURE_SLOW_THRESHOLD_S: float = 5.0
BackpressurePolicy = Literal["drop_oldest", "disconnect"]
DEFAULT_BACKPRESSURE_POLICY: BackpressurePolicy = "disconnect"
UPSTREAM_POLL_TIMEOUT_S: float = 0.05
UPSTREAM_LOOP_SPIKE_MS: float = 50.0
BACKPRESSURE_LOG_INTERVAL_S: float = 5.0


class TsSource(Protocol):
    """Protocol for TS data source (UDS or fake for tests)."""

    def read(self, size: int) -> bytes:
        """Read TS data (blocks until data available, or non-blocking)."""
        ...

    def close(self) -> None:
        """Close the source."""
        ...

    def get_socket(self) -> Optional[socket.socket]:
        """Return the underlying socket for select(), or None (e.g. fake source)."""
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

            # Bound UDS kernel recv buffer to absorb Python reader pauses.
            # At ~312 KB/s TS wire rate, 128 KB ≈ 410 ms (Linux doubles to ~256 KB ≈ 820 ms).
            # Combined with AIR's SO_SNDBUF=128KB, total kernel buffer ≈ 512 KB (~1.6s).
            import sys
            if sys.platform.startswith("linux"):
                try:
                    _requested_rcvbuf = 131072
                    self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, _requested_rcvbuf)
                    effective = self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
                    _logger.info(
                        "[UDS-BUF] SO_RCVBUF: requested=%d effective=%d", _requested_rcvbuf, effective
                    )
                except Exception as e:
                    _logger.warning(
                        "[UDS-BUF] setsockopt(SO_RCVBUF=%d) failed: %s (continuing with default)",
                        131072, e,
                    )

            # AUDIT: Log actual kernel buffer sizes
            try:
                rcvbuf = self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
                sndbuf = self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF)
                _logger.debug("[AUDIT-BUF] UdsTsSource socket: SO_RCVBUF=%d bytes, SO_SNDBUF=%d bytes",
                            rcvbuf, sndbuf)
            except Exception as e:
                _logger.warning("[AUDIT-BUF] Could not read socket buffer sizes: %s", e)

            # Non-blocking so upstream reader never blocks indefinitely; use select for readiness.
            self.sock.setblocking(False)
            _logger.info(
                "[HTTP] UPSTREAM_CONNECTED fd=%s path=%s",
                self.sock.fileno() if self.sock else None,
                self.socket_path,
            )
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
        """Read TS data from socket (non-blocking; call when select says readable)."""
        if not self.sock or not self._connected:
            raise IOError("Not connected to UDS socket")
        try:
            data = self.sock.recv(size)
            if not data:  # EOF
                _logger.warning(
                    "[HTTP] UPSTREAM_DISCONNECTED reason=EOF path=%s",
                    self.socket_path,
                )
                self._connected = False
                return b""
            return data
        except BlockingIOError:
            return b""  # EAGAIN; caller uses select, so rare
        except (OSError, socket.error) as e:
            err = getattr(e, "errno", None)
            _logger.warning(
                "[HTTP] UPSTREAM_DISCONNECTED errno=%s error=%s path=%s",
                err, e, self.socket_path,
            )
            self._connected = False
            raise IOError(f"UDS read error: {e}") from e

    def close(self) -> None:
        """Close the UDS socket. Only called on explicit channel stop or fatal error."""
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

    def get_socket(self) -> Optional[socket.socket]:
        return self.sock if self._connected else None

    @property
    def is_connected(self) -> bool:
        """Check if connected to UDS."""
        return self._connected and self.sock is not None


class SocketTsSource:
    """TS source that reads from an already-connected socket (e.g. Air connected to our server)."""

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self._connected = True

        # Bound UDS kernel recv buffer to absorb Python reader pauses.
        # At ~312 KB/s TS wire rate, 128 KB ≈ 410 ms (Linux doubles to ~256 KB ≈ 820 ms).
        # Combined with AIR's SO_SNDBUF=128KB, total kernel buffer ≈ 512 KB (~1.6s).
        import sys
        if sys.platform.startswith("linux"):
            try:
                _requested_rcvbuf = 131072
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, _requested_rcvbuf)
                effective = sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
                _logger.debug(
                    "[UDS-BUF] SO_RCVBUF: requested=%d effective=%d", _requested_rcvbuf, effective
                )
            except Exception as e:
                _logger.warning(
                    "[UDS-BUF] setsockopt(SO_RCVBUF=%d) failed: %s (continuing with default)",
                    131072, e,
                )

        # AUDIT: Log actual kernel buffer sizes
        try:
            rcvbuf = sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
            sndbuf = sock.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF)
            _logger.debug("[AUDIT-BUF] SocketTsSource socket: SO_RCVBUF=%d bytes, SO_SNDBUF=%d bytes",
                        rcvbuf, sndbuf)
        except Exception as e:
            _logger.warning("[AUDIT-BUF] Could not read socket buffer sizes: %s", e)

        # Non-blocking so upstream reader uses select; downstream never blocks upstream.
        sock.setblocking(False)
        _logger.info("[HTTP] UPSTREAM_CONNECTED fd=%s (socket from Air)", sock.fileno())

    def get_socket(self) -> Optional[socket.socket]:
        return self.sock if self._connected else None

    def read(self, size: int) -> bytes:
        if not self.sock or not self._connected:
            raise IOError("Socket not connected")
        try:
            data = self.sock.recv(size)
            if not data:
                _logger.info("[HTTP] UPSTREAM_DISCONNECTED reason=EOF (Air closed)")
                self._connected = False
                return b""
            return data
        except BlockingIOError:
            return b""
        except (OSError, socket.error) as e:
            err = getattr(e, "errno", None)
            _logger.warning("[HTTP] UPSTREAM_DISCONNECTED errno=%s error=%s", err, e)
            self._connected = False
            raise IOError(f"Socket read error: {e}") from e

    def close(self) -> None:
        """Close the socket. Only on explicit stop or fatal error; never due to downstream."""
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


class ChannelStream:
    """
    Per-channel TS stream: upstream (AIR UDS) → ring buffer → downstream (HTTP clients).

    Decoupled design: upstream reader never blocks on downstream. Downstream
    behavior (VLC stall/disconnect) never closes upstream. Upstream only closes
    on AIR disconnect or explicit channel stop.
    """

    def __init__(
        self,
        channel_id: str,
        socket_path: str | Path | None = None,
        ts_source_factory: Callable[..., TsSource] | None = None,
        hls_segmenter: Any | None = None,
        *,
        clock: AuthoritativeClock,
        ring_buffer_max_bytes: int | None = None,
        client_buffer_max_bytes: int | None = None,
        backpressure_policy: BackpressurePolicy = DEFAULT_BACKPRESSURE_POLICY,
        resolved_config: Any | None = None,
    ):
        """
        Initialize ChannelStream for a channel.

        Args:
            channel_id: Channel identifier
            socket_path: UDS socket path (if None, uses ts_source_factory)
            ts_source_factory: Factory for creating TS source (for tests)
            hls_segmenter: Optional HlsSegmenter (new canonical segmenter) to tee TS data
            ring_buffer_max_bytes: Max ring buffer size (overrides config)
            client_buffer_max_bytes: Per-client queue byte cap (overrides config)
            backpressure_policy: "drop_oldest" (preferred for live) or "disconnect"
            resolved_config: Frozen resolved config (REQUIRED in production)
        """
        # Extract streaming config values from resolved_config.
        if resolved_config is not None and "streaming" in resolved_config:
            _stm = resolved_config["streaming"]
            _bufs = _stm["buffers"]
            _default_ring = _bufs["ring_buffer_max_bytes"]
            _default_client = _bufs["client_buffer_bytes"]
        else:
            # Test-only path: explicit bytes params are required when no config.
            _default_ring = 8 * 1024 * 1024
            _default_client = 4_000_000

        self.channel_id = channel_id
        self.socket_path = Path(socket_path) if socket_path else None
        self.ts_source_factory = ts_source_factory
        self.hls_segmenter = hls_segmenter
        self._clock = clock
        self._backpressure_policy = backpressure_policy
        self._client_buffer_max_bytes = (
            client_buffer_max_bytes
            if client_buffer_max_bytes is not None
            else _default_client
        )
        ring_bytes = (
            ring_buffer_max_bytes
            if ring_buffer_max_bytes is not None
            else _default_ring
        )

        self._logger = logging.getLogger(f"{__name__}.{channel_id}")

        # Bounded ring buffer: upstream pushes, fanout consumes. Downstream never blocks upstream.
        def _on_ring_drop(dropped: int) -> None:
            self._logger.warning(
                "[HTTP] BACKPRESSURE drop_oldest bytes=%d channel=%s",
                dropped, self.channel_id,
            )
        self._ring_buffer = TsRingBuffer(
            max_bytes=ring_bytes,
            on_drop=_on_ring_drop,
        )

        # Active subscribers (client_id -> bytes-bounded queue)
        self.subscribers: dict[str, BytesBoundedQueue] = {}
        self.subscribers_lock = threading.Lock()

        # Upstream reader thread (UDS → ring buffer) and fanout thread (ring buffer → clients)
        self.reader_thread: threading.Thread | None = None
        self._fanout_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._stopped = False

        # TS source
        self.ts_source: TsSource | None = None

        # Reconnect backoff
        # INV-CHANNEL-STREAM-RECONNECT-001: ~33s total window gives
        # liveness recovery enough time to restart the producer.
        self._reconnect_delays = [1.0, 2.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0]
        self._current_reconnect_delay_index = 0

        # Debug: log first 16 bytes once per connection to verify TS sync 0x47
        self._first_chunk_logged = False
        # Throttle BACKPRESSURE logs per client_id
        self._backpressure_log_last: dict[str, float] = {}
        self._backpressure_log_lock = threading.Lock()

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
        """Create TS source (UDS or fake for tests).

        Passes _stop_event to the factory so blocking factories (e.g. those
        waiting on a socket queue) can exit immediately when stop() is called
        (INV-CHANNEL-STREAM-SHUTDOWN-001).
        """
        if self.ts_source_factory:
            return self.ts_source_factory(self._stop_event)
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

            try:
                self.ts_source = self._create_ts_source()
            except Exception as e:
                self._logger.warning(
                    "TS source factory failed for channel %s (attempt %d/%d): %s",
                    self.channel_id, attempt + 1, max_attempts, e,
                )
                self.ts_source = None
                # Fall through to backoff/retry below
                if attempt < max_attempts - 1:
                    delay = self._reconnect_delays[
                        min(self._current_reconnect_delay_index, len(self._reconnect_delays) - 1)
                    ]
                    if self._stop_event.wait(timeout=delay):
                        return False
                    self._current_reconnect_delay_index = min(
                        self._current_reconnect_delay_index + 1, len(self._reconnect_delays) - 1
                    )
                continue

            if isinstance(self.ts_source, UdsTsSource):
                if self.ts_source.connect(timeout=2.0):
                    self._current_reconnect_delay_index = 0
                    return True
            else:
                # SocketTsSource (Air) or test source: already connected / no connect
                self._logger.debug(
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

    def _upstream_reader_loop(self) -> None:
        """
        Component A: Upstream reader. Only select(), read(), ring_buffer.put().
        No fanout locks, minimal logging, no heavy work or large allocations.
        Loop duration logged per iteration; WARNING if > 50 ms (spike).
        """
        self._logger.debug(
            "[HTTP] Upstream reader started for channel %s", self.channel_id
        )
        chunk_size = 32768  # ~174 TS packets; reduces iterations from ~166/s to ~10-20/s

        # CORE_TRANSPORT_DIAG: upstream read instrumentation
        _diag_recv_count = 0
        _diag_recv_cumulative_bytes = 0
        _diag_recv_t0 = None  # set on first recv

        # STARTUP_CAPTURE: Tee first 512KB of TS to disk for ffprobe analysis
        _capture_path = Path("/tmp") / f"retrovue_startup_{self.channel_id}.ts"
        _capture_fd: Any = None
        _capture_remaining = 512 * 1024  # bytes to capture
        try:
            _capture_fd = open(_capture_path, "wb")
            self._logger.debug(
                "STARTUP_CAPTURE: writing first 512KB to %s", _capture_path
            )
        except OSError as e:
            self._logger.debug("STARTUP_CAPTURE: failed to open %s: %s", _capture_path, e)

        # Only log spike when truly slow: > 3× poll timeout, or did read and > 50 ms
        spike_threshold_long_ms = 3 * (UPSTREAM_POLL_TIMEOUT_S * 1000)
        while not self._stop_event.is_set():
            t_start = self._clock.monotonic_ns()
            bytes_read_this_iter = 0
            t_after_select = t_start
            t_after_recv = t_start
            t_after_put = t_start
            try:
                if not self.ts_source:
                    if not self._connect_with_backoff():
                        self._logger.info(
                            "Initial UDS connection failed for channel %s, stopping",
                            self.channel_id,
                        )
                        break
                if isinstance(
                    self.ts_source, UdsTsSource
                ) and not self.ts_source.is_connected:
                    break

                sock = self.ts_source.get_socket() if self.ts_source else None
                if sock:
                    try:
                        r, _, _ = select.select(
                            [sock], [], [], UPSTREAM_POLL_TIMEOUT_S
                        )
                        t_after_select = self._clock.monotonic_ns()
                        if not r:
                            continue
                    except (OSError, ValueError):
                        continue

                # Re-check after select: stop() may have set ts_source to None during shutdown
                if not self.ts_source:
                    break
                chunk = self.ts_source.read(chunk_size)
                t_after_recv = self._clock.monotonic_ns()
                bytes_read_this_iter = len(chunk)
                if not chunk:
                    # INV-CHANNEL-STREAM-RECONNECT-001: EOF from upstream
                    # (AIR crashed or was restarted).  Reconnect via factory
                    # instead of exiting — the factory will resolve the
                    # current producer's socket queue dynamically.
                    if self.ts_source:
                        try:
                            self.ts_source.close()
                        except Exception:
                            pass
                        self.ts_source = None
                    self._first_chunk_logged = False
                    # If stop was requested, exit cleanly instead of reconnecting.
                    if self._stop_event.is_set():
                        break
                    self._logger.info(
                        "[HTTP] UPSTREAM_EOF channel=%s, attempting reconnect",
                        self.channel_id,
                    )
                    continue  # next iteration enters _connect_with_backoff
                # STARTUP_CAPTURE: tee to disk
                if _capture_fd is not None and _capture_remaining > 0:
                    to_write = chunk[:_capture_remaining]
                    try:
                        _capture_fd.write(to_write)
                        _capture_remaining -= len(to_write)
                        if _capture_remaining <= 0:
                            _capture_fd.close()
                            _capture_fd = None
                            self._logger.debug(
                                "STARTUP_CAPTURE: complete (%s)", _capture_path
                            )
                    except OSError:
                        _capture_fd = None
                self._ring_buffer.put(chunk)
                t_after_put = self._clock.monotonic_ns()
                # CORE_TRANSPORT_DIAG: UDS recv timing
                if _DIAG_ENABLED and bytes_read_this_iter > 0:
                    _diag_recv_count += 1
                    _diag_recv_cumulative_bytes += bytes_read_this_iter
                    if _diag_recv_t0 is None:
                        _diag_recv_t0 = t_after_recv
                    if (_diag_recv_count <= _DIAG_STARTUP_EVENTS or
                            _diag_recv_count % _DIAG_STEADY_INTERVAL == 0):
                        wall_us = t_after_recv // 1000
                        self._logger.info(
                            "CORE_RECV_DIAG: recv_seq=%d wall_us=%d bytes=%d "
                            "cumulative_bytes=%d select_ms=%.2f recv_ms=%.2f put_ms=%.2f "
                            "ring_bytes=%d channel=%s",
                            _diag_recv_count, wall_us, bytes_read_this_iter,
                            _diag_recv_cumulative_bytes,
                            (t_after_select - t_start) / 1e6,
                            (t_after_recv - t_after_select) / 1e6,
                            (t_after_put - t_after_recv) / 1e6,
                            self._ring_buffer.current_bytes,
                            self.channel_id,
                        )
            except IOError as e:
                self._logger.warning(
                    "[HTTP] UPSTREAM_DISCONNECTED reason=read_error error=%s "
                    "channel=%s, attempting reconnect",
                    e, self.channel_id,
                )
                if self.ts_source:
                    try:
                        self.ts_source.close()
                    except Exception:
                        pass
                    self.ts_source = None
                self._first_chunk_logged = False
                continue  # reconnect via _connect_with_backoff
            finally:
                duration_ms = (self._clock.monotonic_ns() - t_start) / 1e6
                self._logger.debug(
                    "[HTTP] UPSTREAM_LOOP channel=%s loop_duration_ms=%.2f",
                    self.channel_id, duration_ms,
                )
                select_ms = (t_after_select - t_start) / 1e6
                recv_ms = (t_after_recv - t_after_select) / 1e6
                put_ms = (t_after_put - t_after_recv) / 1e6
                spike_kind = _classify_upstream_spike(
                    duration_ms, select_ms, recv_ms, put_ms,
                    threshold_ms=spike_threshold_long_ms,
                )
                if spike_kind != "no_spike":
                    if self._stop_event.is_set():
                        # Teardown drain: socket closing causes slow I/O — expected, harmless
                        self._logger.info(
                            "[HTTP] UPSTREAM_LOOP channel=%s loop_duration_ms=%.2f (teardown drain) select_ms=%.2f recv_ms=%.2f put_ms=%.2f",
                            self.channel_id, duration_ms, select_ms, recv_ms, put_ms,
                        )
                    elif spike_kind == "work_spike":
                        # Data path (recv+put) is actually slow — actionable
                        self._logger.warning(
                            "[HTTP] UPSTREAM_LOOP channel=%s loop_duration_ms=%.2f (work spike >%.0fms) select_ms=%.2f recv_ms=%.2f put_ms=%.2f",
                            self.channel_id, duration_ms, spike_threshold_long_ms,
                            select_ms, recv_ms, put_ms,
                        )
                    else:
                        # select-dominated: OS scheduling / GC jitter, absorbed by socket buffers
                        self._logger.debug(
                            "[HTTP] UPSTREAM_LOOP channel=%s loop_duration_ms=%.2f (scheduling jitter select_ms=%.2f) recv_ms=%.2f put_ms=%.2f",
                            self.channel_id, duration_ms, select_ms, recv_ms, put_ms,
                        )

        self._ring_buffer.close()
        if self.ts_source:
            try:
                self.ts_source.close()
            except Exception:
                pass
            self.ts_source = None
        self._stopped = True
        self._logger.debug(
            "[HTTP] Upstream reader stopped for channel %s", self.channel_id
        )

    def _fanout_loop(self) -> None:
        """
        Component B: Fanout. Consume from ring buffer, put to each client queue.
        Slow clients: put_nowait; on Full apply backpressure policy (drop or disconnect).
        Never closes upstream. Runs regardless of subscriber count: with 0 clients we
        still get() from the ring buffer (draining it) and discard; upstream never blocks.
        """
        # CORE_TRANSPORT_DIAG: fanout instrumentation
        _diag_fanout_count = 0
        _diag_fanout_cumulative_bytes = 0

        while not self._stop_event.is_set():
            chunk = self._ring_buffer.get(timeout=UPSTREAM_POLL_TIMEOUT_S)
            if chunk is None:
                continue
            # CORE_TRANSPORT_DIAG: fanout dequeue timing
            if _DIAG_ENABLED:
                _diag_fanout_count += 1
                _diag_fanout_cumulative_bytes += len(chunk)
                if (_diag_fanout_count <= _DIAG_STARTUP_EVENTS or
                        _diag_fanout_count % _DIAG_STEADY_INTERVAL == 0):
                    wall_us = self._clock.monotonic_ns() // 1000
                    self._logger.info(
                        "CORE_FANOUT_DIAG: fanout_seq=%d wall_us=%d bytes=%d "
                        "cumulative_bytes=%d ring_bytes=%d subscribers=%d channel=%s",
                        _diag_fanout_count, wall_us, len(chunk),
                        _diag_fanout_cumulative_bytes,
                        self._ring_buffer.current_bytes,
                        len(self.subscribers),
                        self.channel_id,
                    )
            if self.hls_segmenter is not None:
                try:
                    self.hls_segmenter.feed(chunk)
                except Exception:
                    pass
            with self.subscribers_lock:
                subscribers_snapshot = list(self.subscribers.items())
            # With 0 subscribers we still consumed one chunk (drain); nothing to put.
            to_remove: list[str] = []
            for client_id, client_queue in subscribers_snapshot:
                had_eviction = client_queue.put_nowait(chunk)
                if had_eviction:
                    now = self._clock.monotonic()
                    do_log = False
                    with self._backpressure_log_lock:
                        last = self._backpressure_log_last.get(client_id, 0.0)
                        if now - last >= BACKPRESSURE_LOG_INTERVAL_S:
                            self._backpressure_log_last[client_id] = now
                            do_log = True
                    if do_log:
                        qb = client_queue.current_bytes
                        qc = client_queue.current_chunk_count
                        # AIR encodes at ~5 Mbit/s (H.264 VBV-constrained)
                        est_ms = int(qb * 8 / 5_000_000 * 1000) if qb else 0
                        self._logger.warning(
                            "[HTTP] BACKPRESSURE client_queue_bytes=%d client_queue_chunks=%d "
                            "action=drop estimated_client_buffer_ms=%d client_id=%s",
                            qb, qc, est_ms, client_id,
                        )
                    if self._backpressure_policy == "disconnect":
                        to_remove.append(client_id)
            for cid in to_remove:
                with self.subscribers_lock:
                    q = self.subscribers.pop(cid, None)
                if q is not None:
                    detach_bytes = q.current_bytes
                    # Log BEFORE sentinel so observers cannot react to
                    # the disconnect before the observability event exists.
                    self._logger.info(
                        "[HTTP] SLOW_CONSUMER_DISCONNECT client_id=%s channel_id=%s "
                        "reason=backpressure_disconnect queue_bytes_at_detach=%d",
                        cid, self.channel_id, detach_bytes,
                    )
                    try:
                        q.put_nowait(b"")
                    except Full:
                        pass
                # Clean up per-client throttle state to prevent memory leaks
                with self._backpressure_log_lock:
                    self._backpressure_log_last.pop(cid, None)
        self._logger.debug(
            "[HTTP] Fanout loop stopped for channel %s", self.channel_id
        )

    def start(self) -> None:
        """Start upstream reader thread and fanout thread."""
        global _AUDIT_T0, _AUDIT_T1, _AUDIT_T2, _AUDIT_FIRST_RECV_DONE

        if self.reader_thread is not None and self.reader_thread.is_alive():
            return  # Already running

        self._stop_event.clear()
        self._stopped = False

        with _AUDIT_LOCK:
            _AUDIT_T0 = self._clock.monotonic_ns()
            _AUDIT_T1 = None
            _AUDIT_T2 = None
            _AUDIT_FIRST_RECV_DONE = False
        self._logger.debug(
            "[AUDIT-T0] Reader thread spawning at %d ns for channel %s",
            _AUDIT_T0, self.channel_id,
        )

        self.reader_thread = threading.Thread(
            target=self._upstream_reader_loop,
            name=f"ChannelStream-upstream-{self.channel_id}",
            daemon=True,
        )
        self.reader_thread.start()
        self._fanout_thread = threading.Thread(
            target=self._fanout_loop,
            name=f"ChannelStream-fanout-{self.channel_id}",
            daemon=True,
        )
        self._fanout_thread.start()
        self._logger.debug("ChannelStream started (upstream+fanout) for channel %s", self.channel_id)

    def signal_stop(self) -> None:
        """Signal the stop event without joining threads or closing resources.

        Call this *before* tearing down the producer/AIR so that the reader
        loop sees the event immediately when the socket EOF arrives, avoiding
        a spurious reconnect attempt.
        """
        self._stop_event.set()

    def stop(self) -> None:
        """
        Stop upstream and fanout threads. Close UDS only on explicit stop
        (e.g. channel teardown). Never called merely because last subscriber left.
        """
        if self._stopped:
            return

        self._logger.debug("[teardown] stopping upstream+fanout for channel %s", self.channel_id)
        self._stop_event.set()
        self._ring_buffer.close()

        if self.ts_source:
            try:
                self.ts_source.close()
            except Exception:
                pass
            self.ts_source = None

        for th, name in [
            (self.reader_thread, "upstream"),
            (self._fanout_thread, "fanout"),
        ]:
            if th and th.is_alive():
                th.join(timeout=5.0)
                if th.is_alive():
                    self._logger.warning(
                        "ChannelStream %s thread did not stop cleanly for channel %s",
                        name, self.channel_id,
                    )
        self._fanout_thread = None

        with self.subscribers_lock:
            for queue in self.subscribers.values():
                try:
                    queue.put_nowait(b"")
                except Exception:
                    pass
            self.subscribers.clear()

        self._stopped = True
        self._logger.debug("ChannelStream stopped for channel %s", self.channel_id)

    def subscribe(self, client_id: str) -> BytesBoundedQueue:
        """
        Subscribe a new HTTP client to receive TS chunks.

        Args:
            client_id: Unique identifier for this client

        Returns:
            Bytes-bounded queue that will receive TS chunks (byte cap from config).
        """
        queue = BytesBoundedQueue(max_bytes=self._client_buffer_max_bytes)

        was_running = self.reader_thread is not None and self.reader_thread.is_alive()

        with self.subscribers_lock:
            self.subscribers[client_id] = queue
            subscriber_count = len(self.subscribers)

        stream_state = "existing" if was_running else "fresh"
        self._logger.info(
            "[HTTP] CLIENT_CONNECTED id=%s channel=%s subscribers=%d stream_state=%s",
            client_id, self.channel_id, subscriber_count, stream_state,
        )

        if not was_running:
            self.start()

        return queue

    def unsubscribe(self, client_id: str, reason: str = "disconnect") -> None:
        """
        Unsubscribe an HTTP client. Does NOT stop upstream or close UDS when
        last subscriber leaves; upstream survives for reconnect.
        """
        with self.subscribers_lock:
            removed = self.subscribers.pop(client_id, None)
            subscriber_count = len(self.subscribers)

        if removed is not None:
            detach_bytes = removed.current_bytes
            self._logger.info(
                "[HTTP] CLIENT_DISCONNECTED id=%s reason=%s channel=%s subscribers=%d "
                "queue_bytes_at_detach=%d",
                client_id, reason, self.channel_id, subscriber_count, detach_bytes,
            )
        # Do NOT call self.stop() when subscriber_count == 0. Upstream stays alive.

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

    def get_ring_buffer_metrics(self) -> dict[str, int]:
        """Ring buffer metrics: current_bytes, dropped_bytes, high_water_mark."""
        return {
            "current_bytes": self._ring_buffer.current_bytes,
            "dropped_bytes": self._ring_buffer.dropped_bytes,
            "high_water_mark": self._ring_buffer.high_water_mark,
        }


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


WRITE_TIMEOUT_S: float = 10.0  # INV-SLOW-CONSUMER-DISCONNECT-001


async def generate_ts_stream_async(
    client_queue: Queue[bytes],
    *,
    clock: AuthoritativeClock,
    write_timeout_s: float = WRITE_TIMEOUT_S,
    client_id: str = "unknown",
) -> Any:
    """
    INV-IO-DRAIN-REALTIME: Async generator for live TS streaming.

    Batch-drains up to 64 KB per executor call to reduce per-chunk overhead
    and produce larger, more efficient TCP writes.

    INV-SLOW-CONSUMER-DISCONNECT-001: If a yield (TCP write) takes longer
    than write_timeout_s, the client is considered dead and the connection
    is closed.

    Args:
        client_queue: BytesBoundedQueue receiving TS chunks from ChannelStream
        clock: AuthoritativeClock used for all elapsed-time measurements
            (drain timing, stall detection, yield write-timeout). No
            wall-clock fallback.
        write_timeout_s: Max seconds a yield/TCP-write may block before
            the connection is severed (default: 10s).

    Yields:
        TS data chunks (bytes)
    """
    import asyncio

    consecutive_timeouts = 0
    max_consecutive_timeouts = 100  # 10 seconds at 0.1s timeout
    loop = asyncio.get_event_loop()

    # CORE_TRANSPORT_DIAG: HTTP yield instrumentation
    _diag_yield_count = 0
    _diag_yield_cumulative_bytes = 0
    _diag_timeout_total = 0
    _exit_reason = "normal"

    # TS liveness tracking — zero steady-state logging
    _ts_session_start_mono = clock.monotonic()
    _ts_last_write_mono = _ts_session_start_mono
    _ts_max_gap_ms: float = 0.0
    _ts_stall_count = 0
    _TS_STALL_THRESHOLD_S = 2.0  # emit TS_WRITE_STALL if gap exceeds this

    # Cadence histogram — bucket counts, zero per-write logging
    # Buckets: 0-10, 10-30, 30-60, 60-100, 100-300, 300+ ms
    _cadence_buckets = [0, 0, 0, 0, 0, 0]  # counts per bucket
    _cadence_sum_ms: float = 0.0  # for avg computation
    # Burst detection: runs of <10ms followed by >100ms
    _burst_count = 0
    _in_rapid_run = False
    # Sorted reservoir for percentile estimation (fixed-size)
    _RESERVOIR_SIZE = 2000
    _cadence_reservoir: list[float] = []
    _cadence_reservoir_idx = 0  # total samples seen (for reservoir sampling)

    while True:
        try:
            t_drain_start = clock.monotonic_ns()
            batch = await loop.run_in_executor(
                None,
                lambda: client_queue.drain_many(262144)
            )
            t_drain_end = clock.monotonic_ns()
            consecutive_timeouts = 0
            if not batch:  # EOF signal (b"") or closed (None)
                _exit_reason = "eof_or_closed"
                break
            _diag_yield_count += 1
            _diag_yield_cumulative_bytes += len(batch)

            # TS liveness: track write gap
            now_mono = clock.monotonic()
            gap_ms = (now_mono - _ts_last_write_mono) * 1000.0
            if gap_ms > _ts_max_gap_ms:
                _ts_max_gap_ms = gap_ms
            # Stall detector: only fires on anomaly
            if gap_ms > _TS_STALL_THRESHOLD_S * 1000.0:
                _ts_stall_count += 1
                _logger.warning(
                    "TS_WRITE_STALL: gap_ms=%.0f bytes_total=%d "
                    "yields=%d stall_count=%d timeouts=%d",
                    gap_ms, _diag_yield_cumulative_bytes,
                    _diag_yield_count, _ts_stall_count, _diag_timeout_total,
                )

            # Cadence histogram (no logging, just accumulate)
            _cadence_sum_ms += gap_ms
            if gap_ms < 10:
                _cadence_buckets[0] += 1
            elif gap_ms < 30:
                _cadence_buckets[1] += 1
            elif gap_ms < 60:
                _cadence_buckets[2] += 1
            elif gap_ms < 100:
                _cadence_buckets[3] += 1
            elif gap_ms < 300:
                _cadence_buckets[4] += 1
            else:
                _cadence_buckets[5] += 1

            # Burst detection: rapid run (<10ms) followed by gap (>100ms)
            if gap_ms < 10:
                _in_rapid_run = True
            elif _in_rapid_run and gap_ms > 100:
                _burst_count += 1
                _in_rapid_run = False
            else:
                _in_rapid_run = False

            # Reservoir sampling for percentiles
            import random as _rand
            _cadence_reservoir_idx += 1
            if len(_cadence_reservoir) < _RESERVOIR_SIZE:
                _cadence_reservoir.append(gap_ms)
            else:
                j = _rand.randint(0, _cadence_reservoir_idx - 1)
                if j < _RESERVOIR_SIZE:
                    _cadence_reservoir[j] = gap_ms

            _ts_last_write_mono = now_mono

            # CORE_TRANSPORT_DIAG: HTTP yield timing
            if _DIAG_ENABLED:
                if (_diag_yield_count <= _DIAG_STARTUP_EVENTS or
                        _diag_yield_count % _DIAG_STEADY_INTERVAL == 0):
                    drain_ms = (t_drain_end - t_drain_start) / 1e6
                    wall_us = t_drain_end // 1000
                    _logger.info(
                        "CORE_YIELD_DIAG: yield_seq=%d wall_us=%d bytes=%d "
                        "cumulative_bytes=%d drain_ms=%.2f timeouts_so_far=%d "
                        "queue_bytes=%d",
                        _diag_yield_count, wall_us, len(batch),
                        _diag_yield_cumulative_bytes, drain_ms,
                        _diag_timeout_total,
                        client_queue.current_bytes,
                    )
            # INV-SLOW-CONSUMER-DISCONNECT-001: detect dead clients via write timeout.
            # yield transfers to the ASGI write path; if the client's TCP window
            # is closed the write stalls. Measure pre/post yield monotonic time.
            _t_pre_yield = clock.monotonic()
            yield batch
            _yield_elapsed = clock.monotonic() - _t_pre_yield
            if _yield_elapsed > write_timeout_s:
                _logger.warning(
                    "WRITE_TIMEOUT: yield_elapsed_s=%.1f threshold_s=%.1f "
                    "yields=%d bytes=%d client_id=%s — closing dead client connection",
                    _yield_elapsed, write_timeout_s,
                    _diag_yield_count, _diag_yield_cumulative_bytes, client_id,
                )
                _exit_reason = "write_timeout"
                break
            await asyncio.sleep(0)
        except Empty:
            consecutive_timeouts += 1
            _diag_timeout_total += 1
            if consecutive_timeouts >= max_consecutive_timeouts:
                _exit_reason = "safety_timeout_10s"
                break
            await asyncio.sleep(0.01)
            continue
        except GeneratorExit:
            _exit_reason = "generator_exit"
            break
        except asyncio.CancelledError:
            _exit_reason = "cancelled"
            break
        except RuntimeError as exc:
            if "cannot schedule new futures after shutdown" in str(exc):
                _exit_reason = "executor_shutdown"
                break
            raise

    # TS_SESSION_SUMMARY: once on disconnect, always emitted
    session_duration_s = clock.monotonic() - _ts_session_start_mono
    total_writes = sum(_cadence_buckets)
    avg_ms = (_cadence_sum_ms / total_writes) if total_writes > 0 else 0.0

    # Percentiles from reservoir
    _p50 = _p95 = _p99 = 0.0
    if _cadence_reservoir:
        _sorted = sorted(_cadence_reservoir)
        _n = len(_sorted)
        _p50 = _sorted[int(_n * 0.50)]
        _p95 = _sorted[int(min(_n * 0.95, _n - 1))]
        _p99 = _sorted[int(min(_n * 0.99, _n - 1))]

    _logger.info(
        "TS_SESSION_SUMMARY: reason=%s duration_s=%.1f bytes=%d "
        "yields=%d max_gap_ms=%.0f stalls=%d timeouts=%d",
        _exit_reason, session_duration_s, _diag_yield_cumulative_bytes,
        _diag_yield_count, _ts_max_gap_ms, _ts_stall_count,
        _diag_timeout_total,
    )
    _logger.info(
        "TS_CADENCE: avg_ms=%.1f p50=%.1f p95=%.1f p99=%.1f max=%.0f "
        "bursts=%d histogram=[0-10:%d 10-30:%d 30-60:%d 60-100:%d 100-300:%d 300+:%d]",
        avg_ms, _p50, _p95, _p99, _ts_max_gap_ms,
        _burst_count,
        _cadence_buckets[0], _cadence_buckets[1], _cadence_buckets[2],
        _cadence_buckets[3], _cadence_buckets[4], _cadence_buckets[5],
    )
    _logger.info(
        "[HTTP] GENERATOR_EXIT reason=%s yields=%d bytes=%d timeouts=%d",
        _exit_reason, _diag_yield_count, _diag_yield_cumulative_bytes,
        _diag_timeout_total,
    )

