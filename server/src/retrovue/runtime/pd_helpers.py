"""Helper classes extracted from program_director.py.

INV-PLAYOUT-MODULE-EXTRACTION-001: These classes are importable from this
dedicated module. Backward-compatible re-exports exist in program_director.py.
"""

from __future__ import annotations

import asyncio
import logging
import re as _re
import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Protocol

from fastapi import Response

from retrovue.runtime.channel_stream import generate_ts_stream_async
from retrovue.runtime.clock import AuthoritativeClock


class _RawTSResponse(Response):
    """ASGI response that streams raw MPEG-TS without chunked encoding.

    INV-RAW-TS-TRANSPORT-001: Sends ``Connection: close`` with no
    ``Content-Length`` and no ``Transfer-Encoding``.  Body length is
    determined by connection EOF, matching HDHomeRun / Tvheadend behaviour.

    Overrides :meth:`Response.__call__` to write ASGI messages directly.
    Disables uvicorn's automatic chunked framing by setting
    ``chunked_encoding = False`` on the protocol's request-response cycle
    before the first body write.
    """

    def __init__(
        self,
        client_queue,
        *,
        cleanup_fn: Callable,
        disconnect_monitor: Callable,
        logger: logging.Logger,
        clock: AuthoritativeClock,
    ) -> None:
        # Minimal init — avoid Response.__init__ which sets body/Content-Length
        # that conflicts with raw streaming.  Set attributes that FastAPI
        # middleware expects.
        self.status_code = 200
        self.background = None
        self.body = b""
        self.media_type = None
        self._client_queue = client_queue
        self._cleanup_fn = cleanup_fn
        self._disconnect_monitor = disconnect_monitor
        self._logger = logger
        self._clock = clock

    async def __call__(self, scope, receive, send) -> None:
        # ── Disable uvicorn's chunked framing ────────────────────────────
        # Uvicorn's RequestResponseCycle writes headers (including
        # Transfer-Encoding) during http.response.start.  Setting
        # chunked_encoding = False BEFORE the start message prevents
        # uvicorn from injecting Transfer-Encoding: chunked.
        #
        # FastAPI middleware wraps ``send`` in closures.  Walk the
        # closure chain to find the underlying RequestResponseCycle.
        def _find_cycle(fn, depth=0):
            if depth > 10:
                return None
            # Direct bound method
            obj = getattr(fn, "__self__", None)
            if obj is not None and hasattr(obj, "chunked_encoding"):
                return obj
            # Walk __wrapped__ chain (functools.wraps)
            wrapped = getattr(fn, "__wrapped__", None)
            if wrapped is not None:
                found = _find_cycle(wrapped, depth + 1)
                if found is not None:
                    return found
            # Starlette/FastAPI middleware closes over ``send``
            # in the local scope.  Inspect closure cells.
            closure = getattr(fn, "__closure__", None)
            if closure:
                for cell in closure:
                    try:
                        val = cell.cell_contents
                    except ValueError:
                        continue
                    if hasattr(val, "chunked_encoding"):
                        return val
                    if callable(val) and val is not fn:
                        found = _find_cycle(val, depth + 1)
                        if found is not None:
                            return found
            return None

        cycle = _find_cycle(send)
        if cycle is not None:
            cycle.chunked_encoding = False
            # Set expected_content_length high so uvicorn's body-length
            # check (line 85 in httptools_impl.py) doesn't reject our data.
            # The connection closes on EOF, not when this many bytes are sent.
            cycle.expected_content_length = 2**63
        else:
            self._logger.warning("[HTTP] Could not find RequestResponseCycle — chunked encoding may be active")

        # ── 1. Send response headers (raw ASGI — no Content-Length, no TE) ──
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"video/mpeg"),
                (b"cache-control", b"no-cache"),
                (b"connection", b"close"),
                (b"x-accel-buffering", b"no"),
            ],
        })

        cleanup = self._cleanup_fn

        # ── 2. Monitor for client disconnect (Phase 8.7) ──────────────────
        monitor_task = asyncio.create_task(
            self._disconnect_monitor(
                receive,
                lambda: cleanup(reason="asgi_receive"),
            )
        )

        # ── 3. Stream raw TS packets ─────────────────────────────────────
        try:
            async for chunk in generate_ts_stream_async(self._client_queue, clock=self._clock):
                await send({
                    "type": "http.response.body",
                    "body": chunk,
                    "more_body": True,
                })
        except asyncio.CancelledError:
            cleanup(reason="cancelled")
        except Exception as exc:
            self._logger.error("Raw TS send error: %s: %s", type(exc).__name__, exc)
            cleanup(reason=f"send_error:{type(exc).__name__}")
        finally:
            # Send terminal frame so uvicorn knows the response is done.
            try:
                await send({
                    "type": "http.response.body",
                    "body": b"",
                    "more_body": False,
                })
            except Exception:
                pass
            cleanup(reason="generator_finally")
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass


_HLS_SEGMENT_RE = _re.compile(r"^seg_\d{5}\.ts$")


class HLSAccessFilter(logging.Filter):
    """Suppress uvicorn access log entries for high-frequency polling requests.

    HLS clients poll live.m3u8 every ~1-2s and fetch segments continuously.
    EPG clients poll /api/epg on short intervals.
    These are high-frequency, low-information events that clutter the log.
    Error responses (status >= 400) are still logged.
    """

    _QUIET_PREFIXES = ("/hls/", "/channels/", "/api/epg", "/discover.json", "/lineup_status.json")
    _QUIET_SUFFIXES = ("/status",)  # suppress /channel/*/status polling

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 5:
            return True
        path = args[2] if len(args) > 2 else ""
        status_code = args[4] if len(args) > 4 else 0
        if isinstance(path, str):
            is_quiet = (
                any(path.startswith(p) for p in self._QUIET_PREFIXES)
                or any(path.endswith(s) for s in self._QUIET_SUFFIXES)
            )
            if is_quiet:
                try:
                    if int(status_code) < 400:
                        return False
                except (ValueError, TypeError):
                    pass
        return True


class SystemMode(Enum):
    """System-wide operational modes"""

    NORMAL = "normal"
    EMERGENCY = "emergency"
    MAINTENANCE = "maintenance"
    RECOVERY = "recovery"


@dataclass
class HlsDiagnosticsState:
    """Per-channel HLS diagnostic state.

    Extracted from ProgramDirector to make the boundary explicit and testable.
    PD holds one instance and delegates all _hls_diag_* calls to it.
    """

    duration_s: float
    ring_max_events: int
    lock: threading.Lock = None  # set post-init
    mode_until: dict = None       # channel_id -> float (monotonic)
    ring: dict = None             # channel_id -> deque
    reconnect_hits: dict = None   # channel_id -> deque

    def __post_init__(self) -> None:
        if self.lock is None:
            self.lock = threading.Lock()
        if self.mode_until is None:
            self.mode_until = {}
        if self.ring is None:
            self.ring = {}
        if self.reconnect_hits is None:
            self.reconnect_hits = {}

    def is_active(self, channel_id: str) -> bool:
        now = time.monotonic()
        with self.lock:
            return self.mode_until.get(channel_id, 0.0) > now

    def record(self, channel_id: str, event: str, **fields) -> None:
        now = time.monotonic()
        with self.lock:
            ring = self.ring.get(channel_id)
            if ring is None:
                ring = deque(maxlen=self.ring_max_events)
                self.ring[channel_id] = ring
            ring.append({"t": now, "event": event, **fields})

    def dump_recent(self, channel_id: str, max_events: int = 120) -> list:
        with self.lock:
            return list(self.ring.get(channel_id, []))[-max_events:]

    def trigger(self, channel_id: str, reason: str, **fields) -> None:
        now = time.monotonic()
        with self.lock:
            prev = self.mode_until.get(channel_id, 0.0)
            self.mode_until[channel_id] = max(prev, now + self.duration_s)
        self.record(channel_id, "DIAG_TRIGGER", reason=reason, **fields)

    def note_reconnect_attempt(self, channel_id: str) -> int:
        now = time.monotonic()
        with self.lock:
            dq = self.reconnect_hits.get(channel_id)
            if dq is None:
                dq = deque()
                self.reconnect_hits[channel_id] = dq
            dq.append(now)
            while dq and (now - dq[0]) > 30.0:
                dq.popleft()
            return len(dq)


class ChannelManagerProvider(Protocol):
    """Protocol for getting ChannelManager instances."""

    def get_channel_manager(self, channel_id: str) -> Any:
        """Get ChannelManager instance for a channel."""
        ...

    def list_channels(self) -> list[str]:
        """List all available channel IDs."""
        ...

    def stop_channel(self, channel_id: str) -> None:
        """Stop channel when last viewer disconnects (channel enters STOPPED; health/reconnect does nothing)."""
        ...
