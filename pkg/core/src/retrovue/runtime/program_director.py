"""
Program Director

Pattern: Orchestrator + Policy Enforcer

The ProgramDirector is the control plane inside RetroVue. It is the global coordinator and policy layer for the entire broadcast system.
It orchestrates all channels, enforces system-wide policies, and manages emergency overrides.

Key Responsibilities:
- Coordinate all channels at a system level
- Enforce global policy and mode (normal vs emergency)
- Trigger system-wide emergency override and revert
- Report system health and status

Boundaries:
- ProgramDirector IS allowed to: Coordinate channels, enforce policies, manage emergencies
- ProgramDirector IS NOT allowed to: Generate schedules, ingest content, pick content, manage individual viewers, spawn Producer instances directly

Design Principles:
- Global coordination across all channels
- System-wide policy enforcement
- Emergency override capabilities
- Resource coordination and health monitoring
"""

import atexit
import asyncio
from collections import deque
import gc
import logging
import os
import queue
import signal as _signal_mod
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from threading import Thread
from typing import Any, Callable, Optional, Protocol

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import HTMLResponse, StreamingResponse
from uvicorn import Config, Server

from retrovue.runtime.clock import MasterClock, RealTimeMasterClock
from retrovue.runtime.pace import PaceController
from retrovue.runtime.channel_stream import (
    ChannelStream,
    FakeTsSource,
    SocketTsSource,
    generate_ts_stream,
    generate_ts_stream_async,
)
from retrovue.runtime.config import (
    ChannelConfig,
    ChannelConfigProvider,
    DEFAULT_PROGRAM_FORMAT,
    InlineChannelConfigProvider,
)

try:
    from retrovue.runtime.settings import RuntimeSettings  # type: ignore
except ImportError:  # pragma: no cover - settings optional
    RuntimeSettings = None  # type: ignore


# ---------------------------------------------------------------------------
# Startup reaper: kill stale AIR processes from a previous Core incarnation
# ---------------------------------------------------------------------------
_EXPECTED_AIR_EXE_NAMES = frozenset({"retrovue_air"})

# Resolved once at import time so the reaper matches on the exact deployment path.
_DEPLOYMENT_AIR_DIR: Path | None = None
try:
    _repo_root = Path(__file__).resolve().parents[5]  # .../pkg/core/src/retrovue/runtime -> repo root
    _candidate = _repo_root / "pkg" / "air" / "build" / "retrovue_air"
    if _candidate.is_file():
        _DEPLOYMENT_AIR_DIR = _candidate.parent.resolve()
except Exception:
    pass


def _reap_stale_air_processes(*, my_pid: int) -> int:
    """Find and SIGTERM stale retrovue_air processes belonging to this deployment.

    Matching criteria (ALL must hold):
      1. comm (short process name) is 'retrovue_air'
      2. Executable path resolves into the same build directory as this deployment
      3. Running as the same uid
      4. Not our own pid (we haven't launched anything yet, but guard anyway)
      5. Parent is pid 1 (orphaned — reparented to init)

    Returns the number of processes reaped.
    """
    logger = logging.getLogger(__name__)
    my_uid = os.getuid()
    reaped = 0

    if _DEPLOYMENT_AIR_DIR is None:
        logger.debug("STARTUP-REAPER: cannot resolve deployment AIR dir — skipping")
        return 0

    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return 0  # not Linux

    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == my_pid:
            continue

        try:
            # 1. Check comm (fast, no symlink resolution)
            comm = (entry / "comm").read_text().strip()
            if comm not in _EXPECTED_AIR_EXE_NAMES:
                continue

            # 2. Check uid (loginuid or status UID line)
            status_text = (entry / "status").read_text()
            uid_line = [l for l in status_text.splitlines() if l.startswith("Uid:")]
            if not uid_line:
                continue
            real_uid = int(uid_line[0].split()[1])
            if real_uid != my_uid:
                logger.debug(
                    "STARTUP-REAPER: pid %d is retrovue_air but uid %d != %d — skipping (different user)",
                    pid, real_uid, my_uid,
                )
                continue

            # 3. Check ppid == 1 (orphaned)
            ppid_line = [l for l in status_text.splitlines() if l.startswith("PPid:")]
            if not ppid_line:
                continue
            ppid = int(ppid_line[0].split()[1])
            if ppid != 1:
                logger.debug(
                    "STARTUP-REAPER: pid %d is retrovue_air but ppid=%d (not orphaned) — skipping",
                    pid, ppid,
                )
                continue

            # 4. Check executable path is within our deployment build dir
            try:
                exe_path = (entry / "exe").resolve()
            except (OSError, PermissionError):
                continue
            if exe_path.parent.resolve() != _DEPLOYMENT_AIR_DIR:
                logger.debug(
                    "STARTUP-REAPER: pid %d exe %s not in deployment dir %s — skipping",
                    pid, exe_path, _DEPLOYMENT_AIR_DIR,
                )
                continue

            # 5. Read cmdline for logging context
            try:
                cmdline = (entry / "cmdline").read_text().replace("\x00", " ").strip()
            except Exception:
                cmdline = "(unreadable)"

            # All criteria matched — this is an orphaned AIR from our deployment.
            logger.warning(
                "STARTUP-REAPER: killing stale AIR process pid=%d cmd=[%s] "
                "(orphaned, ppid=1, uid=%d, exe=%s)",
                pid, cmdline, real_uid, exe_path,
            )
            try:
                os.kill(pid, _signal_mod.SIGTERM)
                # Wait briefly for graceful exit, then escalate.
                for _ in range(10):  # 10 × 0.2s = 2s
                    time.sleep(0.2)
                    try:
                        os.kill(pid, 0)  # probe — raises if gone
                    except ProcessLookupError:
                        break
                else:
                    logger.warning(
                        "STARTUP-REAPER: pid %d did not exit after SIGTERM, sending SIGKILL", pid,
                    )
                    try:
                        os.kill(pid, _signal_mod.SIGKILL)
                    except ProcessLookupError:
                        pass
                reaped += 1
            except ProcessLookupError:
                logger.debug("STARTUP-REAPER: pid %d already gone", pid)
            except PermissionError:
                logger.warning("STARTUP-REAPER: no permission to kill pid %d", pid)

        except (FileNotFoundError, ProcessLookupError):
            # Process vanished while we were inspecting it — benign race.
            continue
        except Exception as exc:
            logger.debug("STARTUP-REAPER: error inspecting pid %d: %s", pid, exc)
            continue

    if reaped == 0:
        logger.info("STARTUP-REAPER: no stale AIR processes found")
    else:
        logger.warning("STARTUP-REAPER: sent SIGTERM to %d stale AIR process(es)", reaped)

    return reaped


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
            async for chunk in generate_ts_stream_async(self._client_queue):
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


import re as _re


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


class ProgramDirector:
    """
    Global coordinator and policy layer for the entire broadcast system.

    Pattern: Orchestrator + Policy Enforcer

    Phase 0 Contract Implementation:
    - Exposes HTTP surface for viewers and operators
    - Acts as the only network-facing component
    - Routes viewer "tune" requests to ChannelManager
    - Owns and manages one FanoutBuffer (ChannelStream) per channel
    - Provides live byte stream endpoints that join mid-stream
    - Stops playout engine pipeline when last viewer disconnects
    - Enforces global overrides by commanding ChannelManagers

    Key Responsibilities:
    - Coordinate all channels at a system level
    - Enforce global policy and mode (normal vs emergency)
    - Trigger system-wide emergency override and revert
    - Report system health and status

    Boundaries:
    - IS allowed to: Coordinate channels, enforce policies, manage emergencies, route HTTP requests
    - IS NOT allowed to: Generate schedules, ingest content, pick content, spawn Producer instances directly, generate A/V

    BROADCAST DAY BEHAVIOR (06:00 → 06:00):
    - ProgramDirector coordinates channels, but does NOT redefine broadcast day logic.
    - ProgramDirector can ask ScheduleService for the current broadcast day or what's
      rolling over, but it does not slice content or reschedule content at day boundaries.
    - Emergency / override logic should respect in-progress longform content
      (e.g. a movie spanning 05:00–07:00) unless an emergency explicitly overrides
      normal playout.
    - Goal: ProgramDirector should treat broadcast day mostly as a reporting/scheduling
      grouping, not as a playout cut point.
    """

    def __init__(
        self,
        channel_manager_provider: Optional[ChannelManagerProvider] = None,
        clock: Optional[MasterClock] = None,
        target_hz: Optional[float] = None,
        host: str = "0.0.0.0",
        port: int = 8000,
        *,
        sleep_fn=time.sleep,
        # Embedded mode (when provider is None): PD owns ChannelManager registry
        schedule_dir: Optional[Path] = None,
        channel_config_provider: Optional[Any] = None,
        mock_schedule_grid_mode: bool = False,
        program_asset_path: Optional[str] = None,
        program_duration_seconds: Optional[float] = None,
        filler_asset_path: Optional[str] = None,
        filler_duration_seconds: float = 3600.0,
        mock_schedule_ab_mode: bool = False,
        asset_a_path: Optional[str] = None,
        asset_b_path: Optional[str] = None,
        segment_seconds: float = 10.0,
        resolved_config: Optional[Any] = None,
    ) -> None:
        """Initialize the Program Director.
        
        Args:
            channel_manager_provider: Optional provider for ChannelManager instances (tests).
                When None, use embedded config (schedule_dir or mock flags) and PD owns the registry.
            clock: MasterClock instance (optional)
            target_hz: Pacing target frequency (optional)
            host: HTTP server bind address
            port: HTTP server port
            sleep_fn: Sleep function for testing (optional)
            schedule_dir: For embedded mode: directory containing schedule.json files
            channel_config_provider: For embedded mode: channel config provider
            mock_schedule_*: For embedded mode: mock schedule options
        """
        self._logger = logging.getLogger(__name__)
        self._resolved_config = resolved_config
        if resolved_config is None:
            raise RuntimeError(
                "resolved_config is required for ProgramDirector — "
                "fallback defaults are no longer supported"
            )
        # INV-CONFIG-IMMUTABLE-001: Read from resolved config (required).
        _ch_cfg = resolved_config["channel"]
        self._clock = clock or RealTimeMasterClock()
        if target_hz is None and RuntimeSettings:
            target_hz = RuntimeSettings.pace_target_hz
        self._pace = PaceController(clock=self._clock, target_hz=target_hz or 30.0, sleep_fn=sleep_fn)
        self._pace_thread: Optional[Thread] = None
        
        # Phase 0: ChannelManager integration (provider or embedded registry)
        self._channel_manager_provider = channel_manager_provider
        
        # Embedded mode: PD is sole authority for ChannelManager lifecycle (creation, health, fanout, teardown)
        self._managers: dict[str, Any] = {}
        self._managers_lock = threading.Lock()
        self._schedule_service: Optional[Any] = None
        # Playlist Builder Daemons (playlog plan — INV-PLAYLOG-HORIZON-001)
        self._playlog_daemons: dict[str, Any] = {}
        self._channel_config_provider: Optional[Any] = None
        self._health_check_stop: Optional[threading.Event] = None
        self._health_check_thread: Optional[Thread] = None
        # P11D-009: boundaries are feasible at planning time; 1s tick cadence is sufficient
        self._health_check_interval_seconds = _ch_cfg["health_check_interval_seconds"]
        self._embedded_clock: Optional[Any] = None  # MasterClock with now_utc() for ChannelManagers
        self._test_mode = os.getenv("RETROVUE_TEST_MODE") == "1"
        self._mock_schedule_grid_mode = mock_schedule_grid_mode
        self._program_asset_path = program_asset_path
        self._program_duration_seconds = program_duration_seconds
        self._filler_asset_path = filler_asset_path
        self._filler_duration_seconds = filler_duration_seconds
        self._mock_schedule_ab_mode = mock_schedule_ab_mode
        self._asset_a_path = asset_a_path
        self._asset_b_path = asset_b_path
        self._segment_seconds = segment_seconds
        self._schedule_dir = schedule_dir or Path(".")

        if self._channel_manager_provider is None:
            self._init_embedded_registry(channel_config_provider)

        # Phase 0: FanoutBuffer (ChannelStream) per channel
        self._fanout_buffers: dict[str, ChannelStream] = {}
        self._fanout_lock = threading.Lock()
        # Pre-warmed (CLI-started) channels: grace period before teardown if no viewer connects
        self._pre_warmed_timers: dict[str, threading.Timer] = {}
        self._pre_warmed_lock = threading.Lock()
        # Phase 7: Optional factory for tests (channel_id, socket_path) -> ChannelStream
        self._channel_stream_factory: Optional[Callable[[str, str], ChannelStream]] = None
        
        # Phase 0: HTTP server
        self.host = host
        self.port = port
        self.fastapi_app = FastAPI(title="RetroVue ProgramDirector")
        self._server: Optional[Server] = None
        self._server_thread: Optional[Thread] = None

        # INV-VIEWER-LIFECYCLE-002: Cached event loop for ChannelManager
        # linger timers. Set by _start_http_server's uvicorn thread once
        # the asyncio loop is running. Without this, linger always SKIPs
        # and every last-viewer disconnect immediately kills AIR.
        self._asyncio_loop: Optional[asyncio.AbstractEventLoop] = None
        
        # Phase 0: System mode
        self._system_mode = SystemMode.NORMAL


        # Conditional diagnostic mode (per channel): minimal steady-state overhead.
        # State is encapsulated in HlsDiagnosticsState; PD holds one instance and delegates.
        _diag = _ch_cfg["diagnostics"]
        self._hls_diag = HlsDiagnosticsState(
            duration_s=_diag["duration_seconds"],
            ring_max_events=_diag["ring_max_events"],
        )

        # Evidence pipeline configuration
        _ev = _ch_cfg["evidence"]
        self._evidence_enabled = _ev["enabled"]
        self._evidence_port = _ev["port"]
        self._evidence_asrun_dir = _ev["asrun_dir"]
        self._evidence_ack_dir = _ev["ack_dir"]
        self._evidence_endpoint = f"127.0.0.1:{self._evidence_port}" if self._evidence_enabled else ""
        self._evidence_server = None

        # INV-CHANNEL-STARTUP-NONBLOCKING-001 + INV-CHANNEL-STARTUP-CONCURRENCY-001:
        _startup = _ch_cfg["startup"]
        self._startup_executor = ThreadPoolExecutor(
            max_workers=_startup["max_workers"],
            thread_name_prefix="channel-startup",
        )
        self._startup_semaphore = asyncio.Semaphore(_startup["concurrency"])

        # INV-SCHEDULE-PREWARM-001: Gate set once background schedule
        # prewarm + horizon init completes. Request handlers check this
        # to 503 during the warm-up window.
        self._startup_complete = threading.Event()

        # Register HTTP endpoints
        self._register_endpoints()

        # INV-VIEWER-LIFECYCLE-002: Capture the asyncio event loop from
        # uvicorn's thread so ChannelManager linger timers can schedule
        # call_later on it.
        @self.fastapi_app.on_event("startup")
        async def _capture_event_loop():
            self._asyncio_loop = asyncio.get_running_loop()
        
        self._logger.debug(
            "ProgramDirector initialized with target_hz=%s clock=%s host=%s port=%s",
            self._pace.target_hz,
            type(self._clock).__name__,
            host,
            port,
        )

    def _hls_diag_is_active(self, channel_id: str) -> bool:
        return self._hls_diag.is_active(channel_id)

    def _hls_diag_record(self, channel_id: str, event: str, **fields: Any) -> None:
        self._hls_diag.record(channel_id, event, **fields)

    def _hls_diag_dump_recent(self, channel_id: str, max_events: int = 120) -> None:
        for item in self._hls_diag.dump_recent(channel_id, max_events):
            self._logger.warning("[HLS-DIAG][%s] %s", channel_id, item)

    def _hls_diag_trigger(self, channel_id: str, reason: str, **fields: Any) -> None:
        self._hls_diag.trigger(channel_id, reason, **fields)
        self._logger.warning("[HLS-DIAG][%s] ENABLED reason=%s duration_s=%.0f", channel_id, reason, self._hls_diag.duration_s)
        self._hls_diag_dump_recent(channel_id)

    def _hls_diag_note_reconnect_attempt(self, channel_id: str, reason: str) -> None:
        hits = self._hls_diag.note_reconnect_attempt(channel_id)
        self._hls_diag_record(channel_id, "RECONNECT_ATTEMPT", reason=reason, hits_30s=hits)
        if hits >= 3:
            self._hls_diag_trigger(channel_id, "repeated_reconnect_attempts", hits_30s=hits)

    # External hook (used by HlsSegmenter)
    def hls_diag_event(self, channel_id: str, event: str, **fields: Any) -> None:
        self._hls_diag_record(channel_id, event, **fields)
        if event == "INV-HLS-SEGMENT-WALLCLOCK-AUDIT-001":
            self._hls_diag_trigger(channel_id, "wallclock_audit_violation", **fields)

    def _load_channels_list(self):
        """Load channels as list of dicts, using provider if available."""
        import json as _json
        if self._channel_config_provider is not None and hasattr(self._channel_config_provider, 'to_channels_list'):
            return self._channel_config_provider.to_channels_list()
        elif self._channel_config_provider is not None:
            result = []
            for cid in self._channel_config_provider.list_channel_ids():
                cfg = self._channel_config_provider.get_channel_config(cid)
                if cfg:
                    result.append({
                        'channel_id': cfg.channel_id,
                        'number': cfg.number,
                        'channel_id_int': cfg.channel_id_int,
                        'name': cfg.name,
                        'schedule_config': cfg.schedule_config,
                    })
            return result
        else:
            from pathlib import Path
            from retrovue.runtime.providers import YamlChannelConfigProvider
            yaml_dir = Path("/opt/retrovue/config/channels")
            if yaml_dir.is_dir():
                return YamlChannelConfigProvider(yaml_dir, resolved_config=self._resolved_config).to_channels_list()
            return []

    def _generate_iptv_m3u(self, request: "Request") -> "Response":
        """Generate IPTV M3U playlist pointing to canonical HLS manifests.

        This is the primary discovery surface for IPTV/VLC/general HLS clients.
        Each channel entry points to /channels/{id}/live.m3u8.

        The HDHomeRun /lineup.json endpoint (for Plex HDHomeRun tuner compat)
        continues to point to /channel/{id}.ts under INV-PLEX-LINEUP-001.
        """
        channels = self._load_channels_list()
        base_url = str(request.base_url).rstrip("/")

        sort_key = lambda ch: ch.get("number", ch.get("channel_id_int", 0))
        sorted_channels = sorted(channels, key=sort_key)

        guide_url = f"{base_url}/iptv/guide.xml"
        lines = [f'#EXTM3U url-tvg="{guide_url}"']
        for ch in sorted_channels:
            cid = ch["channel_id"]
            name = ch.get("name", cid)
            number = ch.get("number", ch.get("channel_id_int", ""))
            tvg = f'tvg-id="{number}" tvg-chno="{number}" tvg-name="{name}"'
            lines.append(f'#EXTINF:-1 {tvg},{name}')
            lines.append(f"{base_url}/channels/{cid}/live.m3u8")

        body = "\n".join(lines) + "\n"
        return Response(
            content=body,
            media_type="audio/x-mpegurl",
            headers={
                "Cache-Control": "no-cache, max-age=0",
                "Access-Control-Allow-Origin": "*",
            },
        )

    def _reload_config(self) -> dict[str, Any]:
        """Reload channel YAML configs, invalidating all config caches.

        The next schedule compilation, horizon expansion, or traffic fill
        will re-read the YAML from disk.
        """
        reloaded: list[str] = []

        # 1. Reload YamlChannelConfigProvider (channel list, format, etc.)
        if self._channel_config_provider is not None and hasattr(
            self._channel_config_provider, "reload"
        ):
            self._channel_config_provider.reload()
            reloaded.append("channel_config_provider")
            self._logger.info("[reload] Channel config provider reloaded")

        # 2. Invalidate all cached DslScheduleService._channel_dsl
        #    so the next compilation re-reads the YAML from disk.
        for attr_name in list(vars(self)):
            if attr_name.startswith("_dsl_"):
                svc = getattr(self, attr_name, None)
                if svc is not None and hasattr(svc, "_channel_dsl"):
                    svc._channel_dsl = None
                    channel_id = attr_name[5:]  # strip "_dsl_" prefix
                    reloaded.append(f"dsl:{channel_id}")
                    self._logger.info(
                        "[reload] DSL config cache invalidated for channel %s",
                        channel_id,
                    )

        self._logger.info(
            "[reload] Config reload complete: %d caches invalidated",
            len(reloaded),
        )
        return {
            "status": "ok",
            "reloaded": reloaded,
            "message": f"Reloaded {len(reloaded)} config caches",
        }

    def _init_embedded_registry(
        self, channel_config_provider: Optional[Any] = None
    ) -> None:
        """Build schedule service, config provider, producer factory (embedded mode).

        Blockplan-only: embedded registry registers only BlockPlan path.
        Mock/playlist schedule services are not available.
        """
        # ChannelManager and schedule services expect clock.now_utc() (datetime); use concrete MasterClock
        self._embedded_clock = MasterClock()
        from retrovue.runtime.channel_manager import (
            BlockPlanProducer,
            ChannelManager,
            MockAlternatingScheduleService,
            MockGridScheduleService,
        )

        if self._mock_schedule_ab_mode:
            if not self._asset_a_path or not self._asset_b_path:
                raise ValueError("Mock A/B mode requires asset_a_path and asset_b_path")
            self._schedule_service = MockAlternatingScheduleService(
                clock=self._embedded_clock,
                asset_a_path=self._asset_a_path,
                asset_b_path=self._asset_b_path,
                segment_seconds=self._segment_seconds,
            )
        elif self._mock_schedule_grid_mode:
            if not self._program_asset_path or self._program_duration_seconds is None:
                raise ValueError("Mock grid requires program_asset_path and program_duration_seconds")
            if not self._filler_asset_path:
                raise ValueError("Mock grid requires filler_asset_path")
            self._schedule_service = MockGridScheduleService(
                clock=self._embedded_clock,
                program_asset_path=self._program_asset_path,
                program_duration_seconds=self._program_duration_seconds,
                filler_asset_path=self._filler_asset_path,
                filler_duration_seconds=self._filler_duration_seconds,
            )
        else:
            # Blockplan-only: require channel config provider.
            self._schedule_service = None
            if channel_config_provider is None:
                raise ValueError(
                    "Channel config is required; mock/playlist schedule services are not available. "
                    "Provide a channels config file or use --mock-schedule-ab/--mock-schedule-grid."
                )
        self._channel_config_provider = channel_config_provider
        # Mock A/B without config file: provide minimal blockplan config for test-1.
        if self._channel_config_provider is None and self._mock_schedule_ab_mode:
            from retrovue.runtime.channel_manager import MockAlternatingScheduleService
            test1_config = ChannelConfig(
                channel_id=MockAlternatingScheduleService.MOCK_AB_CHANNEL_ID,
                number=1,
                channel_id_int=1,
                name="Test A/B",
                program_format=DEFAULT_PROGRAM_FORMAT,
                schedule_source="dsl",
                schedule_config={},
            )
            self._channel_config_provider = InlineChannelConfigProvider([test1_config])

        self._health_check_stop = threading.Event()

    def _get_schedule_service_for_channel(self, channel_id: str, channel_config: ChannelConfig) -> Any:
        """Get appropriate schedule service based on channel config.

        Embedded mock A/B or grid takes precedence for those channel(s).
        """
        # Embedded mock A/B or grid: use the single embedded schedule service for that channel.
        if self._schedule_service is not None:
            if self._mock_schedule_ab_mode:
                from retrovue.runtime.channel_manager import MockAlternatingScheduleService
                if channel_id == MockAlternatingScheduleService.MOCK_AB_CHANNEL_ID:
                    return self._schedule_service
            if self._mock_schedule_grid_mode:
                return self._schedule_service

        return self._get_dsl_service(channel_id, channel_config)

    def _get_dsl_service(self, channel_id: str, channel_config: "ChannelConfig") -> Any:
        """Create or return a DslScheduleService for DSL-backed channels.

        INV-SCHEDULE-PREWARM-001: Service creation is decoupled from schedule
        compilation. This method only constructs and caches the service object.
        Schedule loading is the responsibility of _prewarm_channel_schedules()
        which runs at server startup.
        """
        key = f"_dsl_{channel_id}"
        cached = getattr(self, key, None)
        if cached is not None:
            return cached

        from retrovue.runtime.dsl_schedule_service import DslScheduleService

        sc = channel_config.schedule_config or {}
        dsl_path = sc.get("dsl_path", "")
        filler_path = sc.get("filler_path", "/opt/retrovue/assets/filler.mp4")
        filler_duration_ms = sc.get("filler_duration_ms", 3_650_000)

        svc = DslScheduleService(
            dsl_path=dsl_path,
            filler_path=filler_path,
            filler_duration_ms=filler_duration_ms,
            channel_slug=channel_id,
            channel_type=sc.get("channel_type", "network"),
            resolved_config=self._resolved_config,
            clock=self._embedded_clock,
        )

        setattr(self, key, svc)
        return svc

    def _prewarm_channel_schedules(self) -> None:
        """Pre-warm schedule data for all configured channels at server startup.

        INV-SCHEDULE-PREWARM-001: All multi-day DSL compilation and EPG horizon
        building MUST be performed here (scheduler daemon startup), never on a
        viewer-triggered code path. This method creates each channel's schedule
        service and calls load_schedule() to compile the initial horizon.

        Called from start(), before _init_playlog_daemons().
        """
        if self._channel_config_provider is None:
            return

        if not hasattr(self._channel_config_provider, "list_channel_ids"):
            return

        warmed = 0
        for channel_id in self._channel_config_provider.list_channel_ids():
            config = self._channel_config_provider.get_channel_config(channel_id)
            if config is None:
                continue

            try:
                svc = self._get_schedule_service_for_channel(channel_id, config)
                ok, err = svc.load_schedule(channel_id)
                if not ok:
                    self._logger.warning(
                        "Prewarm[%s]: load_schedule failed: %s",
                        channel_id, err,
                    )
                else:
                    warmed += 1
            except Exception as e:
                self._logger.warning(
                    "Prewarm[%s]: failed: %s",
                    channel_id, e, exc_info=True,
                )

        self._logger.info(
            "Schedule prewarm complete: %d channels warmed", warmed,
        )

    def _init_playlog_daemons(self) -> None:
        """Create and start PlaylistBuilderDaemons for DSL channels.

        INV-PLAYLOG-HORIZON-001: Each DSL channel gets a daemon that
        maintains 2-3+ hours of fully-filled playout logs in
        PlaylistEvent (Postgres).

        Called from start(), after _prewarm_channel_schedules().
        """
        if self._channel_config_provider is None:
            return

        if not hasattr(self._channel_config_provider, "list_channel_ids"):
            return

        from retrovue.runtime.playlist_builder_daemon import PlaylistBuilderDaemon

        for channel_id in self._channel_config_provider.list_channel_ids():
            config = self._channel_config_provider.get_channel_config(channel_id)
            if config is None:
                continue
            if config.schedule_source != "dsl":
                continue

            # Program schedule (active revisions/items) is already warmed by
            # _prewarm_channel_schedules() which runs before this method.

            sc = config.schedule_config or {}

            # INV-EPG-VIEWER-INDEPENDENT-001: Wire program schedule horizon extension
            # into the daemon so EPG stays fresh without viewers.
            program_schedule_cb = None
            try:
                svc = self._get_schedule_service_for_channel(channel_id, config)
                if hasattr(svc, "_maybe_extend_horizon"):
                    program_schedule_cb = svc._maybe_extend_horizon
            except Exception:
                pass

            daemon = PlaylistBuilderDaemon(
                channel_id=channel_id,
                min_hours=sc.get("playlog_min_hours", 3),
                evaluation_interval_seconds=sc.get(
                    "playlog_eval_interval_seconds", 60,
                ),
                programming_day_start_hour=sc.get(
                    "programming_day_start_hour", 6,
                ),
                grid_minutes=sc.get("grid_minutes", 30),
                filler_path=sc.get("filler_path", "/opt/retrovue/assets/filler.mp4"),
                filler_duration_ms=sc.get("filler_duration_ms", 3_650_000),
                master_clock=self._embedded_clock,
                channel_tz=sc.get("channel_tz", "UTC"),
                dsl_path=sc.get("dsl_path", ""),
                program_schedule_extend_callback=program_schedule_cb,
            )

            # Readiness gate: synchronous initial evaluation
            blocks_filled = daemon.evaluate_once()
            report = daemon.get_health_report()
            self._logger.info(
                "PlaylistBuilder[%s]: readiness gate — "
                "healthy=%s depth=%.1fh blocks=%d filled=%d",
                channel_id,
                report.is_healthy,
                report.depth_hours,
                report.blocks_in_window,
                blocks_filled,
            )

            # Start background thread
            daemon.start()
            self._playlog_daemons[channel_id] = daemon

        self._logger.info(
            "PlaylistBuilderDaemons initialized: %d channels",
            len(self._playlog_daemons),
        )

    def _get_or_create_manager(self, channel_id: str) -> Any:
        """Get or create ChannelManager for a channel (embedded mode). PD is sole authority for creation.

        INV-CHANNEL-STARTUP-NONBLOCKING-001: If a manager already exists (even
        in STOPPED state after teardown), return it directly — no schedule
        reload.

        INV-SCHEDULE-PREWARM-001: Manager creation MUST NOT trigger schedule
        compilation. The schedule is pre-warmed at startup by
        _prewarm_channel_schedules(). If the schedule is not ready (channel
        was not configured at startup), this raises ChannelManagerError (503).
        """
        if not self._startup_complete.is_set():
            from retrovue.runtime.channel_manager import ChannelManagerError
            raise ChannelManagerError("Server is starting up — schedule prewarm in progress")

        with self._managers_lock:
            if channel_id in self._managers:
                manager = self._managers[channel_id]
                # Re-activate stopped manager for returning viewers
                if manager._channel_state == "STOPPED":
                    manager._channel_state = "IDLE"
                return manager

            channel_config = self._channel_config_provider.get_channel_config(channel_id)
            if channel_config is None:
                raise ValueError(
                    f"[channel {channel_id}] No channel config found; "
                    "blockplan-only mode requires config for each channel."
                )

            # INV-P5-001: Select schedule service based on channel config
            schedule_service = self._get_schedule_service_for_channel(channel_id, channel_config)

            # INV-SCHEDULE-PREWARM-001: Do not call load_schedule() here.
            # Schedule must already be loaded by _prewarm_channel_schedules().
            # Check readiness: for DSL services, blocks must be populated.
            if hasattr(schedule_service, "_blocks") and not schedule_service._blocks:
                from retrovue.runtime.channel_manager import ChannelManagerError
                raise ChannelManagerError(
                    f"Schedule not ready for {channel_id}: "
                    "schedule was not pre-warmed at startup. "
                    "Ensure _prewarm_channel_schedules() ran for this channel."
                )
            from retrovue.runtime.channel_manager import ChannelManager
            # INV-VIEWER-LIFECYCLE-002: Pass event loop so linger grace
            # period works.  Without it, every last-viewer disconnect
            # immediately kills AIR (LINGER_SKIP).
            # NOTE: get_running_loop() fails when called from an executor
            # thread. Use the loop cached on ProgramDirector instead.
            _loop = self._asyncio_loop
            manager = ChannelManager(
                channel_id=channel_id,
                clock=self._embedded_clock,
                schedule_service=schedule_service,
                program_director=self,
                event_loop=_loop,
                evidence_endpoint=self._evidence_endpoint,
                resolved_config=self._resolved_config,
                # INV-LIFECYCLE-PD-SOLE-TEARDOWN-001: PD is the sole teardown
                # authority. CM must not call stop_channel directly — it invokes
                # this callback instead.
                on_linger_expired=lambda cid=channel_id: self._stop_channel_internal(cid, reason="last_viewer_left"),
            )
            manager.channel_config = channel_config
            if self._mock_schedule_grid_mode:
                manager._mock_grid_block_minutes = 30
                manager._mock_grid_program_asset_path = self._program_asset_path
                manager._mock_grid_filler_asset_path = self._filler_asset_path
                manager._mock_grid_filler_epoch = datetime(
                    2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc
                )
            self._managers[channel_id] = manager
            self._logger.info(
                "[channel %s] ChannelManager created (channel_id_int=%d)",
                channel_id,
                channel_config.channel_id_int,
            )
            return manager

    _GC_REFREEZE_INTERVAL_S = 15.0

    def _health_check_loop(self) -> None:
        """Run check_health() and tick() on each registered ChannelManager (embedded mode)."""
        last_refreeze = time.monotonic()
        while (
            self._health_check_stop is not None
            and not self._health_check_stop.wait(timeout=self._health_check_interval_seconds)
        ):
            try:
                with self._managers_lock:
                    managers = list(self._managers.values())
                for manager in managers:
                    try:
                        manager.check_health()
                        manager.tick()
                    except Exception as e:
                        self._logger.warning(
                            "Health check failed for channel %s: %s",
                            getattr(manager, "channel_id", "?"),
                            e,
                            exc_info=True,
                        )

                # Periodic re-freeze: runtime churn (DB sessions, ScheduledBlocks,
                # ORM identities) accumulates in Gen 2 after the startup freeze.
                # At 60s interval, Gen 2 grew large enough for 80-90ms collections.
                # At 15s, Gen 2 stays small and collections stay sub-5ms.
                now = time.monotonic()
                if now - last_refreeze >= self._GC_REFREEZE_INTERVAL_S:
                    _gc_before = gc.get_stats()[2]
                    gc.collect()
                    _gc_after = gc.get_stats()[2]
                    gc.freeze()
                    # INV-GC-AUTOGEN2-SUPPRESSED-001: suppress automatic gen 2
                    # collections between re-freezes.  Only the gc.collect()
                    # above may trigger a gen 2 sweep.
                    # If freeze logic is ever removed, restore explicitly:
                    #   gc.set_threshold(700, 10, 10)
                    gc.set_threshold(700, 10, 10_000_000)
                    self._logger.debug(
                        "[GC] Re-freeze: gen2 collected=%d uncollectable=%d "
                        "— thresholds set to (700, 10, 10_000_000)",
                        _gc_after["collected"] - _gc_before["collected"],
                        _gc_after["uncollectable"] - _gc_before["uncollectable"],
                    )
                    last_refreeze = now

            except Exception as e:
                self._logger.warning("Health check loop error: %s", e, exc_info=True)

    def load_all_schedules(self) -> list[str]:
        """Load schedule data for discoverable channels (embedded mode). Blockplan-only."""
        if self._schedule_service is None:
            # Config-driven channels only; list from provider.
            if self._channel_config_provider is None:
                return []
            return self._channel_config_provider.list_channel_ids()
        if self._mock_schedule_ab_mode:
            from retrovue.runtime.channel_manager import MockAlternatingScheduleService
            channel_id = MockAlternatingScheduleService.MOCK_AB_CHANNEL_ID
            success, _ = self._schedule_service.load_schedule(channel_id)
            return [channel_id] if success else []
        if self._mock_schedule_grid_mode:
            # Grid mode: channel list from config provider if available.
            if self._channel_config_provider is None:
                return []
            return self._channel_config_provider.list_channel_ids()
        return []

    def _list_channels_internal(self) -> list[str]:
        """List channel IDs in active registry (embedded mode)."""
        with self._managers_lock:
            return list(self._managers.keys())

    def _get_pre_warmed_viewer_count(self, channel_id: str) -> int:
        """Return current viewer (subscriber) count for this channel (0 if no fanout yet)."""
        with self._fanout_lock:
            fanout = self._fanout_buffers.get(channel_id)
            return fanout.get_subscriber_count() if fanout else 0

    def _schedule_pre_warmed_teardown(self, channel_id: str, grace_seconds: int) -> None:
        """Schedule teardown of channel after grace_seconds if no viewer has connected."""
        def teardown_if_no_viewers() -> None:
            with self._pre_warmed_lock:
                self._pre_warmed_timers.pop(channel_id, None)
            if self._get_pre_warmed_viewer_count(channel_id) == 0:
                self._logger.info(
                    "[channel %s] Pre-warmed grace period (%ds) expired with no viewers; tearing down",
                    channel_id,
                    grace_seconds,
                )
                self.stop_channel(channel_id)

        with self._pre_warmed_lock:
            existing = self._pre_warmed_timers.pop(channel_id, None)
            if existing:
                existing.cancel()
            t = threading.Timer(float(grace_seconds), teardown_if_no_viewers)
            t.daemon = True
            self._pre_warmed_timers[channel_id] = t
            t.start()

    def start_channel(
        self,
        channel_id: str,
        pre_warmed_grace_seconds: Optional[int] = None,
    ) -> Any:
        """
        Single entry point for starting a channel: ensure ChannelManager exists and is ready.

        ProgramDirector uses this when a viewer tunes in (no grace period; teardown when viewers=0).
        The CLI can call it with pre_warmed_grace_seconds (e.g. 30) so the channel is pre-warmed:
        if no viewer connects within that many seconds, the channel is torn down; otherwise
        normal rules apply (teardown when last viewer disconnects). Returns the ChannelManager.
        """
        if self._channel_manager_provider is not None:
            return self._channel_manager_provider.get_channel_manager(channel_id)
        manager = self._get_or_create_manager(channel_id)
        if pre_warmed_grace_seconds is not None and pre_warmed_grace_seconds > 0:
            self._schedule_pre_warmed_teardown(channel_id, pre_warmed_grace_seconds)
        return manager

    def get_channel_manager(self, channel_id: str) -> Any:
        """Get or create ChannelManager (provider protocol). Delegates to start_channel (single code path)."""
        return self.start_channel(channel_id)

    def list_channels(self) -> list[str]:
        """List channel IDs in active registry (provider protocol)."""
        if self._channel_manager_provider is not None:
            return self._channel_manager_provider.list_channels()
        return self._list_channels_internal()

    def stop_channel(self, channel_id: str, reason: str | None = None) -> None:
        """Stop channel and remove from registry (provider protocol; when embedded, PD is sole authority).

        reason: When using embedded ChannelManagers, passed to AIR StopBlockPlanSession for accurate
        logging. Use "last_viewer_left" only when stopping due to viewer count 1→0; omit for admin stop.
        Provider protocol only receives channel_id (backward compatible).
        """
        if self._channel_manager_provider is not None:
            self._channel_manager_provider.stop_channel(channel_id)
        else:
            self._stop_channel_internal(channel_id, reason=reason)

    def has_channel_stream(self, channel_id: str) -> bool:
        """Return True if this channel has an active ChannelStream (for tests)."""
        if self._channel_manager_provider is not None:
            if hasattr(self._channel_manager_provider, "has_channel_stream"):
                return self._channel_manager_provider.has_channel_stream(channel_id)
            return False
        with self._fanout_lock:
            return channel_id in self._fanout_buffers

    def _stop_channel_internal(self, channel_id: str, reason: str | None = None) -> None:
        """Stop channel producer and fanout (embedded mode). PD is sole authority for teardown.

        INV-CHANNEL-STARTUP-NONBLOCKING-001: The ChannelManager is kept alive
        in self._managers so that a returning viewer can re-activate the channel
        without triggering schedule recompilation. Only the producer and fanout
        are torn down; schedule state persists in the manager.
        """
        stop_reason = reason or "channel_stop"
        with self._pre_warmed_lock:
            timer = self._pre_warmed_timers.pop(channel_id, None)
        if timer:
            timer.cancel()
        with self._managers_lock:
            manager = self._managers.get(channel_id)
        if manager is not None:
            self._logger.info("[channel %s] ChannelManager idle (producer stopped)", channel_id)
            manager.stop_channel(reason=stop_reason)
            # Signal the fanout stop event *before* killing the producer so
            # that when AIR's socket closes and the reader gets EOF it sees
            # _stop_event already set and exits cleanly instead of attempting
            # a spurious reconnect (INV-TEARDOWN-SIGNAL-BEFORE-KILL).
            with self._managers_lock:
                fanout = self._fanout_buffers.get(channel_id)
            if fanout is not None:
                fanout.signal_stop()
            if manager.active_producer:
                self._logger.info("[channel %s] Force-stopping producer (terminating Air)", channel_id)
                try:
                    manager.active_producer.stop(reason=getattr(manager, "_stop_reason", None) or stop_reason)
                    manager.active_producer = None
                except Exception as e:
                    self._logger.warning(
                        "Error stopping producer for channel %s: %s", channel_id, e
                    )
            with self._managers_lock:
                # INV-CHANNEL-STARTUP-NONBLOCKING-001: Keep manager alive.
                # Only the fanout is torn down. Schedule state persists.
                fanout = self._fanout_buffers.pop(channel_id, None)
            if fanout is not None:
                self._logger.info("[teardown] stopping reader loop for channel %s", channel_id)
                # INV-TEARDOWN-NONBLOCK: Run fanout.stop() in a background thread
                # to avoid blocking the asyncio event loop (which starves other channels).
                import threading as _td
                def _bg_stop(f=fanout, cid=channel_id):
                    try:
                        f.stop()
                    except Exception as e:
                        self._logger.warning(
                            "Error stopping channel stream for %s: %s", cid, e
                        )
                _td.Thread(target=_bg_stop, daemon=True).start()

    # Lifecycle -------------------------------------------------------------

    def _install_gc_telemetry(self) -> None:
        """Register a gc.callbacks entry that logs collection durations.

        Gen 2 collections traverse the entire tracked-object graph while
        holding the GIL.  With 12k+ catalog objects this can take 100-200ms,
        starving the upstream reader thread (UPSTREAM_LOOP select_ms spikes).

        Idempotent: skips if already installed (multiple start() calls).
        """
        sentinel = "_retrovue_gc_telemetry"
        for cb in gc.callbacks:
            if getattr(cb, "__name__", "") == sentinel:
                return  # Already installed

        _start_ns_holder = [0]

        def _retrovue_gc_telemetry(phase: str, info: dict) -> None:
            if phase == "start":
                _start_ns_holder[0] = time.monotonic_ns()
            elif phase == "stop":
                duration_ms = (time.monotonic_ns() - _start_ns_holder[0]) / 1e6
                gen = info.get("generation", -1)
                collected = info.get("collected", 0)
                uncollectable = info.get("uncollectable", 0)
                warn_threshold_ms = 50 if gen >= 2 else 180
                if duration_ms > warn_threshold_ms:
                    self._logger.warning(
                        "[GC] gen=%d duration_ms=%.2f collected=%d uncollectable=%d",
                        gen, duration_ms, collected, uncollectable,
                    )
                elif gen >= 2 or duration_ms > 5:
                    self._logger.debug(
                        "[GC] gen=%d duration_ms=%.2f collected=%d uncollectable=%d",
                        gen, duration_ms, collected, uncollectable,
                    )

        gc.callbacks.append(_retrovue_gc_telemetry)
        self._logger.info(
            "[GC] Telemetry installed: thresholds=%s tracked_objects=%d",
            gc.get_threshold(), len(gc.get_objects()),
        )

    def start(self) -> None:
        """Start the pacing loop, health-check loop (embedded), and HTTP server.

        INV-SCHEDULE-PREWARM-001 / INV-CHANNEL-STARTUP-NONBLOCKING-001:
        Evidence server, pace thread, and HTTP server launch first so the
        process is reachable immediately. Schedule loading, horizon init,
        and prewarm run in a background daemon thread. Request handlers
        return 503 until ``_startup_complete`` is set.
        """
        # Reap orphaned AIR processes from a previous Core incarnation before
        # we launch anything new.  Must run before any channel startup.
        _reap_stale_air_processes(my_pid=os.getpid())

        # Register atexit as a best-effort safety net.  This fires on normal
        # interpreter exit and unhandled exceptions in the main thread — but
        # NOT on SIGKILL or SIGSEGV.  The primary protection is the systemd
        # KillMode=mixed + signal handlers; atexit is a belt-and-suspenders.
        atexit.register(self._atexit_stop)

        # GC telemetry: log collection durations to correlate with UPSTREAM_LOOP spikes.
        # Gen 2 collections traverse the entire object graph under the GIL.
        self._install_gc_telemetry()

        # Start evidence gRPC server (if enabled)
        if self._evidence_enabled and self._evidence_server is None:
            try:
                from retrovue.runtime import evidence_server
                from retrovue.runtime.evidence_server import DurableAckStore
                ack_store = DurableAckStore(ack_dir=self._evidence_ack_dir)
                self._evidence_server = evidence_server.serve(
                    port=self._evidence_port,
                    block=False,
                    ack_store=ack_store,
                    asrun_dir=self._evidence_asrun_dir,
                )
                self._logger.info(
                    "Evidence gRPC server started on port %d", self._evidence_port,
                )
            except Exception as e:
                self._logger.warning("Failed to start evidence server: %s", e)
                self._evidence_endpoint = ""

        # Start pacing loop
        if self._pace_thread and self._pace_thread.is_alive():
            self._logger.debug("ProgramDirector.start() called but pace thread already running")
        else:
            def _run() -> None:
                self._logger.info("ProgramDirector pace loop starting")
                try:
                    self._pace.run_forever()
                finally:
                    self._logger.info("ProgramDirector pace loop stopped")

            thread = Thread(target=_run, name="program-director-pace", daemon=True)
            self._pace_thread = thread
            thread.start()
            self._logger.debug("ProgramDirector pace thread started")

        # Start HTTP server
        if self._server_thread and self._server_thread.is_alive():
            self._logger.debug("ProgramDirector HTTP server already running")
        else:
            def _run_server() -> None:
                self._logger.info("ProgramDirector HTTP server starting on %s:%s", self.host, self.port)
                logging.getLogger("uvicorn.access").addFilter(HLSAccessFilter())
                try:
                    config = Config(self.fastapi_app, host=self.host, port=self.port, log_level="info")
                    self._server = Server(config)
                    self._server.run()
                finally:
                    self._logger.info("ProgramDirector HTTP server stopped")

            server_thread = Thread(target=_run_server, name="program-director-http", daemon=True)
            self._server_thread = server_thread
            server_thread.start()
            self._logger.debug("ProgramDirector HTTP server thread started")

        # Embedded mode: run schedule loading + horizon init in background
        if self._channel_manager_provider is None:
            def _background_prewarm() -> None:
                try:
                    # Disable automatic GC during prewarm. Startup creates 100k+
                    # objects (catalog, schedules, ORM identities) and automatic
                    # Gen 2 collections mid-build scan the growing graph for
                    # 200-300ms with collected=0. We collect+freeze once at the end.
                    gc.disable()
                    configured_ids = self.load_all_schedules()
                    # Reconcile DB channels against YAML config (single source of truth).
                    from retrovue.runtime.channel_reconciliation import reconcile_channels
                    from retrovue.infra.uow import session as uow_session
                    with uow_session() as db:
                        reconcile_channels(db, set(configured_ids))
                    self._prewarm_channel_schedules()
                    self._init_playlog_daemons()
                    if self._health_check_stop is not None:
                        self._health_check_stop.clear()
                        self._health_check_thread = Thread(
                            target=self._health_check_loop,
                            name="program-director-health-check",
                            daemon=True,
                        )
                        self._health_check_thread.start()
                    # Freeze long-lived objects out of GC Gen 2 traversal.
                    # gc.freeze() moves them to a permanent generation the GC
                    # never re-traverses — Gen 2 drops to <1ms.
                    pre_freeze = len(gc.get_objects())
                    gc.collect()  # Flush pending garbage before freeze
                    gc.freeze()
                    # INV-GC-AUTOGEN2-SUPPRESSED-001: suppress automatic gen 2
                    # collections between re-freezes.  The 15-second
                    # health-check re-freeze is the only gen 2 sweep in steady
                    # state.  If freeze logic is ever removed, restore
                    # explicitly: gc.set_threshold(700, 10, 10)
                    gc.set_threshold(700, 10, 10_000_000)
                    gc.enable()  # Re-enable for runtime churn
                    self._logger.info(
                        "[GC] Frozen %d long-lived objects after startup "
                        "(Gen 2 traversal eliminated)",
                        pre_freeze,
                    )
                    self._logger.debug(
                        "[GC] Thresholds set to (700, 10, 10_000_000) "
                        "— gen 2 auto-collection suppressed post-startup-freeze"
                    )
                except RuntimeError:
                    self._logger.exception(
                        "Background prewarm failed (horizon readiness gate). "
                        "Channels will 503 until resolved."
                    )
                except Exception:
                    self._logger.exception("Background prewarm failed unexpectedly")
                finally:
                    if not gc.isenabled():
                        gc.enable()
                    self._startup_complete.set()

            prewarm_thread = Thread(
                target=_background_prewarm,
                name="program-director-prewarm",
                daemon=True,
            )
            prewarm_thread.start()
            self._logger.info("Background schedule prewarm started")
        else:
            # Non-embedded mode (tests with external provider): ready immediately
            self._startup_complete.set()

    def stop(self, timeout: float = 2.0) -> None:
        """Stop the pacing loop, HTTP server, and join threads.

        Parameters
        ----------
        timeout:
            Maximum seconds to wait for threads to exit before emitting a warning.
        """
        # Mark as called so the atexit handler doesn't repeat the teardown.
        self._atexit_called = True
        self._logger.debug("ProgramDirector.stop() requested")

        # Stop HTTP server
        self._stop_http_server()
        
        # Stop pacing loop
        self._pace.stop()
        thread = self._pace_thread
        if thread:
            thread.join(timeout=timeout)
            if thread.is_alive():
                self._logger.warning("ProgramDirector pace thread did not stop within %.2fs", timeout)
            else:
                self._logger.debug("ProgramDirector pace thread joined successfully")
            self._pace_thread = None
        
        # Shutdown startup executor
        self._startup_executor.shutdown(wait=False)

        # INV-TEARDOWN-SIGNAL-BEFORE-KILL: Signal all fanout stop events first
        # so reader loops see _stop_event when AIR sockets close, avoiding
        # spurious reconnect attempts during shutdown.
        with self._fanout_lock:
            for fanout in self._fanout_buffers.values():
                fanout.signal_stop()

        # Embedded mode: stop health-check thread and tear down all managers (including AIR).
        # Stop channel managers (and thus PlayoutSession/AIR) before stopping the Evidence
        # server so AIR receives Stop RPC and exits gracefully; otherwise Evidence server
        # stop can cause AIR to disconnect and exit, leading to "Event stream error" and
        # "Stop RPC error: connection refused" during shutdown.
        if self._channel_manager_provider is None:
            if self._health_check_stop is not None:
                self._health_check_stop.set()
            if self._health_check_thread is not None and self._health_check_thread.is_alive():
                self._health_check_thread.join(timeout=2.0)
                if self._health_check_thread.is_alive():
                    self._logger.warning("Health-check thread did not stop within timeout")
                self._health_check_thread = None
            with self._managers_lock:
                for channel_id, manager in list(self._managers.items()):
                    if manager.active_producer:
                        try:
                            manager.active_producer.stop()
                        except Exception as e:
                            self._logger.warning("Error stopping producer %s: %s", channel_id, e)
                        manager.active_producer = None
                self._managers.clear()

        # Now do the full fanout stop (join threads, close resources).
        with self._fanout_lock:
            for channel_id, fanout in list(self._fanout_buffers.items()):
                try:
                    fanout.stop()
                except Exception as e:
                    self._logger.warning("Error stopping fanout buffer for channel %s: %s", channel_id, e)
            self._fanout_buffers.clear()

        if self._channel_manager_provider is None:
            # Stop evidence server after AIR has been stopped (no remaining clients).
            if self._evidence_server is not None:
                try:
                    self._evidence_server.stop(grace=2.0)
                    self._logger.info("Evidence gRPC server stopped")
                except Exception as e:
                    self._logger.warning("Error stopping evidence server: %s", e)
                self._evidence_server = None

        else:
            # Non-embedded mode: stop evidence server (managers are external).
            if self._evidence_server is not None:
                try:
                    self._evidence_server.stop(grace=2.0)
                    self._logger.info("Evidence gRPC server stopped")
                except Exception as e:
                    self._logger.warning("Error stopping evidence server: %s", e)
                self._evidence_server = None

        # Shut down DslScheduleService background resources (loudness executor)
        for attr_name in list(vars(self)):
            if attr_name.startswith("_dsl_"):
                svc = getattr(self, attr_name, None)
                if svc is not None and hasattr(svc, "shutdown"):
                    try:
                        svc.shutdown()
                    except Exception as e:
                        self._logger.warning("Error shutting down %s: %s", attr_name, e)

        # Stop PlaylistBuilderDaemons
        for channel_id, daemon in list(self._playlog_daemons.items()):
            try:
                daemon.stop()
            except Exception as e:
                self._logger.warning("Error stopping PlaylistBuilderDaemon %s: %s", channel_id, e)
        self._playlog_daemons.clear()

        self._logger.debug("ProgramDirector stopped")

    # ------------------------------------------------------------------
    # atexit safety net
    # ------------------------------------------------------------------
    _atexit_called = False

    def _atexit_stop(self) -> None:
        """Best-effort cleanup on interpreter exit.

        Guarded by a flag so ``stop()`` is not called twice if the signal
        handler already ran it.
        """
        if self._atexit_called:
            return
        self._atexit_called = True
        try:
            self.stop(timeout=3.0)
        except Exception:
            pass


    # Phase 0 Contract Implementation -----------------------------------------

    def get_channel_mode(self, channel_id: str) -> str:
        """
        Phase 0 contract: Return the required mode for a channel.
        
        Args:
            channel_id: Channel identifier
            
        Returns:
            Mode string: "normal", "emergency", "guide", etc.
        """
        if self._system_mode == SystemMode.EMERGENCY:
            return "emergency"
        elif self._system_mode == SystemMode.MAINTENANCE:
            return "maintenance"
        return "normal"

    def get_channel_config(self, channel_id: str) -> Optional[ChannelConfig]:
        """Return channel config for channel_id from embedded config provider (if any)."""
        if self._channel_config_provider is None:
            return None
        return self._channel_config_provider.get_channel_config(channel_id)

    def _resolve_channel_manager(self, channel_id: str) -> "Any | None":
        """Resolve the ChannelManager for a channel using the existing ownership model.

        Returns None if the channel is unknown.
        """
        if self._channel_manager_provider is not None:
            try:
                return self._channel_manager_provider.get_channel_manager(channel_id)
            except Exception:
                return None
        with self._managers_lock:
            return self._managers.get(channel_id)

    def _resolve_or_create_channel_manager(self, channel_id: str) -> "Any | None":
        """Resolve or create a ChannelManager for a channel.

        INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001: HLS activation must use
        the same _get_or_create_manager path as raw TS viewers. This method
        ensures a ChannelManager exists for the given channel_id.

        Returns None if channel creation fails (unknown channel, startup
        in progress, etc.).
        """
        # Try existing manager first (fast path)
        mgr = self._resolve_channel_manager(channel_id)
        if mgr is not None:
            return mgr

        # Create via the same path as raw TS viewers
        if self._channel_manager_provider is not None:
            try:
                return self._channel_manager_provider.get_channel_manager(channel_id)
            except Exception:
                return None
        try:
            return self._get_or_create_manager(channel_id)
        except Exception:
            return None

    async def _ensure_channel_active_for_hls(self, channel_id: str, session_id: str) -> "Any | None":
        """Ensure a channel is active by tuning in an HLS phantom viewer.

        INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001: Uses the same channel
        activation path as raw TS viewers — _get_or_create_manager + tune_in.
        Does NOT create a parallel lifecycle.

        INV-HLS-PHANTOM-DRAIN-KEEPS-CHANNEL-ALIVE-001: Subscribes a phantom
        to the ChannelStream fanout so the byte pipeline stays alive while
        HLS clients poll. Exactly one phantom per channel. The phantom drain
        thread disconnects when no HLS client has polled recently.

        Returns the ChannelManager on success, None on failure.
        """
        import time as _time

        # INV-HLS-PHANTOM-DRAIN-KEEPS-CHANNEL-ALIVE-001: Exactly one phantom
        # per channel. Use _hls_activity_lock to serialize check-and-register
        # so concurrent manifest requests cannot create duplicate phantoms.
        with self._hls_activity_lock:
            if channel_id in self._hls_phantom_sessions:
                # Phantom already active — just refresh activity and return
                self._hls_last_activity[channel_id] = _time.monotonic()
                return self._resolve_channel_manager(channel_id)
            # Reserve the slot immediately so concurrent requests see it
            phantom_id = f"hls-v2-phantom-{channel_id}-{uuid.uuid4().hex[:8]}"
            self._hls_phantom_sessions[channel_id] = phantom_id
            self._hls_last_activity[channel_id] = _time.monotonic()
        loop = asyncio.get_running_loop()

        def _startup():
            mgr = self._resolve_or_create_channel_manager(channel_id)
            if mgr is None:
                return None

            # tune_in triggers _ensure_producer_running → starts AIR.
            # AIR immediately writes to the UDS socket. If nobody reads
            # within ~200ms, AIR's SocketSink overflows → detach → session
            # ends with reason=stopped → crash-loop.
            #
            # Fix: start a pre-drain thread that grabs the accepted socket
            # from the queue and reads from it immediately, preventing
            # backpressure. The ChannelStream reader will take over later
            # via the normal reconnect path.
            import time as _t

            mgr.tune_in(phantom_id, {"channel_id": channel_id, "hls": True})

            # AIR immediately writes to the UDS socket after startup.
            # If nobody reads within ~200ms, SocketSink overflows → detach
            # → session ends (reason=stopped) → crash-loop.
            #
            # Fix: grab the accepted socket from the queue and construct
            # the ChannelStream directly with it (via SocketTsSource),
            # bypassing the slow factory retry loop. This ensures the
            # reader thread starts draining immediately.
            import time as _t
            from retrovue.runtime.channel_stream import SocketTsSource

            producer = getattr(mgr, "active_producer", None)
            reader_queue = getattr(producer, "reader_socket_queue", None) if producer else None

            if reader_queue is not None:
                try:
                    t0 = _t.monotonic()
                    sock = reader_queue.get(timeout=5.0)
                    self._logger.info(
                        "[HLS %s] Socket acquired from queue in %.0fms",
                        channel_id, (_t.monotonic() - t0) * 1000,
                    )
                    _hls_seg = getattr(mgr, "hls_segmenter", None)
                    fanout = ChannelStream(
                        channel_id=channel_id,
                        ts_source_factory=lambda stop_event=None, s=sock: SocketTsSource(s),
                        hls_manager=None,
                        hls_segmenter=_hls_seg,
                    )
                    self._fanout_buffers[channel_id] = fanout
                except Exception as exc:
                    self._logger.warning(
                        "[HLS %s] direct fanout creation failed: %s", channel_id, exc,
                    )

            return mgr

        # INV-CHANNEL-STARTUP-CONCURRENCY-001: Acquire startup semaphore
        await self._startup_semaphore.acquire()
        try:
            mgr = await loop.run_in_executor(self._startup_executor, _startup)
        except Exception as exc:
            self._logger.warning(
                "HLS activation failed for channel %s: %s", channel_id, exc,
            )
            mgr = None
        finally:
            self._startup_semaphore.release()

        if mgr is None:
            # Startup failed — clean up the reserved slot
            with self._hls_activity_lock:
                self._hls_phantom_sessions.pop(channel_id, None)
                self._hls_last_activity.pop(channel_id, None)
            return None

        # Wait for fanout to establish so bytes start flowing to the segmenter
        fanout = None
        for _ in range(10):
            fanout = self._get_or_create_fanout_buffer(channel_id, mgr)
            if fanout and fanout.is_running():
                break
            await asyncio.sleep(1)

        if fanout is None:
            # Startup failed — clean up phantom
            self._logger.warning(
                "[HLS-v2 %s] activation failed (no fanout), cleaning up phantom %s",
                channel_id, phantom_id,
            )
            try:
                mgr.tune_out(phantom_id)
            except Exception:
                pass
            with self._hls_activity_lock:
                self._hls_phantom_sessions.pop(channel_id, None)
                self._hls_last_activity.pop(channel_id, None)
            return None

        # Subscribe phantom to fanout and start drain thread.
        # This keeps the ChannelStream subscriber list non-empty so AIR bytes
        # continue flowing through the fanout → HlsSegmenter tee path.
        phantom_queue = fanout.subscribe(phantom_id)

        def _drain_hls_v2_phantom():
            IDLE_CHECK_INTERVAL = 5.0
            idle_timeout = getattr(mgr, "LINGER_SECONDS", 20)
            self._logger.info(
                "[HLS-v2-phantom %s] started, idle_timeout=%ds", channel_id, idle_timeout,
            )
            while True:
                # Sleep between checks — the BytesBoundedQueue's drop_oldest
                # policy handles overflow silently. We don't need to drain at
                # wire rate; we just need to stay subscribed and periodically
                # confirm the stream is alive.
                _time.sleep(IDLE_CHECK_INTERVAL)

                # Pull one chunk to confirm stream is alive (non-blocking)
                try:
                    chunk = phantom_queue.get(timeout=0.01)
                    if not chunk:
                        break  # EOF
                except Exception:
                    pass  # queue empty or timeout — stream may be starting

                # Check if any HLS client is still active
                with self._hls_activity_lock:
                    last = self._hls_last_activity.get(channel_id, 0)
                idle_seconds = _time.monotonic() - last
                if idle_seconds > idle_timeout:
                    self._logger.info(
                        "[HLS-v2-phantom %s] no client activity for %.0fs, disconnecting",
                        channel_id, idle_seconds,
                    )
                    break

            # Cleanup
            self._logger.info(
                "[HLS-v2-phantom %s] tearing down phantom viewer %s", channel_id, phantom_id,
            )
            try:
                mgr.tune_out(phantom_id)
            except Exception:
                pass
            try:
                fanout.unsubscribe(phantom_id)
            except Exception:
                pass
            with self._hls_activity_lock:
                self._hls_phantom_sessions.pop(channel_id, None)
                self._hls_last_activity.pop(channel_id, None)

        threading.Thread(
            target=_drain_hls_v2_phantom,
            daemon=True,
            name=f"hls-v2-phantom-{channel_id}",
        ).start()

        return mgr

    def _get_or_create_fanout_buffer(self, channel_id: str, manager: Any) -> Optional[ChannelStream]:
        """
        Phase 0 contract: Get or create FanoutBuffer (ChannelStream) for a channel.
        
        Args:
            channel_id: Channel identifier
            manager: ChannelManager instance
            
        Returns:
            ChannelStream instance or None if Producer not available
        """
        with self._fanout_lock:
            # Embedded mode + test mode: fake TS source (no real Producer)
            if (
                self._channel_manager_provider is None
                and self._test_mode
            ):
                if channel_id in self._fanout_buffers:
                    return self._fanout_buffers[channel_id]
                def ts_source_factory(_stop_event=None) -> FakeTsSource:
                    return FakeTsSource()
                fanout = ChannelStream(
                    channel_id=channel_id,
                    ts_source_factory=ts_source_factory,
                    hls_manager=None,
                )
                self._fanout_buffers[channel_id] = fanout
                return fanout

            # Check if Producer is running and has socket_path
            producer = getattr(manager, "active_producer", None)

            if channel_id in self._fanout_buffers:
                fanout = self._fanout_buffers[channel_id]
                if fanout.is_running() and producer:
                    return fanout
                # Remove stopped or orphaned fanout (producer gone)
                self._fanout_buffers.pop(channel_id, None)

            if not producer:
                return None

            # Phase 8 Air: we are the UDS server; the already-accepted socket is in reader_socket_queue.
            # Use that socket (do not connect to the path — the listener is closed after Air connects).
            reader_queue = getattr(producer, "reader_socket_queue", None)
            if reader_queue is not None:
                self._logger.info(
                    "Using reader_socket_queue for channel %s (socket from Air)",
                    channel_id,
                )

                def ts_source_factory(stop_event=None) -> Any:
                    # INV-CHANNEL-STREAM-RECONNECT-001: Resolve the *current*
                    # producer's queue at call time so reconnect after AIR
                    # restart picks up the new producer's socket.
                    #
                    # INV-CHANNEL-STREAM-SHUTDOWN-001: stop_event is passed by
                    # ChannelStream._create_ts_source so that all blocking waits
                    # here can be interrupted within the 5s stop() deadline.
                    for attempt in range(6):
                        if stop_event is not None and stop_event.is_set():
                            raise RuntimeError(
                                "Factory cancelled (shutdown) for %s" % channel_id
                            )
                        current_producer = getattr(manager, "active_producer", None)
                        if current_producer is None:
                            self._logger.debug(
                                "Factory: no active_producer for %s (attempt %d/6)",
                                channel_id, attempt + 1,
                            )
                            if stop_event is not None:
                                if stop_event.wait(timeout=2.0):
                                    raise RuntimeError(
                                        "Factory cancelled (shutdown) for %s" % channel_id
                                    )
                            else:
                                time.sleep(2.0)
                            continue
                        current_queue = getattr(current_producer, "reader_socket_queue", None)
                        if current_queue is None:
                            self._logger.debug(
                                "Factory: no reader_socket_queue for %s (attempt %d/6)",
                                channel_id, attempt + 1,
                            )
                            if stop_event is not None:
                                if stop_event.wait(timeout=2.0):
                                    raise RuntimeError(
                                        "Factory cancelled (shutdown) for %s" % channel_id
                                    )
                            else:
                                time.sleep(2.0)
                            continue
                        # Poll the queue in short bursts so stop_event can interrupt.
                        deadline = time.monotonic() + 2.0
                        while time.monotonic() < deadline:
                            if stop_event is not None and stop_event.is_set():
                                raise RuntimeError(
                                    "Factory cancelled (shutdown) for %s" % channel_id
                                )
                            try:
                                sock = current_queue.get(timeout=0.1)
                                self._logger.info(
                                    "Got socket from queue for channel %s",
                                    channel_id,
                                )
                                return SocketTsSource(sock)
                            except queue.Empty:
                                pass
                        self._logger.debug(
                            "Reader queue empty for channel %s (attempt %d/6)",
                            channel_id, attempt + 1,
                        )
                    raise RuntimeError(
                        "Timed out waiting for socket from reader_socket_queue for %s"
                        % channel_id
                    )

                # Wire HLS segmenter from ChannelManager if available
                _hls_seg = getattr(manager, "hls_segmenter", None)
                fanout = ChannelStream(channel_id=channel_id, ts_source_factory=ts_source_factory, hls_manager=None, hls_segmenter=_hls_seg)
                self._fanout_buffers[channel_id] = fanout
                return fanout

            # Fallback: Producer exposes only socket_path (legacy/test); connect as client (may fail if server closed).
            socket_path = getattr(producer, "socket_path", None)
            if not socket_path:
                return None
            if self._channel_stream_factory:
                fanout = self._channel_stream_factory(channel_id, str(socket_path))
            else:
                _hls_seg = getattr(manager, "hls_segmenter", None)
                fanout = ChannelStream(channel_id=channel_id, socket_path=socket_path, hls_manager=None, hls_segmenter=_hls_seg)
            self._fanout_buffers[channel_id] = fanout
            return fanout

    def _register_endpoints(self) -> None:
        """Register Phase 0 HTTP endpoints."""
        # Studio tagging UI
        from retrovue.web.studio import router as studio_router
        self.fastapi_app.include_router(studio_router)
        
        @self.fastapi_app.get("/channels", response_model=None)
        async def get_channels():
            """
            Phase 0 contract: Channel discovery endpoint.

            Returns list of available channels (from provider or embedded registry).
            Returns 503 during startup while schedule prewarm is in progress.
            """
            if not self._startup_complete.is_set():
                return Response(
                    content="Server is starting up — schedule prewarm in progress",
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            channels = []
            try:
                if self._channel_manager_provider is not None:
                    if hasattr(self._channel_manager_provider, "list_channels"):
                        channel_ids = self._channel_manager_provider.list_channels()
                        channels = [{"id": cid, "name": cid} for cid in channel_ids]
                else:
                    channel_ids = self._list_channels_internal()
                    channels = [{"id": cid, "name": cid} for cid in channel_ids]
            except Exception as e:
                self._logger.warning("Error getting channel list: %s", e)
            return {"channels": channels}

        def _run_stream_cleanup(
            channel_id: str,
            session_id: str,
            manager: Any,
            fanout: Optional[Any],
            *,
            reason: str = "unknown",
        ) -> None:
            """
            Unsubscribe viewer and update viewer count. Idempotent.
            Does NOT stop channel or upstream when last subscriber leaves:
            upstream (AIR UDS) stays connected so VLC reconnect does not restart AIR.
            """
            self._logger.info(
                "[HTTP] STREAM_CLEANUP id=%s channel=%s trigger=%s",
                session_id, channel_id, reason,
            )
            with self._fanout_lock:
                if fanout:
                    fanout.unsubscribe(session_id, reason=reason)
            try:
                manager.tune_out(session_id)
            except Exception as e:
                self._logger.debug("tune_out on cleanup: %s", e)

        async def _wait_disconnect_then_cleanup(receive_or_request, cleanup: Callable[[], None]) -> None:
            """When client disconnects, ASGI receive() returns; run cleanup so viewer_count and teardown run (Phase 8.7).

            ``receive_or_request`` may be a Starlette Request (has .receive())
            or a raw ASGI receive callable.

            Drains any ``http.request`` messages (unconsumed request body)
            and only fires cleanup on ``http.disconnect``.
            """
            receive_fn = getattr(receive_or_request, "receive", receive_or_request)
            try:
                while True:
                    msg = await receive_fn()
                    msg_type = msg.get("type", "unknown") if isinstance(msg, dict) else "non-dict"
                    if msg_type == "http.disconnect":
                        self._logger.info(
                            "[HTTP] ASGI_RECEIVE_RETURNED type=%s", msg_type,
                        )
                        break
                    # http.request with more_body=False means request body is
                    # fully consumed — keep waiting for http.disconnect.
                    # http.request with more_body=True — keep draining.
            except Exception as exc:
                self._logger.info(
                    "[HTTP] ASGI_RECEIVE_EXCEPTION %s: %s",
                    type(exc).__name__, exc,
                )
            cleanup()

        @self.fastapi_app.get("/channel/{channel_id}.m3u")
        async def channel_m3u(request: Request, channel_id: str) -> Response:
            """Return an M3U playlist pointing to the channel's live HLS manifest."""
            base_url = str(request.base_url).rstrip("/")
            body = f"#EXTM3U\n#EXTINF:-1,{channel_id}\n{base_url}/channels/{channel_id}/live.m3u8\n"
            return Response(
                content=body,
                media_type="audio/x-mpegurl",
                headers={"Content-Disposition": f'attachment; filename="{channel_id}.m3u"'},
            )

        @self.fastapi_app.get("/channel/{channel_id}.ts")
        async def stream_channel(request: Request, channel_id: str) -> Response:
            """
            INV-RAW-TS-TRANSPORT-001: Live MPEG-TS stream endpoint.

            Delivers raw continuous bytes with ``Connection: close`` and no
            ``Content-Length`` or ``Transfer-Encoding``, matching how real
            tuner devices (HDHomeRun, Tvheadend) behave.  Uses a custom ASGI
            response (``_RawTSResponse``) so that Starlette/uvicorn never
            injects ``Transfer-Encoding: chunked``, which caused intermittent
            HTTP 400 errors from Plex Live TV.
            """
            # INV-CHANNEL-STARTUP-CONCURRENCY-001: Fail fast when at capacity.
            if self._startup_semaphore.locked():
                return Response(
                    content="Server at startup capacity, try again shortly",
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            # Create session ID for this viewer
            session_id = str(uuid.uuid4())

            # INV-CHANNEL-STARTUP-NONBLOCKING-001 + CONCURRENCY-001: Acquire
            # semaphore, then offload manager acquisition + tune_in to the
            # bounded executor so the event loop is never blocked.
            await self._startup_semaphore.acquire()
            try:
                def _startup_channel():
                    if self._channel_manager_provider is not None:
                        mgr = self._channel_manager_provider.get_channel_manager(channel_id)
                    else:
                        mgr = self._get_or_create_manager(channel_id)
                    mgr.tune_in(session_id, {"channel_id": channel_id})
                    return mgr

                loop = asyncio.get_running_loop()
                manager = await loop.run_in_executor(
                    self._startup_executor, _startup_channel
                )
            except Exception as e:
                self._logger.error("Error starting channel %s: %s", channel_id, e)
                return Response(
                    content=f"Channel not available: {e}",
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            finally:
                self._startup_semaphore.release()

            # Get or create FanoutBuffer for this channel
            fanout = self._get_or_create_fanout_buffer(channel_id, manager)
            if not fanout:
                # Producer not ready yet, wait for it to start
                for _ in range(10):
                    await asyncio.sleep(1)
                    fanout = self._get_or_create_fanout_buffer(channel_id, manager)
                    if fanout:
                        break
                if not fanout:
                    _run_stream_cleanup(channel_id, session_id, manager, None, reason="fanout_timeout")
                    return Response(
                        content="Channel not ready",
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    )

            # Subscribe to FanoutBuffer
            client_queue = fanout.subscribe(session_id)
            cleaned = []

            def cleanup_stream(*, reason: str = "unknown") -> None:
                if cleaned:
                    return
                cleaned.append(1)
                _run_stream_cleanup(channel_id, session_id, manager, fanout, reason=reason)

            # Phase 8.7: disconnect monitor
            asyncio.create_task(_wait_disconnect_then_cleanup(
                request, lambda: cleanup_stream(reason="asgi_receive")))

            async def generate_stream():
                try:
                    async for chunk in generate_ts_stream_async(client_queue):
                        yield chunk
                except GeneratorExit:
                    cleanup_stream(reason="generator_exit")
                    return
                except asyncio.CancelledError:
                    cleanup_stream(reason="cancelled")
                    return
                finally:
                    cleanup_stream(reason="generator_finally")

            return StreamingResponse(
                generate_stream(),
                media_type="video/mpeg",
                headers={
                    "Connection": "close",
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        @self.fastapi_app.get("/debug/channels/{channel_id}/current-segment")
        async def get_current_segment(channel_id: str, now_utc_ms: Optional[int] = None) -> Any:
            """
            Phase 7: Test-only probe for expected asset + offset at tune-in.
            Returns current segment (asset_id, asset_path, start_offset_ms) when the
            channel manager supports get_current_segment(now_utc_ms).
            """
            try:
                if self._channel_manager_provider is not None:
                    manager = self._channel_manager_provider.get_channel_manager(channel_id)
                else:
                    manager = self._get_or_create_manager(channel_id)
            except Exception:
                return Response(
                    content="Channel not found",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            get_segment = getattr(manager, "get_current_segment", None)
            if not callable(get_segment):
                return Response(
                    content="Manager does not support current segment probe",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            try:
                segment = get_segment(now_utc_ms)
                if segment is None:
                    return Response(
                        content="No current segment",
                        status_code=status.HTTP_404_NOT_FOUND,
                    )
                return segment
            except Exception as e:
                self._logger.exception("get_current_segment failed")
                return Response(
                    content=str(e),
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        @self.fastapi_app.post("/admin/reload-config")
        async def reload_config() -> dict[str, Any]:
            """Reload channel YAML configs without restarting the server.

            Invalidates all config caches so the next schedule compilation,
            horizon expansion, or traffic fill picks up the new YAML.
            """
            result = self._reload_config()
            return result

        @self.fastapi_app.post("/admin/emergency")
        async def emergency_override() -> dict[str, Any]:
            """
            Phase 0 contract: Emergency override endpoint (placeholder/no-op for now).

            In Phase 0, this is a no-op. Future phases will enforce global overrides.
            """
            # Phase 0: No-op implementation
            return {"status": "ok", "message": "Emergency override endpoint (no-op in Phase 0)"}


        @self.fastapi_app.get("/api/epg")
        def get_epg_all(
            date: Optional[str] = None,
            channel: Optional[str] = None,
        ) -> Any:
            """EPG endpoint for all channels — reads from canonical compiled schedule.

            INV-EPG-READS-CANONICAL-SCHEDULE-001: reads from canonical relational
            schedule data, does NOT call compile_schedule() directly.
            """
            from zoneinfo import ZoneInfo
            from retrovue.runtime.dsl_schedule_service import DslScheduleService
            from retrovue.runtime.catalog_resolver import CatalogAssetResolver
            from retrovue.infra.uow import session

            if date is None:
                now = datetime.now(ZoneInfo("America/New_York"))
                if now.hour < 6:
                    broadcast_day = (now - timedelta(days=1)).strftime("%Y-%m-%d")
                else:
                    broadcast_day = now.strftime("%Y-%m-%d")
            else:
                broadcast_day = date

            channels = self._load_channels_list()

            if channel:
                channels = [c for c in channels if c["channel_id"] == channel]

            # Compute broadcast day window for range-based EPG lookup
            from datetime import date as _date_type
            _bd = _date_type.fromisoformat(broadcast_day)
            _programming_day_start = 6  # 06:00 local
            _tz = ZoneInfo("America/New_York")
            window_start = datetime(_bd.year, _bd.month, _bd.day, _programming_day_start, 0, tzinfo=_tz)
            window_end = window_start + timedelta(hours=24)

            # Build resolver once for metadata lookups
            with session() as db:
                _shared_resolver = CatalogAssetResolver(db)

            all_entries = []
            for ch in channels:
                try:
                    # INV-EPG-READS-CANONICAL-SCHEDULE-001: read canonical relational schedule
                    blocks = DslScheduleService.get_canonical_epg(
                        ch["channel_id"], window_start, window_end
                    )
                    if blocks is None:
                        all_entries.append({
                            "channel_id": ch["channel_id"],
                            "channel_name": ch["name"],
                            "error": "Schedule not yet compiled",
                        })
                        continue

                    from retrovue.epg.duration import epg_display_duration

                    for block in blocks:
                        asset_id = block["asset_id"]
                        series_title = block.get("title", "")
                        season_number = None
                        episode_number = None

                        description = ""
                        episode_title = ""
                        for cat_entry in _shared_resolver._catalog:
                            if cat_entry.canonical_id == asset_id:
                                series_title = cat_entry.series_title or series_title
                                season_number = cat_entry.season
                                episode_number = cat_entry.episode
                                description = getattr(cat_entry, "description", "") or ""
                                episode_title = getattr(cat_entry, "title", "") or ""
                                break

                        start_dt = datetime.fromisoformat(block["start_at"])
                        slot_sec = block["slot_duration_sec"]
                        ep_sec = block.get("episode_duration_sec", block["slot_duration_sec"])
                        end_dt = start_dt + timedelta(seconds=slot_sec)

                        all_entries.append({
                            "channel_id": ch["channel_id"],
                            "channel_name": ch["name"],
                            "start_time": start_dt.isoformat(),
                            "end_time": end_dt.isoformat(),
                            "title": (series_title or episode_title or "Untitled"),
                            "episode_title": episode_title,
                            "season": season_number,
                            "episode": episode_number,
                            "description": description,
                            "duration_minutes": round(ep_sec / 60, 1),
                            "slot_minutes": round(slot_sec / 60, 1),
                            "display_duration": epg_display_duration(
                                start_dt, end_dt, slot_sec, ep_sec,
                                is_movie=season_number is None,
                            ),
                            "asset_id": str(asset_id) if asset_id else None,
                        })
                except Exception as e:
                    self._logger.error("EPG error for %s: %s", ch["channel_id"], e, exc_info=True)
                    all_entries.append({
                        "channel_id": ch["channel_id"],
                        "channel_name": ch["name"],
                        "error": str(e),
                    })

            return {"broadcast_day": broadcast_day, "entries": all_entries}


        @self.fastapi_app.get("/channel/{channel_id}/status")
        def channel_status(channel_id: str) -> dict[str, Any]:
            """Real-time channel status for demo/dashboard pages.

            Returns current program, viewer count, and timing info.
            """
            from zoneinfo import ZoneInfo
            from retrovue.runtime.dsl_schedule_service import DslScheduleService
            from retrovue.infra.uow import session

            tz = ZoneInfo("America/New_York")
            now = datetime.now(tz)

            viewer_count = self._get_pre_warmed_viewer_count(channel_id)

            # Determine channel name
            channel_name = channel_id
            try:
                channels = self._load_channels_list()
                for ch in channels:
                    if ch["channel_id"] == channel_id:
                        channel_name = ch.get("name", channel_id)
                        break
            except Exception:
                pass

            # Find what's playing now from EPG
            now_playing = None
            try:
                if now.hour < 6:
                    broadcast_day = (now - timedelta(days=1)).strftime("%Y-%m-%d")
                else:
                    broadcast_day = now.strftime("%Y-%m-%d")

                from datetime import date as _date_type
                _bd = _date_type.fromisoformat(broadcast_day)
                window_start = datetime(_bd.year, _bd.month, _bd.day, 6, 0, tzinfo=tz)
                window_end = window_start + timedelta(hours=24)

                blocks = DslScheduleService.get_canonical_epg(
                    channel_id, window_start, window_end
                )
                for block in blocks or []:
                    start_dt = datetime.fromisoformat(block["start_at"])
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=tz)
                    slot_sec = block["slot_duration_sec"]
                    ep_sec = block.get("episode_duration_sec", slot_sec)
                    end_dt = start_dt + timedelta(seconds=slot_sec)

                    if start_dt <= now < end_dt:
                        title = block.get("title", "Untitled")
                        episode_title = ""
                        season = None
                        episode = None
                        description = ""

                        # Single-asset lookup instead of full catalog load
                        from retrovue.domain.entities import AssetEditorial
                        asset_id = block.get("asset_id")
                        if asset_id:
                            p = None
                            with session() as db:
                                ed = db.query(AssetEditorial).filter(
                                    AssetEditorial.asset_uuid == asset_id
                                ).first()
                                if ed:
                                    p = dict(ed.payload) if ed.payload else None
                            if p:
                                asset_title = p.get("title", "") or ""
                                series = p.get("series_title", "") or ""
                                if series:
                                    title = series
                                    episode_title = asset_title
                                else:
                                    title = asset_title or title
                                season = p.get("season_number")
                                episode = p.get("episode_number")
                                description = p.get("description", "") or ""

                        now_playing = {
                            "title": title,
                            "episode_title": episode_title,
                            "season": season,
                            "episode": episode,
                            "description": description,
                            "start_time": start_dt.astimezone(tz).isoformat(),
                            "end_time": end_dt.astimezone(tz).isoformat(),
                            "duration_minutes": round(ep_sec / 60, 1),
                            "slot_minutes": round(slot_sec / 60, 1),
                            "progress_pct": round(
                                (now - start_dt).total_seconds() / slot_sec * 100, 1
                            ),
                        }
                        break
            except Exception as e:
                self._logger.debug("Status EPG lookup error: %s", e)

            return {
                "channel_id": channel_id,
                "channel_name": channel_name,
                "viewer_count": viewer_count,
                "now_playing": now_playing,
                "server_time": now.isoformat(),
            }


        @self.fastapi_app.get("/demo/{channel_id}", response_class=HTMLResponse)
        async def demo_page(channel_id: str) -> HTMLResponse:
            """Serve the channel demo/continuity page."""
            channel_name = channel_id
            try:
                channels = self._load_channels_list()
                for ch in channels:
                    if ch["channel_id"] == channel_id:
                        channel_name = ch.get("name", channel_id)
                        break
            except Exception:
                pass

            html_path = Path("/opt/retrovue/pkg/core/templates/demo/channel.html")
            html = html_path.read_text()
            html = html.replace("{{CHANNEL_ID}}", channel_id)
            html = html.replace("{{CHANNEL_NAME}}", channel_name)
            return HTMLResponse(content=html)


        # ---------------------------------------------------------------
        # New canonical HLS endpoints (Phase 6 — backed by SegmentRing)
        # ---------------------------------------------------------------

        @self.fastapi_app.get("/channels/{channel_id}/live.m3u8")
        async def channels_hls_manifest(
            channel_id: str,
            request: Request,
            session: str | None = None,
        ) -> Response:
            """Serve live HLS manifest from the new canonical SegmentRing.

            INV-HLS-MANIFEST-LIVE-001: No EXT-X-ENDLIST.
            INV-HLS-MANIFEST-CHANNEL-SCOPED-001: Same content for all clients.
            INV-HLS-LIFECYCLE-SEGMENT-READY-001: 503 + Retry-After until ready.
            INV-HLS-ENDPOINT-SESSION-TOUCH-001: Touch only on 200.
            INV-HLS-QUIET-POLLING-001: No INFO logging per request.
            INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001: Activates inactive channel.

            Any request to this endpoint counts as a viewer. The first
            request activates the channel through the normal ChannelManager
            lifecycle (same as raw TS). The endpoint blocks until segments
            are available, then returns a valid manifest.
            """
            sid = session or f"hls-anon-{uuid.uuid4().hex[:8]}"
            req_id = uuid.uuid4().hex[:10]
            mgr = self._resolve_channel_manager(channel_id)

            # Determine whether the channel is active
            is_active = False
            if mgr is not None:
                rs = getattr(mgr, "runtime_state", None)
                has_viewers = rs is not None and rs.viewer_count > 0
                has_producer = mgr.active_producer is not None
                is_active = has_viewers or has_producer

            if not is_active:
                # Activate channel in background — don't block the response.
                asyncio.ensure_future(
                    self._ensure_channel_active_for_hls(channel_id, sid)
                )

            ring = getattr(mgr, "hls_segment_ring", None) if mgr else None
            gen = getattr(mgr, "hls_manifest_generator", None) if mgr else None

            # Try to generate a manifest with real segments
            playlist = gen.generate(ring) if (gen and ring) else None

            if playlist is None:
                # INV-HLS-LIFECYCLE-SEGMENT-READY-001:
                # During startup (or reconnect), return 503 + Retry-After
                # until at least one completed segment is available.
                ring_count = ring.count() if ring is not None else 0
                self._hls_diag_record(
                    channel_id,
                    "HLS_SERVE_SNAPSHOT",
                    req_id=req_id,
                    path="manifest",
                    status=503,
                    ring_count=ring_count,
                    is_active=is_active,
                )
                return Response(
                    content="Playlist not ready yet",
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    headers={"Retry-After": "1"},
                )

            # INV-HLS-ENDPOINT-SESSION-TOUCH-001: Touch on success only
            session_mgr = getattr(mgr, "hls_session_manager", None)
            if session_mgr is not None:
                session_mgr.set_clock(int(__import__("time").monotonic() * 1000))
                session_mgr.touch(sid)

            # Refresh phantom activity so drain thread keeps channel alive
            with self._hls_activity_lock:
                self._hls_last_activity[channel_id] = __import__("time").monotonic()

            ring_count = ring.count() if ring is not None else 0
            self._hls_diag_record(
                channel_id,
                "HLS_SERVE_SNAPSHOT",
                req_id=req_id,
                path="manifest",
                status=200,
                ring_count=ring_count,
                is_active=is_active,
            )
            if self._hls_diag_is_active(channel_id):
                self._logger.warning(
                    "[HLS-DIAG][%s] HLS_SERVE_SNAPSHOT req_id=%s status=200 ring_count=%d active=%s",
                    channel_id, req_id, ring_count, is_active,
                )


            return Response(
                content=playlist,
                media_type="application/vnd.apple.mpegurl",
                headers={
                    "Cache-Control": "no-cache, max-age=0",
                    "Access-Control-Allow-Origin": "*",
                },
            )

        @self.fastapi_app.get("/channels/{channel_id}/seg_{index}.ts")
        async def channels_hls_segment(
            channel_id: str,
            index: int,
            session: str | None = None,
        ) -> Response:
            """Serve an HLS segment from the canonical SegmentRing.

            INV-HLS-SERVE-BYTE-IDENTITY-001: Exact bytes from ring, no transformation.
            INV-HLS-ENDPOINT-SESSION-TOUCH-001: Touch on success only.
            INV-HLS-QUIET-POLLING-001: No INFO logging per request.
            """
            req_id = uuid.uuid4().hex[:10]
            mgr = self._resolve_channel_manager(channel_id)
            if mgr is None:
                return Response(content="Channel not found", status_code=404)

            ring = getattr(mgr, "hls_segment_ring", None)
            if ring is None:
                return Response(content="Not found", status_code=404)

            segment = ring.get(index)
            if segment is None:
                self._hls_diag_record(channel_id, "HLS_SEGMENT_SERVE", req_id=req_id, index=index, status=404)

                # Derive claimed manifest window + hash for correlation payload.
                gen = getattr(mgr, "hls_manifest_generator", None)
                playlist = gen.generate(ring) if gen is not None else None
                playlist_hash = hashlib.sha1(playlist.encode("utf-8")).hexdigest()[:16] if playlist else None

                all_segments = ring.window()
                manifest_count = ring.manifest_window
                if len(all_segments) > manifest_count:
                    manifest_segments = all_segments[-manifest_count:]
                else:
                    manifest_segments = all_segments

                oldest_index = manifest_segments[0].index if manifest_segments else None
                newest_index = manifest_segments[-1].index if manifest_segments else None
                media_sequence = oldest_index

                unexpected_404 = (
                    oldest_index is not None
                    and newest_index is not None
                    and oldest_index <= index <= newest_index
                )
                if unexpected_404:
                    # Trigger immediately on FIRST unexpected in-window segment miss.
                    self._hls_diag_trigger(
                        channel_id,
                        "unexpected_segment_404_first",
                        req_id=req_id,
                        requested_index=index,
                        oldest_index=oldest_index,
                        newest_index=newest_index,
                        media_sequence=media_sequence,
                        playlist_hash=playlist_hash,
                    )

                self._hls_diag_note_reconnect_attempt(channel_id, reason="segment_404")
                return Response(content="Not found", status_code=404)

            # INV-HLS-ENDPOINT-SESSION-TOUCH-001: Touch on success only
            session_mgr = getattr(mgr, "hls_session_manager", None)
            if session_mgr is not None:
                sid = session or f"hls-anon-{uuid.uuid4().hex[:8]}"
                session_mgr.set_clock(int(__import__("time").monotonic() * 1000))
                session_mgr.touch(sid)

            # Refresh phantom activity so drain thread keeps channel alive
            with self._hls_activity_lock:
                self._hls_last_activity[channel_id] = __import__("time").monotonic()

            self._hls_diag_record(
                channel_id,
                "HLS_SEGMENT_SERVE",
                req_id=req_id,
                index=index,
                status=200,
                bytes=segment.byte_count,
                wall_clock_ms=segment.wall_clock_start_utc_ms,
                duration_ms=segment.duration_ms,
            )
            if self._hls_diag_is_active(channel_id):
                self._logger.warning(
                    "[HLS-DIAG][%s] HLS_SEGMENT_SERVE req_id=%s idx=%d status=200 bytes=%d wall=%d dur=%d",
                    channel_id, req_id, index, segment.byte_count,
                    segment.wall_clock_start_utc_ms, segment.duration_ms,
                )

            return Response(
                content=segment.data,
                media_type="video/mp2t",
                headers={
                    "Content-Length": str(segment.byte_count),
                    "Cache-Control": "public, max-age=60",
                    "Access-Control-Allow-Origin": "*",
                },
            )

        @self.fastapi_app.get("/watch/{channel_id}", response_class=HTMLResponse)
        async def watch_channel(channel_id: str) -> HTMLResponse:
            """Serve the HLS web player page."""
            import json as _json
            html_path = Path("/opt/retrovue/pkg/core/templates/player/watch.html")
            html = html_path.read_text()

            channel_name = channel_id
            channel_buttons = ""
            try:
                channels = self._load_channels_list()
                for ch in channels:
                    if ch["channel_id"] == channel_id:
                        channel_name = ch["name"]
                    active = " active" if ch["channel_id"] == channel_id else ""
                    channel_buttons += '<a href="/watch/' + ch["channel_id"] + '" class="' + active.strip() + '">' + ch["name"] + '</a>\n'
            except Exception:
                channel_buttons = '<a href="/watch/' + channel_id + '" class="active">' + channel_id + '</a>'

            html = html.replace("{{CHANNEL_ID}}", channel_id)
            html = html.replace("{{CHANNEL_NAME}}", channel_name)
            html = html.replace("{{CHANNEL_BUTTONS}}", channel_buttons)
            return HTMLResponse(content=html)

        @self.fastapi_app.get("/epg", response_class=HTMLResponse)
        def epg_guide_html() -> HTMLResponse:
            """Serve the EPG HTML page."""
            html_path = Path("/opt/retrovue/pkg/core/templates") / "epg" / "guide.html"
            return HTMLResponse(content=html_path.read_text())

        # --- IPTV Guide (no M3U playlist: Plex uses HDHomeRun discover/lineup only) ---

        @self.fastapi_app.get("/iptv/guide.xml")
        def get_xmltv_guide(
            request: Request,
            date: Optional[str] = None,
        ) -> Response:
            """XMLTV electronic program guide for IPTV clients.

            Plain def (not async) to avoid blocking the event loop during
            schedule compilation (INV-EPG-NONAUTHORITATIVE-FOR-PLAYOUT-001).
            Reuses the same EPG compilation path as /api/epg.
            Contract: observable freshness (ETag/Last-Modified) when guide changes.
            """
            import hashlib
            from datetime import date as _date_type
            from email.utils import formatdate
            from retrovue.web.iptv import generate_xmltv

            channels = self._load_channels_list()
            # EPG/XMLTV horizon invariant: at least 48h future; fetch multiple broadcast days
            first = get_epg_all(date=date)
            entries = [e for e in first.get("entries", []) if "error" not in e]
            bd_str = first.get("broadcast_day")
            if bd_str:
                bd = _date_type.fromisoformat(bd_str)
                for delta_days in (1, 2):
                    next_result = get_epg_all(date=(bd + timedelta(days=delta_days)).strftime("%Y-%m-%d"))
                    entries.extend(
                        e for e in next_result.get("entries", []) if "error" not in e
                    )

            base_url = str(request.base_url).rstrip("/")
            xml_str = generate_xmltv(channels, entries, base_url=base_url)
            full_content = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str

            # XMLTV refresh invariant: cache validators so Plex detects freshness
            etag = hashlib.sha256(full_content.encode()).hexdigest()
            last_modified = formatdate(usegmt=True)

            return Response(
                content=full_content,
                media_type="application/xml",
                headers={
                    "ETag": f'"{etag}"',
                    "Last-Modified": last_modified,
                },
            )

        # --- Artwork for Plex guide (posters / channel logos) ---
        # Minimal valid 1x1 JPEG placeholder when no artwork is configured
        _PLACEHOLDER_JPEG_B64 = "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="
        _PLACEHOLDER_JPEG = __import__("base64").b64decode(_PLACEHOLDER_JPEG_B64)

        @self.fastapi_app.get("/art/program/{program_id}.jpg")
        def art_program(program_id: str) -> Response:
            """Programme poster for XMLTV/Plex. Proxies image from upstream source.

            INV-PLEX-ARTWORK-001: Serves artwork by proxying the persisted
            thumb_url through RetroVue rather than redirecting to the upstream
            server.  Plex guide clients do not reliably follow redirects back
            to their own server.
            """
            import requests as _requests
            from retrovue.infra.uow import session
            from retrovue.web.artwork import resolve_programme_poster_url

            try:
                asset_uuid = uuid.UUID(program_id)
            except ValueError:
                return Response(content=_PLACEHOLDER_JPEG, media_type="image/jpeg")

            with session() as db:
                url = resolve_programme_poster_url(asset_uuid, db)
            if not url:
                return Response(content=_PLACEHOLDER_JPEG, media_type="image/jpeg")

            # Proxy the image from upstream instead of redirecting.
            try:
                upstream = _requests.get(url, timeout=10, verify=False)
                upstream.raise_for_status()
                return Response(
                    content=upstream.content,
                    media_type=upstream.headers.get("content-type", "image/jpeg"),
                    headers={"Cache-Control": "public, max-age=86400"},
                )
            except Exception:
                return Response(content=_PLACEHOLDER_JPEG, media_type="image/jpeg")

        @self.fastapi_app.get("/art/channel/{channel_id}.jpg")
        def art_channel(channel_id: str) -> Response:
            """Channel logo for XMLTV/Plex. Placeholder until channel artwork is configured."""
            return Response(
                content=_PLACEHOLDER_JPEG,
                media_type="image/jpeg",
            )

        # --- Block IPTV playlist paths (Plex discovery surface invariant) ---
        # Return 404 for common M3U paths so Plex does not register a second
        # device or phantom tuner. Tuner discovery is HDHomeRun only.

        @self.fastapi_app.get("/channels.m3u8")
        def _block_channels_m3u8() -> Response:
            return Response(status_code=status.HTTP_404_NOT_FOUND)

        @self.fastapi_app.get("/channels.m3u")
        def _block_channels_m3u() -> Response:
            return Response(status_code=status.HTTP_404_NOT_FOUND)

        @self.fastapi_app.get("/playlist.m3u")
        def playlist_m3u(request: Request) -> Response:
            """IPTV channel list pointing to canonical HLS manifests."""
            return self._generate_iptv_m3u(request)

        # --- Plex HDHomeRun Virtual Tuner Endpoints ---
        # INV-PLEX-DISCOVERY-001, INV-PLEX-LINEUP-001,
        # INV-PLEX-TUNER-STATUS-001, INV-PLEX-XMLTV-001
        # These endpoints present existing RetroVue services in HDHomeRun
        # format so Plex discovers channels via its DVR tuner protocol.

        @self.fastapi_app.get("/discover.json")
        def plex_discover(request: Request):
            """HDHomeRun device discovery — INV-PLEX-DISCOVERY-001."""
            from retrovue.integrations.plex.models import make_discover_payload

            base_url = str(request.base_url).rstrip("/")
            return make_discover_payload(
                base_url=base_url,
            )

        @self.fastapi_app.get("/lineup.json")
        def plex_lineup(request: Request):
            """HDHomeRun channel lineup — INV-PLEX-LINEUP-001 (ascending GuideNumber order)."""
            from retrovue.integrations.plex.models import make_lineup_entry

            channels = self._load_channels_list()
            base_url = str(request.base_url).rstrip("/")
            # Channel ordering invariant: ascending GuideNumber
            sort_key = lambda ch: ch.get("number", ch.get("channel_id_int", 0))
            sorted_channels = sorted(channels, key=sort_key)
            return [
                make_lineup_entry(
                    channel_id=ch["channel_id"],
                    channel_name=ch["name"],
                    base_url=base_url,
                    guide_number=ch.get("number", ch.get("channel_id_int")),
                )
                for ch in sorted_channels
            ]

        @self.fastapi_app.get("/lineup_status.json")
        def plex_lineup_status():
            """Tuner scan status — INV-PLEX-TUNER-STATUS-001."""
            from retrovue.integrations.plex.models import LINEUP_STATUS

            return dict(LINEUP_STATUS)


        @self.fastapi_app.get("/test/block/{block_id}.ts")
        async def test_block_stream(request: Request, block_id: str) -> Response:
            from retrovue.runtime.test_playout_endpoint import (
                EphemeralTestSession, _make_test_channel_config,
                load_channel_slug_for_block,
            )
            from retrovue.runtime.channel_stream import generate_ts_stream_async
            session_id = str(uuid.uuid4())

            # INV-TEST-BLOCK-008: Derive channel config from the block's owning channel.
            # PlaylistEvent.channel_slug is the authoritative link — no guessing.
            channel_config = None
            try:
                slug = load_channel_slug_for_block(block_id)
                if slug and self._channel_config_provider is not None:
                    channel_config = self._channel_config_provider.get_channel_config(slug)
            except Exception:
                pass
            channel_config = _make_test_channel_config(channel_config)
            test_session = EphemeralTestSession(block_id=block_id, session_id=session_id)
            try:
                test_session.start(channel_config)
            except RuntimeError as e:
                return Response(
                    content=str(e),
                    status_code=(
                        status.HTTP_404_NOT_FOUND
                        if "not found" in str(e).lower()
                        else status.HTTP_503_SERVICE_UNAVAILABLE
                    ),
                )
            client_queue = test_session.subscribe(session_id)
            cleaned = []
            def cleanup(*, reason: str = "unknown") -> None:
                if cleaned:
                    return
                cleaned.append(1)
                test_session.unsubscribe(session_id)
                test_session.stop()
            asyncio.create_task(_wait_disconnect_then_cleanup(
                request, lambda: cleanup(reason="asgi_receive")))
            async def generate_stream():
                try:
                    async for chunk in generate_ts_stream_async(client_queue):
                        yield chunk
                except GeneratorExit:
                    cleanup(reason="generator_exit")
                    return
                except asyncio.CancelledError:
                    cleanup(reason="cancelled")
                    return
                finally:
                    cleanup(reason="generator_finally")
            return StreamingResponse(
                generate_stream(),
                media_type="video/mpeg",
                headers={"Connection": "close", "Cache-Control": "no-cache",
                         "X-Accel-Buffering": "no"},
            )

        @self.fastapi_app.post("/lineup.post")
        def plex_lineup_post():
            """Plex channel scan trigger (POST) — no-op for virtual tuner."""
            return Response(status_code=200)

    def _start_http_server(self) -> None:
        """Start the HTTP server in a background thread."""
        if self._server_thread and self._server_thread.is_alive():
            self._logger.debug("HTTP server already running")
            return

        def _run_server():
            try:
                logging.getLogger("uvicorn.access").addFilter(HLSAccessFilter())
                config = Config(self.fastapi_app, host=self.host, port=self.port, log_level="info")
                self._server = Server(config)
                self._logger.info("ProgramDirector HTTP server starting on %s:%s", self.host, self.port)
                self._server.run()
            except Exception as e:
                self._logger.error("HTTP server error: %s", e)

        self._server_thread = Thread(target=_run_server, name="program-director-http", daemon=True)
        self._server_thread.start()
        self._logger.debug("ProgramDirector HTTP server thread started")

    def _stop_http_server(self) -> None:
        """Stop the HTTP server."""
        if self._server:
            self._server.should_exit = True
        
        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=2.0)
            if self._server_thread.is_alive():
                self._logger.warning("HTTP server thread did not stop cleanly")
            self._server_thread = None
