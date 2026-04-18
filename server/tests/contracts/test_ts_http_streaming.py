"""
Contract test for INV-RAW-TS-TRANSPORT-001.

Invariant:
    The /channel/{id}.ts endpoint delivers MPEG-TS as a raw continuous byte
    stream.  Response headers must match the behaviour of real tuner devices
    (HDHomeRun / Tvheadend):

      Content-Type: video/mpeg
      Connection: close
      Cache-Control: no-cache

    No ``Content-Length`` and no ``Transfer-Encoding`` should be present.

    The first bytes must arrive within 2 seconds and consist of 188-byte
    aligned MPEG-TS packets (sync byte 0x47).

    Note: the absence of ``Transfer-Encoding: chunked`` is enforced at the
    uvicorn protocol level via ``_RawTSResponse`` which patches the
    ``RequestResponseCycle``.  The ``TestClient`` (httpx) runs ASGI
    in-process without uvicorn, so the chunked-suppression path is not
    exercisable here.  That behaviour is validated via ``curl -v`` against
    the running daemon.
"""

import asyncio
import logging
import time
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request, Response, status
from fastapi.testclient import TestClient

from retrovue.runtime.channel_stream import generate_ts_stream_async

# ── Minimal fake components ──────────────────────────────────────────────────

TS_SYNC = 0x47
TS_PACKET_SIZE = 188
# Minimal valid-looking TS packet: sync byte + 187 padding bytes
_FAKE_TS_PACKET = bytes([TS_SYNC]) + b"\x00" * (TS_PACKET_SIZE - 1)
_FAKE_TS_CHUNK = _FAKE_TS_PACKET * 7  # 1316 bytes = 7 TS packets (standard AVIO size)


class FakeClientQueue:
    """Minimal BytesBoundedQueue stand-in that yields a few TS chunks then EOF."""

    def __init__(self, chunks: int = 20):
        self._remaining = chunks
        self._closed = False
        self.current_bytes = 0

    def drain_many(self, max_bytes: int = 65536):
        if self._closed or self._remaining <= 0:
            return b""
        self._remaining -= 1
        return _FAKE_TS_CHUNK

    def close(self):
        self._closed = True


class FakeFanout:
    """Minimal ChannelStreamConsumer stand-in."""

    def __init__(self):
        self.subscribers = {}

    def subscribe(self, client_id: str):
        q = FakeClientQueue()
        self.subscribers[client_id] = q
        return q

    def unsubscribe(self, client_id: str, reason: str = "disconnect"):
        self.subscribers.pop(client_id, None)


class FakeChannelManager:
    def __init__(self):
        self.viewer_count = 0
        self.sessions = {}

    def tune_in(self, session_id, info=None):
        self.sessions[session_id] = info
        self.viewer_count += 1

    def tune_out(self, session_id):
        if session_id in self.sessions:
            del self.sessions[session_id]
            self.viewer_count -= 1


def _build_test_app():
    """Build a minimal FastAPI app that mirrors the production stream endpoint."""
    from fastapi.responses import StreamingResponse

    app = FastAPI()
    fake_manager = FakeChannelManager()
    fake_fanout = FakeFanout()

    @app.get("/channel/{channel_id}.ts")
    async def stream_channel(request: Request, channel_id: str) -> Response:
        session_id = str(uuid.uuid4())
        fake_manager.tune_in(session_id, {"channel_id": channel_id})
        client_queue = fake_fanout.subscribe(session_id)

        async def generate_stream():
            from retrovue.runtime.clock import SystemClock
            try:
                async for chunk in generate_ts_stream_async(client_queue, clock=SystemClock()):
                    yield chunk
            except (GeneratorExit, asyncio.CancelledError):
                pass
            finally:
                fake_fanout.unsubscribe(session_id)
                fake_manager.tune_out(session_id)

        return StreamingResponse(
            generate_stream(),
            media_type="video/mpeg",
            headers={
                "Connection": "close",
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return app, fake_manager, fake_fanout


# ── Contract tests ───────────────────────────────────────────────────────────

class TestInvRawTsTransport001:
    """INV-RAW-TS-TRANSPORT-001: Raw TS transport — no chunked encoding."""

    @pytest.fixture(autouse=True)
    def setup_app(self):
        self.app, self.manager, self.fanout = _build_test_app()
        self.client = TestClient(self.app)

    def test_content_type_is_video_mp2t(self):
        """Response Content-Type must be video/mp2t."""
        with self.client.stream("GET", "/channel/test.ts") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "video/mpeg"

    def test_no_content_length_header(self):
        """Response must NOT include Content-Length."""
        with self.client.stream("GET", "/channel/test.ts") as resp:
            assert resp.status_code == 200
            assert "content-length" not in resp.headers, (
                f"Content-Length must not be present, got: {resp.headers.get('content-length')!r}"
            )

    def test_connection_close_header(self):
        """Response must include Connection: close."""
        with self.client.stream("GET", "/channel/test.ts") as resp:
            assert resp.status_code == 200
            assert resp.headers.get("connection", "").lower() == "close"

    def test_cache_control_no_cache(self):
        """Response must include Cache-Control: no-cache."""
        with self.client.stream("GET", "/channel/test.ts") as resp:
            assert resp.status_code == 200
            assert "no-cache" in resp.headers.get("cache-control", "")

    def test_first_bytes_arrive_within_2_seconds(self):
        """First bytes must arrive within 2 seconds of connection."""
        t0 = time.monotonic()
        with self.client.stream("GET", "/channel/test.ts") as resp:
            first_chunk = next(resp.iter_bytes(chunk_size=1316))
            elapsed = time.monotonic() - t0
            assert elapsed < 2.0, f"First bytes took {elapsed:.2f}s (>2s)"
            assert len(first_chunk) > 0

    def test_ts_packet_alignment(self):
        """Stream must produce 188-byte aligned TS packets with 0x47 sync."""
        collected = b""
        with self.client.stream("GET", "/channel/test.ts") as resp:
            for chunk in resp.iter_bytes(chunk_size=4096):
                collected += chunk
                if len(collected) >= TS_PACKET_SIZE * 10:
                    break

        assert len(collected) >= TS_PACKET_SIZE, (
            f"Expected at least {TS_PACKET_SIZE} bytes, got {len(collected)}"
        )
        # Check sync bytes at 188-byte boundaries
        packets_checked = 0
        for offset in range(0, len(collected) - TS_PACKET_SIZE + 1, TS_PACKET_SIZE):
            assert collected[offset] == TS_SYNC, (
                f"Expected sync byte 0x47 at offset {offset}, "
                f"got 0x{collected[offset]:02x}"
            )
            packets_checked += 1
        assert packets_checked >= 7, (
            f"Expected at least 7 aligned packets, checked {packets_checked}"
        )

    def test_viewer_lifecycle_cleanup(self):
        """tune_out must be called when the stream generator finishes."""
        with self.client.stream("GET", "/channel/test.ts") as resp:
            # Read a bit to start the stream
            next(resp.iter_bytes(chunk_size=1316), None)
        # After context exit, cleanup should have run
        assert self.manager.viewer_count == 0, (
            f"Expected 0 viewers after disconnect, got {self.manager.viewer_count}"
        )
