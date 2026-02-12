"""
Regression test: reader_socket_queue per-session lifecycle.

Contract: Socket is per-session. Each new viewer session (0→1) gets a fresh AttachStream
and new socket. Disconnect triggers full teardown; reconnect gets a new session.

- Connect viewer, verify TS sync byte (0x47)
- Disconnect viewer, ensure ChannelStream stops and socket is released
- Connect viewer again, verify new AttachStream occurs and TS resumes (no timeout)
"""

from __future__ import annotations

import queue
import socket
import threading
import time

import pytest
import requests

from retrovue.runtime.program_director import ProgramDirector


CHANNEL_ID = "reader-queue-test"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _ProducerWithReaderQueue:
    """Fake producer that provides one socket per session via reader_socket_queue."""

    def __init__(self, channel_id: str):
        self.channel_id = channel_id
        self.reader_socket_queue: queue.Queue[socket.socket] = queue.Queue()
        self._writer_sock: socket.socket | None = None
        self._stop_event = threading.Event()
        self._writer_thread: threading.Thread | None = None

    def _writer_loop(self) -> None:
        """Write TS packets (0x47 sync + padding) to the socket until stopped."""
        while not self._stop_event.wait(timeout=0.02):
            if self._writer_sock:
                try:
                    chunk = b"\x47" + b"\x00" * (188 * 10 - 1)  # One TS packet + more
                    self._writer_sock.sendall(chunk)
                except (BrokenPipeError, OSError):
                    break

    def start(self) -> None:
        """Create socket pair, put read end in queue, start writer thread."""
        a, b = socket.socketpair()
        self.reader_socket_queue.put(a)
        self._writer_sock = b
        self._stop_event.clear()
        self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer_thread.start()

    def stop(self) -> None:
        """Stop writer, close sockets, drain queue."""
        self._stop_event.set()
        if self._writer_thread:
            self._writer_thread.join(timeout=0.5)
            self._writer_thread = None
        if self._writer_sock:
            try:
                self._writer_sock.close()
            except Exception:
                pass
            self._writer_sock = None
        while not self.reader_socket_queue.empty():
            try:
                s = self.reader_socket_queue.get_nowait()
                try:
                    s.close()
                except Exception:
                    pass
            except queue.Empty:
                break


class _ManagerWithReaderQueue:
    """Stub manager with producer that has reader_socket_queue."""

    def __init__(self, channel_id: str, producer: _ProducerWithReaderQueue):
        self.channel_id = channel_id
        self._producer = producer
        self._sessions: set[str] = set()

    def tune_in(self, session_id: str, info: dict) -> None:
        self._sessions.add(session_id)
        if len(self._sessions) == 1:
            self._producer.start()

    def tune_out(self, session_id: str) -> None:
        self._sessions.discard(session_id)

    @property
    def active_producer(self) -> _ProducerWithReaderQueue | None:
        if len(self._sessions) == 0:
            return None
        return self._producer


class _ProviderWithReaderQueue:
    """Provider that creates fresh manager+producer per session (after stop_channel)."""

    def __init__(self, channel_id: str = CHANNEL_ID):
        self.channel_id = channel_id
        self._manager: _ManagerWithReaderQueue | None = None
        self._producer: _ProducerWithReaderQueue | None = None

    def get_channel_manager(self, channel_id: str) -> _ManagerWithReaderQueue:
        if channel_id != self.channel_id:
            raise LookupError(f"Unknown channel: {channel_id}")
        if self._manager is None:
            self._producer = _ProducerWithReaderQueue(channel_id)
            self._manager = _ManagerWithReaderQueue(channel_id, self._producer)
        return self._manager

    def list_channels(self) -> list[str]:
        return [self.channel_id]

    def stop_channel(self, channel_id: str) -> None:
        if channel_id != self.channel_id:
            return
        if self._producer:
            self._producer.stop()
            self._producer = None
        self._manager = None


def _start_director(provider: _ProviderWithReaderQueue) -> tuple[ProgramDirector, str]:
    port = _free_port()
    director = ProgramDirector(
        channel_manager_provider=provider,
        host="127.0.0.1",
        port=port,
    )
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


def _read_ts_bytes(url: str, min_bytes: int = 188 * 20, timeout: float = 5.0) -> bytes:
    """Read at least min_bytes from stream, return data."""
    data = b""
    with requests.get(url, stream=True, timeout=(3, timeout)) as r:
        assert r.status_code == 200, r.text or r.reason
        for chunk in r.iter_content(chunk_size=4096):
            data += chunk
            if len(data) >= min_bytes:
                break
    return data


def test_reader_socket_queue_connect_disconnect_reconnect() -> None:
    """
    Per-session lifecycle: connect → verify TS sync → disconnect → reconnect → TS resumes.

    Regression for: RuntimeError: Timed out waiting for socket from reader_socket_queue
    """
    provider = _ProviderWithReaderQueue()
    director, base = _start_director(provider)
    url = f"{base}/channel/{CHANNEL_ID}.ts"

    try:
        # 1) First connect: verify TS sync byte
        data1 = _read_ts_bytes(url)
        assert len(data1) >= 188 * 20, f"First session: expected TS bytes, got {len(data1)}"
        assert data1[0] == 0x47, (
            f"First session: expected 0x47 sync byte, got 0x{data1[0]:02x}"
        )

        # 2) Disconnect: ChannelStream stops, socket released, channel torn down
        # (Connection already closed by exiting _read_ts_bytes context)
        # Allow cleanup to run (last viewer → stop_channel → producer stopped)
        time.sleep(0.5)

        # 3) Second connect: new AttachStream, new socket, TS resumes (no timeout)
        data2 = _read_ts_bytes(url)
        assert len(data2) >= 188 * 20, (
            f"Second session: expected TS bytes (no timeout), got {len(data2)}"
        )
        assert data2[0] == 0x47, (
            f"Second session: expected 0x47 sync byte, got 0x{data2[0]:02x}"
        )
    finally:
        director.stop(timeout=2.0)
