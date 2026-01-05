"""
Channel TS Stream Consumer (Phase 9).

Per-channel Unix Domain Socket (UDS) reader that consumes TS streams from Air
and fans out to multiple HTTP clients.

Responsibilities:
- Connect to Air UDS socket per channel
- Read TS data in a loop
- Fan-out TS chunks to all active HTTP clients
- Handle Air disconnect/reconnect transparently
- Support test mode with injectable fake TS source
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Callable, Protocol

_logger = logging.getLogger(__name__)


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
                _logger.warning("UDS socket closed by Air (EOF)")
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
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        _logger.info("Closed UDS socket: %s", self.socket_path)

    @property
    def is_connected(self) -> bool:
        """Check if connected to UDS."""
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

        self._logger = logging.getLogger(f"{__name__}.{channel_id}")

    def get_socket_path(self) -> Path:
        """Get the UDS socket path for this channel."""
        if self.socket_path:
            return self.socket_path
        # Default path: /var/run/retrovue/air/channel_{channel_id}.sock
        return Path(f"/var/run/retrovue/air/channel_{self.channel_id}.sock")

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
                # Fake source doesn't need connect
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
        self._logger.info("ChannelStream reader loop started for channel %s", self.channel_id)
        chunk_size = 188 * 10  # Read 10 TS packets at a time (188 bytes each)

        while not self._stop_event.is_set():
            # Connect if needed
            if not self.ts_source:
                if not self._connect_with_backoff():
                    if self._stop_event.is_set():
                        break
                    # Failed to connect, wait before retrying
                    time.sleep(1.0)
                    continue

            # Check if source is connected (for UDS)
            if isinstance(self.ts_source, UdsTsSource) and not self.ts_source.is_connected:
                self._logger.warning(
                    "UDS source disconnected, attempting reconnect for channel %s", self.channel_id
                )
                if not self._connect_with_backoff():
                    if self._stop_event.is_set():
                        break
                    time.sleep(1.0)
                    continue

            # Read TS chunk
            try:
                chunk = self.ts_source.read(chunk_size)
                if not chunk:
                    # EOF or disconnect
                    if isinstance(self.ts_source, UdsTsSource):
                        self._logger.warning(
                            "TS source closed, attempting reconnect for channel %s", self.channel_id
                        )
                        self.ts_source.close()
                        self.ts_source = None
                        continue
                    else:
                        # Fake source EOF, stop
                        break
            except IOError as e:
                self._logger.error("TS read error for channel %s: %s", self.channel_id, e)
                if isinstance(self.ts_source, UdsTsSource):
                    self.ts_source.close()
                    self.ts_source = None
                time.sleep(1.0)
                continue

            # Fan-out to all subscribers
            with self.subscribers_lock:
                subscribers_to_remove = []
                for client_id, queue in self.subscribers.items():
                    try:
                        # Non-blocking put; if queue is full, drop this client
                        queue.put_nowait(chunk)
                    except Exception as e:
                        self._logger.warning(
                            "Failed to deliver chunk to client %s: %s", client_id, e
                        )
                        subscribers_to_remove.append(client_id)

                # Remove failed subscribers
                for client_id in subscribers_to_remove:
                    self.subscribers.pop(client_id, None)

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
        if self.reader_thread is not None and self.reader_thread.is_alive():
            return  # Already running

        self._stop_event.clear()
        self._stopped = False
        self.reader_thread = threading.Thread(
            target=self._reader_loop, name=f"ChannelStream-{self.channel_id}", daemon=True
        )
        self.reader_thread.start()
        self._logger.info("ChannelStream started for channel %s", self.channel_id)

    def stop(self) -> None:
        """Stop the UDS reader thread and clean up."""
        if self._stopped:
            return

        self._logger.info("Stopping ChannelStream for channel %s", self.channel_id)
        self._stop_event.set()

        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=5.0)
            if self.reader_thread.is_alive():
                self._logger.warning("ChannelStream reader thread did not stop cleanly for channel %s", self.channel_id)

        if self.ts_source:
            try:
                self.ts_source.close()
            except Exception:
                pass
            self.ts_source = None

        # Clear all subscribers and signal EOF
        with self.subscribers_lock:
            for queue in self.subscribers.values():
                try:
                    # Signal EOF to remaining clients
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
            "HTTP client %s connected to channel %s (total subscribers: %d)",
            client_id,
            self.channel_id,
            subscriber_count,
        )

        # Start reader if not already running
        if not self.reader_thread or not self.reader_thread.is_alive():
            self.start()

        return queue

    def unsubscribe(self, client_id: str) -> None:
        """Unsubscribe an HTTP client."""
        with self.subscribers_lock:
            removed = self.subscribers.pop(client_id, None)

        if removed is not None:
            subscriber_count = len(self.subscribers)
            self._logger.info(
                "HTTP client %s disconnected from channel %s (remaining subscribers: %d)",
                client_id,
                self.channel_id,
                subscriber_count,
            )

            # If no more subscribers and stopped, cleanup
            if subscriber_count == 0 and self._stopped:
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
    while True:
        try:
            chunk = client_queue.get(timeout=1.0)
            if not chunk:  # EOF signal
                break
            yield chunk
        except Empty:
            # Timeout - continue waiting (allows graceful shutdown on disconnect)
            # FastAPI will close connection if client disconnects
            continue
        except GeneratorExit:
            # Client disconnected
            break

