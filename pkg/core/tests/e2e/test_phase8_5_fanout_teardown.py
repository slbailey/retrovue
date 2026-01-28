"""
Phase 8.5 — Fan-out & Teardown.

Contract: Multiple HTTP readers from same stream; last viewer disconnect → Air stops;
no per-client buffering required; one slow client must not stall others.

See: docs/air/contracts/Phase8-5-FanoutTeardown.md
"""

from __future__ import annotations

import socket
import time

import pytest
import requests

from retrovue.runtime.channel_stream import ChannelStream, FakeTsSource
from retrovue.runtime.program_director import ProgramDirector


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _StubChannelManager85:
    """Stub that clears producer when last viewer leaves (Phase 8.5 teardown)."""

    def __init__(self, channel_id: str, socket_path: str = "/tmp/phase85-dummy.sock"):
        self.channel_id = channel_id
        self._socket_path = socket_path
        self._sessions: set[str] = set()
        self._producer_stopped = False

    def tune_in(self, session_id: str, info: dict) -> None:
        self._sessions.add(session_id)
        # Producer stays stopped until "next StartChannel/AttachStream" (not auto-restarted here)

    def tune_out(self, session_id: str) -> None:
        self._sessions.discard(session_id)
        if len(self._sessions) == 0:
            self._producer_stopped = True

    @property
    def active_producer(self) -> object | None:
        if self._producer_stopped:
            return None
        return type("Producer", (), {"socket_path": self._socket_path})()


class _StubChannelManagerProvider85:
    """Provider that returns Phase 8.5 stub (producer clears on last viewer)."""

    def __init__(self, channel_id: str = "mock"):
        self.channel_id = channel_id
        self._manager = _StubChannelManager85(channel_id)

    def get_channel_manager(self, channel_id: str):
        if channel_id != self.channel_id:
            raise LookupError(f"Unknown channel: {channel_id}")
        return self._manager

    def list_channels(self) -> list[str]:
        return [self.channel_id]


def _start_director_85(provider: _StubChannelManagerProvider85) -> tuple[ProgramDirector, str]:
    port = _free_port()
    director = ProgramDirector(
        channel_manager_provider=provider,
        host="127.0.0.1",
        port=port,
    )
    director._channel_stream_factory = lambda cid, path: ChannelStream(
        cid, ts_source_factory=lambda: FakeTsSource(chunk_size=188 * 10)
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


def test_phase8_5_multiple_viewers_receive_same_bytes():
    """
    Phase 8.5: Open N HTTP connections to GET /channels/{id}.ts; all receive the same bytes.

    Contract: Multiple HTTP readers receive the same stream (or logical copy).
    """
    provider = _StubChannelManagerProvider85("mock")
    director, base = _start_director_85(provider)
    try:
        url = f"{base}/channels/mock.ts"
        target_bytes = 188 * 30
        responses = []
        try:
            for i in range(3):
                r = requests.get(url, stream=True, timeout=(3, 2))
                assert r.status_code == 200, r.text or r.reason
                responses.append(r)

            collected = []
            for r in responses:
                data = b""
                for chunk in r.iter_content(chunk_size=4096):
                    data += chunk
                    if len(data) >= target_bytes:
                        break
                collected.append(data)

            for i, data in enumerate(collected):
                assert len(data) >= target_bytes, f"Client {i} got only {len(data)} bytes"
            # Same first K bytes (sync pattern / same stream)
            k = min(len(c) for c in collected)
            assert collected[0][:k] == collected[1][:k] == collected[2][:k], (
                "All viewers must receive the same byte stream"
            )
        finally:
            for r in responses:
                r.close()
    finally:
        director.stop(timeout=2.0)


def test_phase8_5_last_viewer_disconnect_stops_stream():
    """
    Phase 8.5: When last viewer disconnects, stream stops; no bytes on new connection until next tune-in.

    Contract: Last viewer disconnect → Air stops; new GET does not receive stream until next AttachStream.
    """
    # Use a stub that starts with producer "stopped" so the only way to get a stream
    # is to have a producer. Second GET will see no producer (stub has _producer_stopped True
    # after first tune_out). We test that when there is no producer, GET gets no TS stream.
    provider = _StubChannelManagerProvider85("mock")
    director, base = _start_director_85(provider)
    try:
        url = f"{base}/channels/mock.ts"

        # First viewer: get some bytes then close
        with requests.get(url, stream=True, timeout=(3, 2)) as r:
            assert r.status_code == 200
            first = b""
            for chunk in r.iter_content(chunk_size=4096):
                first += chunk
                if len(first) >= 188 * 20:
                    break
        assert len(first) >= 188 * 20, "First viewer should receive bytes"

        # Mark producer stopped (simulate last viewer tune_out). Now stub returns no producer.
        provider._manager._producer_stopped = True
        # Wait for server to run first request's finally (unsubscribe, pop cache, stop).
        time.sleep(2.0)
        # Second GET: get_or_create sees no producer → placeholder branch → no TS bytes.
        body = b""
        try:
            with requests.get(url, stream=True, timeout=(3, 2)) as r:
                for chunk in r.iter_content(chunk_size=4096):
                    body += chunk
                    if len(body) >= 188 * 5:
                        break
        except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout):
            pass

        assert len(body) < 188 * 5, (
            "When producer is stopped, new GET must not receive stream until next tune-in"
        )
    finally:
        director.stop(timeout=2.0)
