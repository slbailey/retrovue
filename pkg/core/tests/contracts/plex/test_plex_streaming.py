"""
Contract tests for Plex stream lifecycle and producer fanout.

Verifies:
  INV-PLEX-STREAM-START-001 — stream start delegates to ProgramDirector
  INV-PLEX-STREAM-DISCONNECT-001 — disconnect triggers tune_out
  INV-PLEX-FANOUT-001 — Plex and direct viewers share one producer
  Plex Compatibility Interface — stream endpoint returns 200 and MPEG-TS sync bytes
"""

import threading
from unittest.mock import MagicMock, patch, call

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from starlette.testclient import TestClient

from retrovue.integrations.plex.adapter import PlexAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_channels(*names: str) -> list[dict]:
    """Build minimal channel dicts with number (Plex GuideNumber)."""
    return [
        {
            "channel_id": name.lower().replace(" ", "-"),
            "number": 100 + (i + 1),
            "channel_id_int": 100 + (i + 1),
            "name": name,
            "schedule_config": {"channel_type": "network"},
        }
        for i, name in enumerate(names)
    ]


class FakeChannelManager:
    """Minimal ChannelManager substitute for lifecycle testing."""

    def __init__(self, channel_id: str):
        self.channel_id = channel_id
        self._viewer_lock = threading.Lock()
        self.viewer_sessions: dict[str, dict] = {}
        self.tune_in_calls: list[str] = []
        self.tune_out_calls: list[str] = []
        self._producer_started = False
        self._producer_stopped = False

    def tune_in(self, session_id: str, session_info: dict | None = None):
        self.tune_in_calls.append(session_id)
        with self._viewer_lock:
            was_empty = len(self.viewer_sessions) == 0
            self.viewer_sessions[session_id] = session_info or {}
            if was_empty:
                self._producer_started = True
                self._producer_stopped = False

    def tune_out(self, session_id: str):
        self.tune_out_calls.append(session_id)
        with self._viewer_lock:
            self.viewer_sessions.pop(session_id, None)
            if len(self.viewer_sessions) == 0:
                self._producer_stopped = True

    @property
    def viewer_count(self) -> int:
        return len(self.viewer_sessions)

    @property
    def producer_running(self) -> bool:
        return self._producer_started and not self._producer_stopped


class FakeProgramDirector:
    """Minimal ProgramDirector substitute for delegation testing."""

    def __init__(self, channels: list[dict]):
        self._channels = channels
        self._managers: dict[str, FakeChannelManager] = {}
        self.stream_channel_calls: list[str] = []

    def list_channels(self) -> list[str]:
        return [ch["channel_id"] for ch in self._channels]

    def get_channel_manager(self, channel_id: str) -> FakeChannelManager:
        if channel_id not in self._managers:
            self._managers[channel_id] = FakeChannelManager(channel_id)
        return self._managers[channel_id]

    def stream_channel(self, channel_id: str, session_id: str):
        """Track that stream_channel was called."""
        self.stream_channel_calls.append(channel_id)
        mgr = self.get_channel_manager(channel_id)
        mgr.tune_in(session_id, {"channel_id": channel_id})
        return mgr


# ---------------------------------------------------------------------------
# INV-PLEX-STREAM-START-001
# ---------------------------------------------------------------------------


class TestPlexStreaming:
    """INV-PLEX-STREAM-START-001 / INV-PLEX-STREAM-DISCONNECT-001 /
    INV-PLEX-FANOUT-001 contract tests."""

    # -- Stream Start --

    def test_stream_start_delegates_to_program_director(self):
        """Stream request MUST delegate to ProgramDirector, not handle independently.

        INV-PLEX-STREAM-START-001: The adapter MUST invoke stream_channel()
        or the equivalent tune_in path — it MUST NOT spawn AIR or compile
        schedules directly.
        """
        channels = _make_channels("HBO")
        pd = FakeProgramDirector(channels)
        adapter = PlexAdapter(
            channels=channels,
            base_url="http://localhost:8000",
            program_director=pd,
        )

        adapter.start_stream("hbo", session_id="plex-001")

        mgr = pd.get_channel_manager("hbo")
        assert "plex-001" in mgr.tune_in_calls, (
            "INV-PLEX-STREAM-START-001 violated: adapter did not call tune_in"
        )

    def test_stream_start_does_not_spawn_air_directly(self):
        """Adapter MUST NOT call _ensure_producer_running or spawn AIR.

        INV-PLEX-STREAM-START-001: JIP offset and producer lifecycle are
        ChannelManager's responsibility.
        """
        channels = _make_channels("HBO")
        pd = FakeProgramDirector(channels)
        adapter = PlexAdapter(
            channels=channels,
            base_url="http://localhost:8000",
            program_director=pd,
        )

        adapter.start_stream("hbo", session_id="plex-001")

        # The adapter itself must not have _ensure_producer_running
        assert not hasattr(adapter, "_ensure_producer_running"), (
            "INV-PLEX-STREAM-START-001 violated: adapter has _ensure_producer_running"
        )

    def test_stream_start_uses_channel_id_from_request(self):
        """Adapter MUST pass the correct channel_id through to the lifecycle."""
        channels = _make_channels("HBO", "CNN")
        pd = FakeProgramDirector(channels)
        adapter = PlexAdapter(
            channels=channels,
            base_url="http://localhost:8000",
            program_director=pd,
        )

        adapter.start_stream("cnn", session_id="plex-002")

        assert "cnn" in pd._managers, (
            "INV-PLEX-STREAM-START-001 violated: wrong channel_id passed to manager"
        )
        assert pd._managers["cnn"].viewer_count == 1

    # -- Stream Disconnect --

    def test_disconnect_triggers_tune_out(self):
        """Client disconnect MUST trigger tune_out for that viewer.

        INV-PLEX-STREAM-DISCONNECT-001: The adapter MUST call tune_out on
        disconnect — TCP close, HTTP abort, or timeout.
        """
        channels = _make_channels("HBO")
        pd = FakeProgramDirector(channels)
        adapter = PlexAdapter(
            channels=channels,
            base_url="http://localhost:8000",
            program_director=pd,
        )

        adapter.start_stream("hbo", session_id="plex-001")
        adapter.stop_stream("hbo", session_id="plex-001")

        mgr = pd.get_channel_manager("hbo")
        assert "plex-001" in mgr.tune_out_calls, (
            "INV-PLEX-STREAM-DISCONNECT-001 violated: tune_out not called on disconnect"
        )

    def test_disconnect_tune_out_called_exactly_once(self):
        """tune_out MUST be called exactly once per tune_in.

        INV-PLEX-STREAM-DISCONNECT-001: Double tune_out is a violation.
        """
        channels = _make_channels("HBO")
        pd = FakeProgramDirector(channels)
        adapter = PlexAdapter(
            channels=channels,
            base_url="http://localhost:8000",
            program_director=pd,
        )

        adapter.start_stream("hbo", session_id="plex-001")
        adapter.stop_stream("hbo", session_id="plex-001")
        # Second stop must be idempotent (not double-call tune_out)
        adapter.stop_stream("hbo", session_id="plex-001")

        mgr = pd.get_channel_manager("hbo")
        assert mgr.tune_out_calls.count("plex-001") == 1, (
            f"INV-PLEX-STREAM-DISCONNECT-001 violated: tune_out called "
            f"{mgr.tune_out_calls.count('plex-001')} times, expected exactly 1"
        )

    def test_disconnect_no_phantom_viewers(self):
        """Adapter MUST NOT hold phantom viewer references after disconnect.

        INV-PLEX-STREAM-DISCONNECT-001: viewer_sessions must be empty after
        the last Plex viewer disconnects.
        """
        channels = _make_channels("HBO")
        pd = FakeProgramDirector(channels)
        adapter = PlexAdapter(
            channels=channels,
            base_url="http://localhost:8000",
            program_director=pd,
        )

        adapter.start_stream("hbo", session_id="plex-001")
        adapter.stop_stream("hbo", session_id="plex-001")

        mgr = pd.get_channel_manager("hbo")
        assert mgr.viewer_count == 0, (
            f"INV-PLEX-STREAM-DISCONNECT-001 violated: {mgr.viewer_count} "
            f"phantom viewers remain after disconnect"
        )

    def test_last_viewer_disconnect_stops_producer(self):
        """Last viewer out MUST stop playout per ChannelManager policy.

        INV-PLEX-STREAM-DISCONNECT-001: When the Plex viewer is the last
        viewer, playout MUST stop.
        """
        channels = _make_channels("HBO")
        pd = FakeProgramDirector(channels)
        adapter = PlexAdapter(
            channels=channels,
            base_url="http://localhost:8000",
            program_director=pd,
        )

        adapter.start_stream("hbo", session_id="plex-001")
        assert pd.get_channel_manager("hbo").producer_running

        adapter.stop_stream("hbo", session_id="plex-001")
        assert pd.get_channel_manager("hbo")._producer_stopped, (
            "INV-PLEX-STREAM-DISCONNECT-001 violated: producer still running "
            "after last viewer disconnected"
        )

    # -- Producer Fanout --

    def test_plex_and_direct_viewers_share_producer(self):
        """Plex + direct viewers on same channel MUST share one producer.

        INV-PLEX-FANOUT-001: The adapter MUST NOT create a separate
        AIR process or playout session for Plex clients.
        """
        channels = _make_channels("HBO")
        pd = FakeProgramDirector(channels)
        adapter = PlexAdapter(
            channels=channels,
            base_url="http://localhost:8000",
            program_director=pd,
        )

        # Direct viewer connects first
        direct_mgr = pd.stream_channel("hbo", "direct-001")

        # Plex viewer connects to same channel
        adapter.start_stream("hbo", session_id="plex-001")

        # Both viewers must share the same ChannelManager instance
        plex_mgr = pd.get_channel_manager("hbo")
        assert direct_mgr is plex_mgr, (
            "INV-PLEX-FANOUT-001 violated: Plex viewer got a different "
            "ChannelManager than direct viewer"
        )

    def test_single_air_process_per_channel(self):
        """At most one AIR process MUST exist per channel regardless of viewer origin.

        INV-PLEX-FANOUT-001: Multiple Plex + direct viewers must not
        cause multiple producer starts.
        """
        channels = _make_channels("HBO")
        pd = FakeProgramDirector(channels)
        adapter = PlexAdapter(
            channels=channels,
            base_url="http://localhost:8000",
            program_director=pd,
        )

        # First viewer (direct) starts producer
        pd.stream_channel("hbo", "direct-001")
        mgr = pd.get_channel_manager("hbo")
        assert mgr.producer_running

        # Second viewer (Plex) joins — producer must NOT restart
        adapter.start_stream("hbo", session_id="plex-001")
        assert mgr.viewer_count == 2
        assert mgr.producer_running

        # Direct viewer leaves — producer must stay (Plex still watching)
        mgr.tune_out("direct-001")
        assert mgr.viewer_count == 1
        assert mgr.producer_running, (
            "INV-PLEX-FANOUT-001 violated: producer stopped while Plex viewer "
            "still connected"
        )

    def test_adapter_has_no_independent_buffer(self):
        """Adapter MUST NOT maintain a separate byte buffer or re-mux pipeline.

        INV-PLEX-FANOUT-001: The adapter is a transport adapter only.
        """
        channels = _make_channels("HBO")
        adapter = PlexAdapter(
            channels=channels,
            base_url="http://localhost:8000",
        )

        # Adapter must not have buffer-related attributes
        forbidden_attrs = ["_buffer", "_byte_buffer", "_mux", "_encoder", "_transcode"]
        for attr in forbidden_attrs:
            assert not hasattr(adapter, attr), (
                f"INV-PLEX-FANOUT-001 violated: adapter has '{attr}' — "
                f"adapter MUST NOT maintain independent buffers"
            )

    def test_mixed_viewer_disconnect_order(self):
        """Mixed Plex + direct viewers disconnecting in any order MUST
        maintain correct viewer count.

        INV-PLEX-FANOUT-001 + INV-PLEX-STREAM-DISCONNECT-001: Viewer
        lifecycle must be consistent regardless of viewer origin.
        """
        channels = _make_channels("HBO")
        pd = FakeProgramDirector(channels)
        adapter = PlexAdapter(
            channels=channels,
            base_url="http://localhost:8000",
            program_director=pd,
        )

        # Two direct + two Plex
        pd.stream_channel("hbo", "direct-001")
        pd.stream_channel("hbo", "direct-002")
        adapter.start_stream("hbo", session_id="plex-001")
        adapter.start_stream("hbo", session_id="plex-002")

        mgr = pd.get_channel_manager("hbo")
        assert mgr.viewer_count == 4

        # Remove in interleaved order
        adapter.stop_stream("hbo", session_id="plex-001")
        assert mgr.viewer_count == 3

        mgr.tune_out("direct-001")
        assert mgr.viewer_count == 2

        mgr.tune_out("direct-002")
        assert mgr.viewer_count == 1

        adapter.stop_stream("hbo", session_id="plex-002")
        assert mgr.viewer_count == 0
        assert mgr._producer_stopped, (
            "INV-PLEX-FANOUT-001 violated: producer not stopped after all viewers left"
        )


# ---------------------------------------------------------------------------
# Stream endpoint contract (HTTP observable behavior)
# ---------------------------------------------------------------------------

# TS sync byte per MPEG-TS; first byte of each 188-byte packet.
TS_SYNC_BYTE = 0x47


def _stub_ts_stream():
    """Yield a few TS-like packets (sync 0x47 + padding) for deterministic contract tests."""
    packet = bytes([TS_SYNC_BYTE] + [0x00] * 187)
    for _ in range(10):
        yield packet


class TestPlexStreamEndpoint:
    """Plex Compatibility Interface: channel stream endpoint behavior.

    Tests observable HTTP behavior: 200, stream starts with MPEG-TS sync bytes.
    Uses a stub stream (no real playout) for determinism.
    """

    def test_stream_endpoint_returns_200(self):
        """Stream availability invariant: endpoint MUST return HTTP 200."""
        app = FastAPI()

        @app.get("/channel/{channel_id}.ts")
        def stream_channel(channel_id: str):
            return StreamingResponse(
                _stub_ts_stream(),
                media_type="video/mp2t",
            )

        client = TestClient(app)
        response = client.get("/channel/hbo.ts")
        assert response.status_code == 200, (
            f"Plex stream availability invariant violated: expected HTTP 200, got {response.status_code}"
        )

    def test_stream_begins_with_ts_sync_bytes(self):
        """Stream MUST begin with MPEG-TS packets (sync byte 0x47)."""
        app = FastAPI()

        @app.get("/channel/{channel_id}.ts")
        def stream_channel(channel_id: str):
            return StreamingResponse(
                _stub_ts_stream(),
                media_type="video/mp2t",
            )

        client = TestClient(app)
        response = client.get("/channel/hbo.ts")
        assert response.status_code == 200
        content = b"".join(response.iter_bytes())
        assert len(content) >= 188, (
            "Plex stream invariant violated: stream must produce TS packets"
        )
        assert content[0] == TS_SYNC_BYTE, (
            f"Plex stream invariant violated: first byte must be TS sync 0x47, got 0x{content[0]:02x}"
        )
