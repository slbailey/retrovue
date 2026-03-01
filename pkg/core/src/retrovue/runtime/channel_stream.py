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
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Any, Callable, Literal, Optional, Protocol

from .ts_ring_buffer import DEFAULT_RING_BUFFER_MAX_BYTES, TsRingBuffer

# Config from env (bytes-based client buffer; default ~2–4 s at ~2.5 Mbit/s TS)
def _client_buffer_bytes() -> int:
    val = os.environ.get("HTTP_CLIENT_BUFFER_BYTES")
    if val is not None:
        try:
            return max(64 * 1024, int(val))
        except ValueError:
            pass
    return 2_000_000


def _ring_buffer_bytes() -> int:
    val = os.environ.get("HTTP_RING_BUFFER_BYTES")
    if val is not None:
        try:
            return max(64 * 1024, int(val))
        except ValueError:
            pass
    return DEFAULT_RING_BUFFER_MAX_BYTES


class BytesBoundedQueue:
    """
    Thread-safe queue with a byte-size cap. When full, oldest chunks are dropped.
    Used for per-client TS buffers so backpressure is per-client only.
    """

    def __init__(self, max_bytes: int) -> None:
        self._max_bytes = max(64 * 1024, max_bytes)
        self._lock = threading.Lock()
        self._chunks: list[bytes] = []
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
                old = self._chunks.pop(0)
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
            chunk = self._chunks.pop(0)
            self._current_bytes -= len(chunk)
            return chunk

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

_logger = logging.getLogger(__name__)

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
RECV_GAP_WARN_THRESHOLD_MS: int = 40  # Fixed threshold - do not "move the bar"
RECV_GAP_WARN_COUNT: int = 10  # Minimum gaps before warning (prevents noise)

# Fan-out: if a client cannot accept a chunk within this timeout, it is evicted.
# Keeps backpressure bounded while tolerating brief network/CPU stalls.
SLOW_CLIENT_PUT_TIMEOUT_S: float = 3.0

# Backpressure when ring buffer exceeds this bytes: drop oldest (Policy A) or disconnect client (Policy B).
BACKPRESSURE_SLOW_THRESHOLD_S: float = 5.0
# Policy: "drop_oldest" = drop oldest TS from buffer and continue; "disconnect" = close HTTP client only.
BackpressurePolicy = Literal["drop_oldest", "disconnect"]
DEFAULT_BACKPRESSURE_POLICY: BackpressurePolicy = "drop_oldest"

# Upstream reader select timeout: short so we react quickly; 50 ms max.
UPSTREAM_POLL_TIMEOUT_S: float = 0.05
# Log WARNING when upstream loop iteration exceeds this (indicates jitter/blocking).
UPSTREAM_LOOP_SPIKE_MS: float = 50.0

# Throttle BACKPRESSURE logs per client (avoid flood when one client is consistently slow).
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

    def get_socket(self) -> Optional[socket.socket]:
        return None


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
        ts_source_factory: Callable[[], TsSource] | None = None,
        hls_manager: Any | None = None,
        *,
        ring_buffer_max_bytes: int | None = None,
        client_buffer_max_bytes: int | None = None,
        backpressure_policy: BackpressurePolicy = DEFAULT_BACKPRESSURE_POLICY,
    ):
        """
        Initialize ChannelStream for a channel.

        Args:
            channel_id: Channel identifier
            socket_path: UDS socket path (if None, uses ts_source_factory)
            ts_source_factory: Factory for creating TS source (for tests)
            hls_manager: Optional HLSManager to tee TS data for HLS output
            ring_buffer_max_bytes: Max ring buffer size (default: HTTP_RING_BUFFER_BYTES or 8MB)
            client_buffer_max_bytes: Per-client queue byte cap (default: HTTP_CLIENT_BUFFER_BYTES or 2MB)
            backpressure_policy: "drop_oldest" (preferred for live) or "disconnect"
        """
        self.channel_id = channel_id
        self.socket_path = Path(socket_path) if socket_path else None
        self.ts_source_factory = ts_source_factory
        self.hls_manager = hls_manager
        self._backpressure_policy = backpressure_policy
        self._client_buffer_max_bytes = (
            client_buffer_max_bytes
            if client_buffer_max_bytes is not None
            else _client_buffer_bytes()
        )
        ring_bytes = (
            ring_buffer_max_bytes
            if ring_buffer_max_bytes is not None
            else _ring_buffer_bytes()
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
        self._reconnect_delays = [1.0, 2.0, 5.0, 10.0]
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

        # Only log spike when truly slow: > 3× poll timeout, or did read and > 50 ms
        spike_threshold_long_ms = 3 * (UPSTREAM_POLL_TIMEOUT_S * 1000)
        while not self._stop_event.is_set():
            t_start = time.monotonic_ns()
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
                        t_after_select = time.monotonic_ns()
                        if not r:
                            continue
                    except (OSError, ValueError):
                        continue

                # Re-check after select: stop() may have set ts_source to None during shutdown
                if not self.ts_source:
                    break
                chunk = self.ts_source.read(chunk_size)
                t_after_recv = time.monotonic_ns()
                bytes_read_this_iter = len(chunk)
                if not chunk:
                    break
                self._ring_buffer.put(chunk)
                t_after_put = time.monotonic_ns()
            except IOError as e:
                self._logger.warning(
                    "[HTTP] UPSTREAM_DISCONNECTED reason=read_error error=%s",
                    e,
                )
                break
            finally:
                duration_ms = (time.monotonic_ns() - t_start) / 1e6
                self._logger.debug(
                    "[HTTP] UPSTREAM_LOOP channel=%s loop_duration_ms=%.2f",
                    self.channel_id, duration_ms,
                )
                is_spike = duration_ms > spike_threshold_long_ms

                if is_spike:
                    select_ms = (t_after_select - t_start) / 1e6
                    recv_ms = (t_after_recv - t_after_select) / 1e6
                    put_ms = (t_after_put - t_after_recv) / 1e6
                    if self._stop_event.is_set():
                        # Teardown drain: socket closing causes slow I/O — expected, harmless
                        self._logger.info(
                            "[HTTP] UPSTREAM_LOOP channel=%s loop_duration_ms=%.2f (teardown drain) select_ms=%.2f recv_ms=%.2f put_ms=%.2f",
                            self.channel_id,
                            duration_ms,
                            select_ms,
                            recv_ms,
                            put_ms,
                        )
                    else:
                        self._logger.warning(
                            "[HTTP] UPSTREAM_LOOP channel=%s loop_duration_ms=%.2f (spike >%.0fms long-threshold) select_ms=%.2f recv_ms=%.2f put_ms=%.2f",
                            self.channel_id,
                            duration_ms,
                            spike_threshold_long_ms,
                            select_ms,
                            recv_ms,
                            put_ms,
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
        while not self._stop_event.is_set():
            chunk = self._ring_buffer.get(timeout=UPSTREAM_POLL_TIMEOUT_S)
            if chunk is None:
                continue
            if self.hls_manager is not None:
                try:
                    self.hls_manager.feed(self.channel_id, chunk)
                except Exception:
                    pass
            with self.subscribers_lock:
                subscribers_snapshot = list(self.subscribers.items())
            # With 0 subscribers we still consumed one chunk (drain); nothing to put.
            to_remove: list[str] = []
            for client_id, client_queue in subscribers_snapshot:
                had_eviction = client_queue.put_nowait(chunk)
                if had_eviction:
                    now = time.monotonic()
                    do_log = False
                    with self._backpressure_log_lock:
                        last = self._backpressure_log_last.get(client_id, 0.0)
                        if now - last >= BACKPRESSURE_LOG_INTERVAL_S:
                            self._backpressure_log_last[client_id] = now
                            do_log = True
                    if do_log:
                        qb = client_queue.current_bytes
                        qc = client_queue.current_chunk_count
                        # Optional: ~2.5 Mbit/s TS -> ms ≈ bytes * 8 / 2.5e6 * 1000
                        est_ms = int(qb * 8 / 2_500_000 * 1000) if qb else 0
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
                    try:
                        q.put_nowait(b"")
                    except Full:
                        pass
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
            _AUDIT_T0 = time.monotonic_ns()
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

        with self.subscribers_lock:
            self.subscribers[client_id] = queue
            subscriber_count = len(self.subscribers)

        self._logger.info(
            "[HTTP] CLIENT_CONNECTED id=%s channel=%s subscribers=%d",
            client_id, self.channel_id, subscriber_count,
        )

        if not self.reader_thread or not self.reader_thread.is_alive():
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
            self._logger.info(
                "[HTTP] CLIENT_DISCONNECTED id=%s reason=%s channel=%s subscribers=%d",
                client_id, reason, self.channel_id, subscriber_count,
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
        except RuntimeError as exc:
            if "cannot schedule new futures after shutdown" in str(exc):
                break
            raise

