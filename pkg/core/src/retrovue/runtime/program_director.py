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

import asyncio
import logging
import os
import queue
import threading
import time
import uuid
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
    BLOCKPLAN_SCHEDULE_SOURCE,
    ChannelConfig,
    ChannelConfigProvider,
    DEFAULT_PROGRAM_FORMAT,
    InlineChannelConfigProvider,
)
from retrovue.runtime.schedule_manager_service import ScheduleManagerBackedScheduleService

try:
    from retrovue.runtime.settings import RuntimeSettings  # type: ignore
except ImportError:  # pragma: no cover - settings optional
    RuntimeSettings = None  # type: ignore


from retrovue.streaming.hls_writer import HLSManager, HLS_BASE_DIR
from fastapi.responses import FileResponse

class SystemMode(Enum):
    """System-wide operational modes"""

    NORMAL = "normal"
    EMERGENCY = "emergency"
    MAINTENANCE = "maintenance"
    RECOVERY = "recovery"


class ChannelStatus(Enum):
    """Status of individual channels"""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class SystemHealth:
    """System health and performance metrics"""

    total_channels: int
    active_channels: int
    total_viewers: int
    system_mode: SystemMode
    last_health_check: datetime
    alerts: list[str]


@dataclass
class ChannelInfo:
    """Information about a channel's runtime state"""

    channel_id: str
    name: str
    status: ChannelStatus
    viewer_count: int
    producer_mode: str
    last_activity: datetime


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


# ---------------------------------------------------------------------------
# Horizon adapters — bridge ScheduleManagerBackedScheduleService to HorizonManager protocols
# ---------------------------------------------------------------------------


class _EpgHorizonExtender:
    """Adapts ScheduleManagerBackedScheduleService for HorizonManager's ScheduleExtender protocol.

    Checks the resolved store for existence and calls
    ScheduleManager.resolve_schedule_day() to extend EPG.
    """

    def __init__(self, schedule_service: ScheduleManagerBackedScheduleService, channel_id: str):
        self._service = schedule_service
        self._channel_id = channel_id

    def epg_day_exists(self, broadcast_date) -> bool:
        return self._service._resolved_store.exists(self._channel_id, broadcast_date)

    def extend_epg_day(self, broadcast_date) -> None:
        slots = self._service._schedules.get(self._channel_id, [])
        if not slots:
            return
        resolution_time = datetime(
            broadcast_date.year, broadcast_date.month, broadcast_date.day,
            5, 0, 0, tzinfo=timezone.utc,
        )
        self._service._manager.resolve_schedule_day(
            channel_id=self._channel_id,
            programming_day_date=broadcast_date,
            slots=slots,
            resolution_time=resolution_time,
        )


class _ExecutionHorizonExtender:
    """Adapts ScheduleManagerBackedScheduleService for HorizonManager's ExecutionExtender protocol.

    Generates ExecutionEntry objects from resolved schedule data
    without requiring the full planning pipeline infrastructure.
    Ensures the broadcast date is resolved first, then builds
    execution entries from ScheduleManager's program blocks.
    Writes transmission log artifact (.tlog + .tlog.jsonl) when extending.
    """

    def __init__(
        self,
        schedule_service: ScheduleManagerBackedScheduleService,
        channel_id: str,
        timezone_display: str = "UTC",
    ):
        self._service = schedule_service
        self._channel_id = channel_id
        self._timezone_display = timezone_display
        self._logger = logging.getLogger(__name__)

    def extend_execution_day(self, broadcast_date):
        from retrovue.runtime.execution_window_store import (
            ExecutionDayResult,
            ExecutionEntry,
        )

        # Ensure day is resolved
        if not self._service._resolved_store.exists(self._channel_id, broadcast_date):
            slots = self._service._schedules.get(self._channel_id, [])
            if slots:
                resolution_time = datetime(
                    broadcast_date.year, broadcast_date.month, broadcast_date.day,
                    5, 0, 0, tzinfo=timezone.utc,
                )
                self._service._manager.resolve_schedule_day(
                    channel_id=self._channel_id,
                    programming_day_date=broadcast_date,
                    slots=slots,
                    resolution_time=resolution_time,
                )

        # Build execution entries from resolved program blocks
        grid_minutes = self._service._grid_minutes
        day_start_hour = self._service._programming_day_start_hour

        day_start = datetime(
            broadcast_date.year, broadcast_date.month, broadcast_date.day,
            day_start_hour, 0, 0, tzinfo=timezone.utc,
        )
        day_end = day_start + timedelta(days=1)

        entries = []
        block_idx = 0
        current = day_start
        while current < day_end:
            block = self._service._manager.get_program_at(self._channel_id, current)
            start_ms = int(current.timestamp() * 1000)
            end_ms = start_ms + grid_minutes * 60 * 1000

            block_dur_ms = grid_minutes * 60 * 1000
            segments = []
            if block and block.segments:
                for seg in block.segments:
                    segments.append({
                        "asset_uri": seg.file_path,
                        "asset_start_offset_ms": int(seg.seek_offset_seconds * 1000),
                        "segment_duration_ms": int(seg.duration_seconds * 1000),
                        "segment_type": "episode",
                    })

            # Pad to fill block — this is a planning decision, not AIR's job.
            # AIR must receive a gap-free segment list that sums to block_dur_ms.
            content_ms = sum(s["segment_duration_ms"] for s in segments)
            pad_ms = block_dur_ms - content_ms
            if pad_ms > 0:
                segments.append({
                    "segment_duration_ms": pad_ms,
                    "segment_type": "pad",
                })

            entries.append(ExecutionEntry(
                block_id=f"{self._channel_id}-{broadcast_date.isoformat()}-b{block_idx:04d}",
                block_index=block_idx,
                start_utc_ms=start_ms,
                end_utc_ms=end_ms,
                segments=segments,
            ))

            current += timedelta(minutes=grid_minutes)
            block_idx += 1

        end_ms = entries[-1].end_utc_ms if entries else 0
        self._logger.info(
            "ExecutionHorizonExtender: Generated %d entries for %s (end_utc_ms=%d)",
            len(entries), broadcast_date.isoformat(), end_ms,
        )

        # Write transmission log artifact (TL-ART-001: write-once; ignore if exists)
        if entries:
            self._write_transmission_log_artifact(broadcast_date, entries)

        return ExecutionDayResult(end_utc_ms=end_ms, entries=entries)

    def _write_transmission_log_artifact(self, broadcast_date, entries):
        """Build TransmissionLog from entries and write .tlog + .tlog.jsonl."""
        from retrovue.planning.transmission_log_artifact_writer import (
            TransmissionLogArtifactExistsError,
            TransmissionLogArtifactWriter,
        )
        from retrovue.runtime.planning_pipeline import TransmissionLog, TransmissionLogEntry

        grid_minutes = self._service._grid_minutes
        tl_entries = [
            TransmissionLogEntry(
                block_id=e.block_id,
                block_index=e.block_index,
                start_utc_ms=e.start_utc_ms,
                end_utc_ms=e.end_utc_ms,
                segments=e.segments,
            )
            for e in entries
        ]
        lock_time = datetime(
            broadcast_date.year, broadcast_date.month, broadcast_date.day,
            5, 0, 0, tzinfo=timezone.utc,
        )
        transmission_log = TransmissionLog(
            channel_id=self._channel_id,
            broadcast_date=broadcast_date,
            entries=tl_entries,
            is_locked=True,
            metadata={
                "grid_block_minutes": grid_minutes,
                "locked_at": lock_time.isoformat(),
            },
        )
        writer = TransmissionLogArtifactWriter()
        try:
            path = writer.write(
                channel_id=self._channel_id,
                broadcast_date=broadcast_date,
                transmission_log=transmission_log,
                timezone_display=self._timezone_display,
                generated_utc=lock_time,
            )
            self._logger.info(
                "Transmission log artifact written: %s", path,
            )
        except TransmissionLogArtifactExistsError:
            self._logger.debug(
                "Transmission log artifact already exists for %s %s (TL-ART-001)",
                self._channel_id, broadcast_date.isoformat(),
            )


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
        # Phase 5: Per-channel schedule services
        self._schedule_manager_services: dict[str, ScheduleManagerBackedScheduleService] = {}
        # Horizon management
        self._horizon_managers: dict[str, Any] = {}
        self._horizon_execution_stores: dict[str, Any] = {}
        self._horizon_resolved_stores: dict[str, Any] = {}
        # Playlog Horizon Daemons (Tier 2 — INV-PLAYLOG-HORIZON-001)
        self._playlog_daemons: dict[str, Any] = {}
        self._channel_config_provider: Optional[Any] = None
        self._health_check_stop: Optional[threading.Event] = None
        self._health_check_thread: Optional[Thread] = None
        # P11D-009: boundaries are feasible at planning time; 1s tick cadence is sufficient
        self._health_check_interval_seconds = 1.0
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
        
        # Phase 0: System mode
        self._system_mode = SystemMode.NORMAL

        # HLS Manager
        self._hls_manager = HLSManager()
        # HLS activity tracking: channel_id -> last fetch timestamp (time.monotonic)
        self._hls_last_activity: dict[str, float] = {}
        self._hls_phantom_sessions: dict[str, str] = {}  # channel_id -> hls_session_id
        self._hls_activity_lock = threading.Lock()

        # Evidence pipeline configuration
        self._evidence_enabled = True
        self._evidence_port = 50052
        self._evidence_asrun_dir = "/opt/retrovue/data/logs/asrun"
        self._evidence_ack_dir = "/opt/retrovue/data/logs/asrun/acks"
        self._evidence_endpoint = f"127.0.0.1:{self._evidence_port}" if self._evidence_enabled else ""
        self._evidence_server = None
        
        # Register HTTP endpoints
        self._register_endpoints()
        
        self._logger.debug(
            "ProgramDirector initialized with target_hz=%s clock=%s host=%s port=%s",
            self._pace.target_hz,
            type(self._clock).__name__,
            host,
            port,
        )

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
                        'channel_id_int': cfg.channel_id_int,
                        'name': cfg.name,
                        'schedule_config': cfg.schedule_config,
                    })
            return result
        else:
            from pathlib import Path
            channels_path = Path('/opt/retrovue/config/channels.json')
            with open(channels_path) as f:
                return _json.load(f)['channels']

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
                channel_id_int=1,
                name="Test A/B",
                program_format=DEFAULT_PROGRAM_FORMAT,
                schedule_source=BLOCKPLAN_SCHEDULE_SOURCE,
                schedule_config={},
            )
            self._channel_config_provider = InlineChannelConfigProvider([test1_config])

        self._health_check_stop = threading.Event()

    def _ensure_schedule_manager_service(
        self, channel_id: str, channel_config: ChannelConfig,
    ) -> ScheduleManagerBackedScheduleService:
        """Get or create the ScheduleManagerBackedScheduleService for a channel.

        Always returns the ScheduleManagerBackedScheduleService (not the horizon-backed one).
        Used by both the normal schedule-service routing and by
        _init_horizon_managers() which needs the underlying service
        regardless of horizon mode.
        """
        if channel_id not in self._schedule_manager_services:
            schedule_config = channel_config.schedule_config
            programs_dir = Path(schedule_config.get("programs_dir", "/opt/retrovue/config/programs"))
            schedules_dir = Path(schedule_config.get("schedules_dir", "/opt/retrovue/config/schedules"))
            filler_path = schedule_config.get("filler_path", "/opt/retrovue/assets/filler.mp4")
            filler_duration = schedule_config.get("filler_duration_seconds", 3650.0)
            grid_minutes = schedule_config.get("grid_minutes", 30)

            self._logger.info(
                "[channel %s] Creating ScheduleManagerBackedScheduleService "
                "(schedule_source=%s)",
                channel_id,
                channel_config.schedule_source,
            )

            service = ScheduleManagerBackedScheduleService(
                clock=self._embedded_clock,
                programs_dir=programs_dir,
                schedules_dir=schedules_dir,
                filler_path=filler_path,
                filler_duration_seconds=filler_duration,
                grid_minutes=grid_minutes,
            )
            self._schedule_manager_services[channel_id] = service

        return self._schedule_manager_services[channel_id]

    def _get_schedule_service_for_channel(self, channel_id: str, channel_config: ChannelConfig) -> Any:
        """
        Get appropriate schedule service based on channel config and horizon mode.

        INV-P5-001: Config-Driven Activation - schedule_source: "phase3" enables Phase 3 mode.
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

        schedule_source = channel_config.schedule_source
        if schedule_source == "phase3":
            return self._get_horizon_backed_service(channel_id, channel_config)
        if schedule_source == "dsl":
            return self._get_dsl_service(channel_id, channel_config)

        raise ValueError(
            f"No schedule service for schedule_source={schedule_source!r}"
        )

    def _get_dsl_service(self, channel_id: str, channel_config: "ChannelConfig") -> Any:
        """Create or return a DslScheduleService for DSL-backed channels."""
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
        )
        ok, err = svc.load_schedule(channel_id)
        if not ok:
            raise ValueError(f"Failed to load DSL schedule for {channel_id}: {err}")

        setattr(self, key, svc)
        return svc

    def _get_horizon_backed_service(self, channel_id: str, channel_config: ChannelConfig) -> Any:
        """Create or return a HorizonBackedScheduleService for phase3 channels."""
        from retrovue.runtime.horizon_backed_schedule_service import HorizonBackedScheduleService

        # Return cached if exists
        key = f"_hbs_{channel_id}"
        cached = getattr(self, key, None)
        if cached is not None:
            return cached

        schedule_config = channel_config.schedule_config
        grid_minutes = schedule_config.get("grid_minutes", 30)
        execution_store = self._horizon_execution_stores.get(channel_id)
        resolved_store = self._horizon_resolved_stores.get(channel_id)

        if execution_store is None:
            self._logger.warning(
                "[channel %s] No execution store in authoritative mode. "
                "HorizonManager may not be initialized yet.",
                channel_id,
            )

        service = HorizonBackedScheduleService(
            execution_store=execution_store,
            resolved_store=resolved_store,
            grid_block_minutes=grid_minutes,
            channel_id=channel_id,
        )
        setattr(self, key, service)
        return service

    def _init_horizon_managers(self) -> None:
        """Create and start HorizonManagers for Phase3 channels.

        Called from start().  For each
        Phase3 channel:
        1. Creates ScheduleManagerBackedScheduleService and loads the schedule
        2. Creates ExecutionWindowStore
        3. Creates ScheduleExtender / ExecutionExtender adapters
        4. Creates HorizonManager and runs evaluate_once() (readiness gate)
        5. Locks all initial entries and starts the background thread
        """
        if self._channel_config_provider is None:
            return

        if not hasattr(self._channel_config_provider, "list_channel_ids"):
            self._logger.warning(
                "Channel config provider does not support list_channel_ids; "
                "cannot initialize horizon managers",
            )
            return

        from retrovue.runtime.execution_window_store import ExecutionWindowStore
        from retrovue.runtime.horizon_manager import HorizonManager

        for channel_id in self._channel_config_provider.list_channel_ids():
            config = self._channel_config_provider.get_channel_config(channel_id)
            if config is None or config.schedule_source != "phase3":
                continue

            self._logger.info(
                "[channel %s] Initializing HorizonManager",
                channel_id,
            )

            # Ensure ScheduleManagerBackedScheduleService exists (always needed for adapters)
            phase3_service = self._ensure_schedule_manager_service(channel_id, config)
            phase3_service.load_schedule(channel_id)

            # Create stores
            execution_store = ExecutionWindowStore()
            self._horizon_execution_stores[channel_id] = execution_store
            self._horizon_resolved_stores[channel_id] = phase3_service._resolved_store

            schedule_config = config.schedule_config

            # Create adapters
            schedule_extender = _EpgHorizonExtender(phase3_service, channel_id)
            execution_extender = _ExecutionHorizonExtender(
                phase3_service,
                channel_id,
                timezone_display=schedule_config.get("timezone_display", "UTC"),
            )

            # Create HorizonManager
            horizon_mgr = HorizonManager(
                schedule_manager=schedule_extender,
                planning_pipeline=execution_extender,
                master_clock=self._embedded_clock,
                min_epg_days=schedule_config.get("min_epg_days", 3),
                min_execution_hours=schedule_config.get("min_execution_hours", 6),
                evaluation_interval_seconds=schedule_config.get(
                    "horizon_eval_interval_seconds", 30,
                ),
                programming_day_start_hour=schedule_config.get(
                    "programming_day_start_hour", 6,
                ),
                execution_store=execution_store,
            )

            # Readiness gate: synchronous initial evaluation
            horizon_mgr.evaluate_once()
            report = horizon_mgr.get_health_report()
            self._logger.info(
                "[channel %s] HorizonManager readiness gate: "
                "healthy=%s epg=%.1fh exec=%.1fh store_entries=%d",
                channel_id,
                report.is_healthy,
                report.epg_depth_hours,
                report.execution_depth_hours,
                report.store_entry_count,
            )

            if not report.is_healthy:
                raise RuntimeError(
                    f"[channel {channel_id}] HorizonManager readiness gate "
                    f"FAILED. epg={report.epg_depth_hours:.1f}h "
                    f"exec={report.execution_depth_hours:.1f}h "
                    f"(min_epg={report.min_epg_days}d "
                    f"min_exec={report.min_execution_hours}h). "
                    f"Cannot start with insufficient horizon depth.",
                )

            # Lock all initial entries for execution
            locked = execution_store.lock_all()
            if locked:
                self._logger.info(
                    "[channel %s] Locked %d execution entries", channel_id, locked,
                )

            # Start background evaluation thread
            horizon_mgr.start()
            self._horizon_managers[channel_id] = horizon_mgr

        self._logger.info(
            "HorizonManagers initialized: %d channels",
            len(self._horizon_managers),
        )

    def _init_playlog_daemons(self) -> None:
        """Create and start PlaylogHorizonDaemons for DSL channels.

        INV-PLAYLOG-HORIZON-001: Each DSL channel gets a daemon that
        maintains 2-3+ hours of fully-filled playout logs in
        TransmissionLog (Postgres).

        Called from start(), after _init_horizon_managers.
        """
        if self._channel_config_provider is None:
            return

        if not hasattr(self._channel_config_provider, "list_channel_ids"):
            return

        from retrovue.runtime.playlog_horizon_daemon import PlaylogHorizonDaemon

        for channel_id in self._channel_config_provider.list_channel_ids():
            config = self._channel_config_provider.get_channel_config(channel_id)
            if config is None:
                continue
            # Only DSL channels for now (phase3 uses ExecutionWindowStore path)
            if config.schedule_source != "dsl":
                continue

            # Warm Tier 1 (CompiledProgramLog) so the daemon can extend Tier 2.
            # _get_schedule_service_for_channel (→ _get_dsl_service) calls
            # load_schedule(channel_id), which compiles and caches Tier 1. Without
            # this, DSL channels that have never had a viewer would have empty
            # Tier 1 and the daemon would log INV-PLAYLOG-HORIZON-002.
            try:
                self._get_schedule_service_for_channel(channel_id, config)
            except Exception as e:
                self._logger.warning(
                    "PlaylogHorizon[%s]: Tier 1 warm failed: %s",
                    channel_id, e, exc_info=True,
                )

            sc = config.schedule_config or {}

            daemon = PlaylogHorizonDaemon(
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
            )

            # Readiness gate: synchronous initial evaluation
            blocks_filled = daemon.evaluate_once()
            report = daemon.get_health_report()
            self._logger.info(
                "PlaylogHorizon[%s]: readiness gate — "
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
            "PlaylogHorizonDaemons initialized: %d channels",
            len(self._playlog_daemons),
        )

    def _get_or_create_manager(self, channel_id: str) -> Any:
        """Get or create ChannelManager for a channel (embedded mode). PD is sole authority for creation."""
        with self._managers_lock:
            if channel_id not in self._managers:
                channel_config = self._channel_config_provider.get_channel_config(channel_id)
                if channel_config is None:
                    raise ValueError(
                        f"[channel {channel_id}] No channel config found; "
                        "blockplan-only mode requires config for each channel."
                    )

                # INV-P5-001: Select schedule service based on channel config
                schedule_service = self._get_schedule_service_for_channel(channel_id, channel_config)

                success, error = schedule_service.load_schedule(channel_id)
                if not success:
                    from retrovue.runtime.channel_manager import ChannelManagerError
                    raise ChannelManagerError(f"Failed to load schedule for {channel_id}: {error}")
                from retrovue.runtime.channel_manager import ChannelManager
                manager = ChannelManager(
                    channel_id=channel_id,
                    clock=self._embedded_clock,
                    schedule_service=schedule_service,
                    program_director=self,
                    evidence_endpoint=self._evidence_endpoint,
                )
                manager.channel_config = channel_config
                if self._mock_schedule_grid_mode:
                    manager._mock_grid_block_minutes = 30
                    manager._mock_grid_program_asset_path = self._program_asset_path
                    manager._mock_grid_filler_asset_path = self._filler_asset_path
                    manager._mock_grid_filler_epoch = datetime(
                        2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc
                    )
                cfg = channel_config
                # ChannelManager always uses BlockPlanProducer.
                _cm_build = ChannelManager._build_producer_for_mode

                def factory_wrapper(mode: str, cfg: ChannelConfig = cfg) -> Optional[Any]:
                    return _cm_build(manager, mode)
                manager._build_producer_for_mode = factory_wrapper
                self._managers[channel_id] = manager
                self._logger.info(
                    "[channel %s] ChannelManager created (channel_id_int=%d)",
                    channel_id,
                    channel_config.channel_id_int,
                )
            return self._managers[channel_id]

    def _health_check_loop(self) -> None:
        """Run check_health() and tick() on each registered ChannelManager (embedded mode)."""
        while (
            self._health_check_stop is not None
            and not self._health_check_stop.wait(timeout=self._health_check_interval_seconds)
        ):
            try:
                with self._managers_lock:
                    managers = list(self._managers.values())
                deferred_destroy: list[str] = []
                for manager in managers:
                    try:
                        manager.check_health()
                        manager.tick()
                        # P12-CORE-006: Poll for deferred teardown completion; destroy channel when ready
                        if getattr(manager, "deferred_teardown_triggered", lambda: False)() is True:
                            deferred_destroy.append(manager.channel_id)
                    except Exception as e:
                        self._logger.warning(
                            "Health check failed for channel %s: %s",
                            getattr(manager, "channel_id", "?"),
                            e,
                            exc_info=True,
                        )
                for channel_id in deferred_destroy:
                    self._logger.info(
                        "[channel %s] Deferred teardown ready; destroying ChannelManager",
                        channel_id,
                    )
                    self._stop_channel_internal(channel_id)
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

    def stop_channel(self, channel_id: str) -> None:
        """Stop channel and remove from registry (provider protocol; when embedded, PD is sole authority)."""
        if self._channel_manager_provider is not None:
            self._channel_manager_provider.stop_channel(channel_id)
        else:
            self._stop_channel_internal(channel_id)

    def has_channel_stream(self, channel_id: str) -> bool:
        """Return True if this channel has an active ChannelStream (for tests)."""
        if self._channel_manager_provider is not None:
            if hasattr(self._channel_manager_provider, "has_channel_stream"):
                return self._channel_manager_provider.has_channel_stream(channel_id)
            return False
        with self._fanout_lock:
            return channel_id in self._fanout_buffers

    def _stop_channel_internal(self, channel_id: str) -> None:
        """Stop channel and remove from registry (embedded mode). PD is sole authority for teardown."""
        with self._pre_warmed_lock:
            timer = self._pre_warmed_timers.pop(channel_id, None)
        if timer:
            timer.cancel()
        with self._managers_lock:
            manager = self._managers.get(channel_id)
        if manager is not None:
            self._logger.info("[channel %s] ChannelManager destroyed (viewer count 0)", channel_id)
            manager.stop_channel()
            if manager.active_producer:
                self._logger.info("[channel %s] Force-stopping producer (terminating Air)", channel_id)
                try:
                    manager.active_producer.stop()
                    manager.active_producer = None
                except Exception as e:
                    self._logger.warning(
                        "Error stopping producer for channel %s: %s", channel_id, e
                    )
            with self._managers_lock:
                self._managers.pop(channel_id, None)
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
    def start(self) -> None:
        """Start the pacing loop, health-check loop (embedded), and HTTP server."""
        # Embedded mode: load schedules, init horizon managers, start health-check
        if self._channel_manager_provider is None:
            self.load_all_schedules()
            # Horizon management: create/start HorizonManagers before HTTP server
            self._init_horizon_managers()
            # Playlog Horizon Daemons: Tier 2 pre-fill for all DSL channels
            self._init_playlog_daemons()
            if self._health_check_stop is not None:
                self._health_check_stop.clear()
                self._health_check_thread = Thread(
                    target=self._health_check_loop,
                    name="program-director-health-check",
                    daemon=True,
                )
                self._health_check_thread.start()

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

    def stop(self, timeout: float = 2.0) -> None:
        """Stop the pacing loop, HTTP server, and join threads.

        Parameters
        ----------
        timeout:
            Maximum seconds to wait for threads to exit before emitting a warning.
        """
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
        
        # Stop all HLS writers
        self._hls_manager.stop_all()

        # Stop all fanout buffers
        with self._fanout_lock:
            for channel_id, fanout in list(self._fanout_buffers.items()):
                try:
                    fanout.stop()
                except Exception as e:
                    self._logger.warning("Error stopping fanout buffer for channel %s: %s", channel_id, e)
            self._fanout_buffers.clear()

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

            # Stop evidence server after AIR has been stopped (no remaining clients).
            if self._evidence_server is not None:
                try:
                    self._evidence_server.stop(grace=2.0)
                    self._logger.info("Evidence gRPC server stopped")
                except Exception as e:
                    self._logger.warning("Error stopping evidence server: %s", e)
                self._evidence_server = None

            # Stop all HorizonManagers
            for channel_id, hm in list(self._horizon_managers.items()):
                try:
                    hm.stop()
                    self._logger.info(
                        "[channel %s] HorizonManager stopped", channel_id,
                    )
                except Exception as e:
                    self._logger.warning(
                        "Error stopping HorizonManager for %s: %s", channel_id, e,
                    )
            self._horizon_managers.clear()
        else:
            # Non-embedded mode: stop evidence server (managers are external).
            if self._evidence_server is not None:
                try:
                    self._evidence_server.stop(grace=2.0)
                    self._logger.info("Evidence gRPC server stopped")
                except Exception as e:
                    self._logger.warning("Error stopping evidence server: %s", e)
                self._evidence_server = None

        self._logger.debug("ProgramDirector stopped")

    def get_system_health(self) -> SystemHealth:
        """
        Get overall system health and performance metrics.

        Returns:
            SystemHealth with current system status
        """
        # TODO: Implement system health monitoring
        # - Check all channels for health status
        # - Count total viewers across all channels
        # - Check for system alerts and issues
        # - Return comprehensive health status
        pass

    def get_channel_status(self, channel_id: str) -> ChannelInfo | None:
        """
        Get runtime status for a specific channel.

        Args:
            channel_id: Channel to check

        Returns:
            ChannelInfo for the channel, or None if not found
        """
        # TODO: Implement channel status check
        # - Get channel runtime state
        # - Check producer status and viewer count
        # - Get last activity timestamp
        # - Return channel information
        pass

    def get_all_channels(self) -> list[ChannelInfo]:
        """
        Get status for all channels in the system.

        Returns:
            List of ChannelInfo for all channels
        """
        # TODO: Implement all channels status
        # - Query all active channels
        # - Get status for each channel
        # - Return list of channel information
        pass

    def activate_emergency_mode(self, reason: str) -> bool:
        """
        Activate system-wide emergency mode.

        Args:
            reason: Reason for emergency activation

        Returns:
            True if emergency mode activated successfully
        """
        # TODO: Implement emergency mode activation
        # - Set system mode to EMERGENCY
        # - Override all channels to emergency mode
        # - Activate emergency producers
        # - Log emergency activation
        # - Return success status
        pass

    def deactivate_emergency_mode(self) -> bool:
        """
        Deactivate emergency mode and return to normal operation.

        Returns:
            True if emergency mode deactivated successfully
        """
        # TODO: Implement emergency mode deactivation
        # - Set system mode to NORMAL
        # - Restore normal channel operations
        # - Deactivate emergency producers
        # - Log emergency deactivation
        # - Return success status
        pass

    def enforce_system_policies(self) -> list[str]:
        """
        Enforce system-wide policies across all channels.

        Returns:
            List of policy violations or enforcement actions
        """
        # TODO: Implement system policy enforcement
        # - Check all channels for policy compliance
        # - Apply system-wide restrictions
        # - Enforce content and timing policies
        # - Return list of actions taken
        pass

    def coordinate_channel_operations(self) -> dict[str, Any]:
        """
        Coordinate operations across all channels.

        Returns:
            Dictionary of coordination results
        """
        # TODO: Implement channel coordination
        # - Ensure consistent operation across channels
        # - Coordinate shared resources
        # - Handle channel dependencies
        # - Return coordination results
        pass

    def monitor_system_performance(self) -> dict[str, Any]:
        """
        Monitor system performance and resource usage.

        Returns:
            Dictionary of performance metrics
        """
        # TODO: Implement performance monitoring
        # - Track resource usage across channels
        # - Monitor system performance
        # - Check for bottlenecks or issues
        # - Return performance metrics
        pass

    def handle_system_alerts(self, alerts: list[str]) -> bool:
        """
        Handle system alerts and notifications.

        Args:
            alerts: List of alerts to handle

        Returns:
            True if alerts handled successfully
        """
        # TODO: Implement alert handling
        # - Process system alerts
        # - Take appropriate actions
        # - Log alert handling
        # - Return success status
        pass

    def get_emergency_content(self) -> list[dict[str, Any]]:
        """
        Get emergency content for system-wide override.

        Returns:
            List of emergency content available
        """
        # TODO: Implement emergency content retrieval
        # - Get emergency content from Content Manager
        # - Filter for system-wide emergency use
        # - Return available emergency content
        pass

    def validate_system_state(self) -> bool:
        """
        Validate that the system is in a consistent state.

        Returns:
            True if system state is valid
        """
        # TODO: Implement system state validation
        # - Check all channels for consistency
        # - Validate system-wide state
        # - Ensure proper coordination
        # - Return validation result
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
                def ts_source_factory() -> FakeTsSource:
                    return FakeTsSource()
                fanout = ChannelStream(
                    channel_id=channel_id,
                    ts_source_factory=ts_source_factory,
                    hls_manager=self._hls_manager,
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

                def ts_source_factory() -> Any:
                    # Producer may have just started; allow a short wait for socket to appear
                    for attempt in range(6):
                        try:
                            sock = reader_queue.get(timeout=2.0)
                            self._logger.info(
                                "Got socket from queue for channel %s",
                                channel_id,
                            )
                            return SocketTsSource(sock)
                        except queue.Empty:
                            self._logger.debug(
                                "Reader queue empty for channel %s (attempt %d/6), waiting for socket",
                                channel_id,
                                attempt + 1,
                            )
                    raise RuntimeError(
                        "Timed out waiting for socket from reader_socket_queue for channel %s"
                        % channel_id
                    )

                fanout = ChannelStream(channel_id=channel_id, ts_source_factory=ts_source_factory, hls_manager=self._hls_manager)
                self._fanout_buffers[channel_id] = fanout
                return fanout

            # Fallback: Producer exposes only socket_path (legacy/test); connect as client (may fail if server closed).
            socket_path = getattr(producer, "socket_path", None)
            if not socket_path:
                return None
            if self._channel_stream_factory:
                fanout = self._channel_stream_factory(channel_id, str(socket_path))
            else:
                fanout = ChannelStream(channel_id=channel_id, socket_path=socket_path, hls_manager=self._hls_manager)
            self._fanout_buffers[channel_id] = fanout
            return fanout

    def _register_endpoints(self) -> None:
        """Register Phase 0 HTTP endpoints."""
        
        @self.fastapi_app.get("/channels")
        async def get_channels() -> dict[str, Any]:
            """
            Phase 0 contract: Channel discovery endpoint.
            
            Returns list of available channels (from provider or embedded registry).
            """
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
        ) -> None:
            """
            Unsubscribe viewer and update viewer count. Idempotent.
            Does NOT stop channel or upstream when last subscriber leaves:
            upstream (AIR UDS) stays connected so VLC reconnect does not restart AIR.
            """
            with self._fanout_lock:
                if fanout:
                    fanout.unsubscribe(session_id, reason="disconnect")
            try:
                manager.tune_out(session_id)
            except Exception as e:
                self._logger.debug("tune_out on cleanup: %s", e)

        async def _wait_disconnect_then_cleanup(request: Request, cleanup: Callable[[], None]) -> None:
            """When client disconnects, ASGI receive() returns; run cleanup so viewer_count and teardown run (Phase 8.7)."""
            try:
                await request.receive()
            except Exception:
                pass
            cleanup()

        @self.fastapi_app.get("/channel/{channel_id}.ts")
        async def stream_channel(request: Request, channel_id: str) -> StreamingResponse:
            """
            Phase 0 contract: Live stream endpoint for a channel.
            
            - Joins mid-stream (no restart)
            - Emits continuous MPEG-TS bytes
            - Stops playout engine pipeline when last viewer disconnects (Phase 8.7: disconnect triggers teardown)
            """
            try:
                if self._channel_manager_provider is not None:
                    manager = self._channel_manager_provider.get_channel_manager(channel_id)
                else:
                    manager = self._get_or_create_manager(channel_id)
            except Exception as e:
                self._logger.error("Error getting ChannelManager for %s: %s", channel_id, e)
                return Response(
                    content=f"Channel not available: {e}",
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            # Create session ID for this viewer
            session_id = str(uuid.uuid4())

            # Phase 0: Route tune request to ChannelManager
            try:
                manager.tune_in(session_id, {"channel_id": channel_id})
            except Exception as e:
                self._logger.error("Error tuning in viewer to channel %s: %s", channel_id, e)
                return Response(
                    content=f"Failed to tune in: {e}",
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            # Get or create FanoutBuffer for this channel
            fanout = self._get_or_create_fanout_buffer(channel_id, manager)
            if not fanout:
                # Producer not ready yet, wait for it to start
                cleaned = []

                def cleanup_placeholder() -> None:
                    if cleaned:
                        return
                    cleaned.append(1)
                    fanout_buffer = getattr(cleanup_placeholder, "_fanout", None)
                    _run_stream_cleanup(channel_id, session_id, manager, fanout_buffer)

                # INV-IO-DRAIN-REALTIME: Async placeholder generator
                async def generate_placeholder():
                    fanout_buffer = None
                    try:
                        for _ in range(10):
                            await asyncio.sleep(1)
                            fanout_buffer = self._get_or_create_fanout_buffer(channel_id, manager)
                            if fanout_buffer:
                                cleanup_placeholder._fanout = fanout_buffer
                                break
                        if not fanout_buffer:
                            yield b""
                            return
                        client_queue = fanout_buffer.subscribe(session_id)
                        asyncio.create_task(_wait_disconnect_then_cleanup(request, cleanup_placeholder))
                        async for chunk in generate_ts_stream_async(client_queue):
                            yield chunk
                    except GeneratorExit:
                        pass
                    except asyncio.CancelledError:
                        pass
                    finally:
                        cleanup_placeholder()

                return StreamingResponse(
                    generate_placeholder(),
                    media_type="video/mp2t",
                    headers={
                        "Cache-Control": "no-cache, no-store, must-revalidate",
                        "Pragma": "no-cache",
                        "Expires": "0",
                        "X-Accel-Buffering": "no",  # Disable nginx buffering if present
                    },
                )

            # Subscribe to FanoutBuffer
            client_queue = fanout.subscribe(session_id)
            cleaned = []

            def cleanup_stream() -> None:
                if cleaned:
                    return
                cleaned.append(1)
                _run_stream_cleanup(channel_id, session_id, manager, fanout)

            # Phase 8.7: When client disconnects, receive() returns; run cleanup so viewer_count→0 triggers teardown.
            asyncio.create_task(_wait_disconnect_then_cleanup(request, cleanup_stream))

            # INV-IO-DRAIN-REALTIME: Use async generator to yield to event loop
            # This ensures non-blocking streaming and regular flush opportunities.
            async def generate_stream():
                _first_chunk_logged = False
                try:
                    async for chunk in generate_ts_stream_async(client_queue):
                        if not _first_chunk_logged:
                            _first_chunk_logged = True
                        yield chunk
                except GeneratorExit:
                    pass
                except asyncio.CancelledError:
                    pass
                finally:
                    cleanup_stream()

            return StreamingResponse(
                generate_stream(),
                media_type="video/mp2t",
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                    "X-Accel-Buffering": "no",  # Disable nginx buffering if present
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

        @self.fastapi_app.get("/debug/horizon/{channel_id}")
        async def get_horizon_health(channel_id: str) -> Any:
            """Horizon health report for a channel.

            Returns HorizonManager health snapshot including EPG depth,
            execution depth, compliance status, and store entry count.
            """
            hm = self._horizon_managers.get(channel_id)
            if hm is None:
                return Response(
                    content=f"No HorizonManager for channel: {channel_id}",
                    status_code=status.HTTP_404_NOT_FOUND,
                )

            try:
                report = hm.get_health_report()
                return {
                    "channel_id": channel_id,
                    "is_healthy": report.is_healthy,
                    "epg_depth_hours": report.epg_depth_hours,
                    "epg_compliant": report.epg_compliant,
                    "epg_farthest_date": report.epg_farthest_date,
                    "execution_depth_hours": report.execution_depth_hours,
                    "execution_compliant": report.execution_compliant,
                    "execution_window_end_utc_ms": report.execution_window_end_utc_ms,
                    "min_epg_days": report.min_epg_days,
                    "min_execution_hours": report.min_execution_hours,
                    "evaluation_interval_seconds": report.evaluation_interval_seconds,
                    "last_evaluation_utc_ms": report.last_evaluation_utc_ms,
                    "store_entry_count": report.store_entry_count,
                }
            except Exception as e:
                self._logger.exception("get_horizon_health failed for %s", channel_id)
                return Response(
                    content=str(e),
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        @self.fastapi_app.get("/api/epg/{channel_id}")
        async def get_epg(
            channel_id: str,
            start: Optional[str] = None,
            end: Optional[str] = None,
        ) -> Any:
            """
            Phase 5 contract: EPG endpoint for a channel.

            INV-P5-004: EPG Endpoint Independence - works without active viewers.

            Query params:
                start: ISO 8601 start time (default: now)
                end: ISO 8601 end time (default: start + 24 hours)

            Returns:
                JSON with EPG events for the time range.
            """
            # Get channel config
            channel_config = None
            if self._channel_config_provider is not None:
                channel_config = self._channel_config_provider.get_channel_config(channel_id)

            if channel_config is None:
                return Response(
                    content=f"Channel not found: {channel_id}",
                    status_code=status.HTTP_404_NOT_FOUND,
                )

            # Only Phase 3 channels support EPG
            if channel_config.schedule_source != "phase3":
                return {"channel_id": channel_id, "events": [], "message": "EPG not available for this channel type"}

            # Get or create Phase 3 schedule service
            try:
                schedule_service = self._get_schedule_service_for_channel(channel_id, channel_config)
                success, error = schedule_service.load_schedule(channel_id)
                if not success:
                    return Response(
                        content=f"Failed to load schedule: {error}",
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )
            except Exception as e:
                self._logger.error("Error getting schedule service for EPG: %s", e)
                return Response(
                    content=f"Internal error: {e}",
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            # Parse time range
            now = datetime.now(timezone.utc)
            try:
                if start:
                    start_time = datetime.fromisoformat(start.replace("Z", "+00:00"))
                else:
                    start_time = now
                if end:
                    end_time = datetime.fromisoformat(end.replace("Z", "+00:00"))
                else:
                    end_time = start_time + timedelta(hours=24)
            except ValueError as e:
                return Response(
                    content=f"Invalid time format: {e}",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Get EPG events
            try:
                events = schedule_service.get_epg_events(channel_id, start_time, end_time)
                return {
                    "channel_id": channel_id,
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat(),
                    "events": events,
                }
            except Exception as e:
                self._logger.error("Error getting EPG events: %s", e)
                return Response(
                    content=f"Error getting EPG: {e}",
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        @self.fastapi_app.post("/admin/emergency")
        async def emergency_override() -> dict[str, Any]:
            """
            Phase 0 contract: Emergency override endpoint (placeholder/no-op for now).

            In Phase 0, this is a no-op. Future phases will enforce global overrides.
            """
            # Phase 0: No-op implementation
            return {"status": "ok", "message": "Emergency override endpoint (no-op in Phase 0)"}


        @self.fastapi_app.get("/api/epg")
        async def get_epg_all(
            date: Optional[str] = None,
            channel: Optional[str] = None,
        ) -> Any:
            """EPG endpoint for all channels compiled from DSL."""
            import json as _json
            from zoneinfo import ZoneInfo
            from retrovue.runtime.schedule_compiler import compile_schedule, parse_dsl
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

            # Part 2: Build resolver once per EPG request, not per channel
            with session() as db:
                _shared_resolver = CatalogAssetResolver(db)

            all_entries = []
            for ch in channels:
                try:
                    dsl_path = ch["schedule_config"]["dsl_path"]
                    dsl_text = Path(dsl_path).read_text()
                    dsl = parse_dsl(dsl_text)
                    dsl["broadcast_day"] = broadcast_day

                    resolver = _shared_resolver

                    # Deterministic sequential counters based on day offset
                    from datetime import date as _date_type
                    _epoch = _date_type(2026, 1, 1)
                    _target = _date_type.fromisoformat(broadcast_day)
                    _day_offset = (_target - _epoch).days
                    _slots = sum(
                        len(b.get("slots", []))
                        for v in dsl.get("schedule", {}).values()
                        for b in (v if isinstance(v, list) else [v])
                        if isinstance(b, dict)
                    )
                    _seq_counters = {
                        pid: _day_offset * _slots
                        for pid in dsl.get("pools", {})
                    }
                    # Derive channel-specific seed from channel_id hash
                    _channel_seed = abs(hash(ch["channel_id"])) % 100000
                    schedule = compile_schedule(
                        dsl, resolver=resolver, dsl_path=dsl_path,
                        sequential_counters=_seq_counters,
                        seed=_channel_seed,
                    )

                    for block in schedule["program_blocks"]:
                        asset_id = block["asset_id"]
                        series_title = block.get("title", "")
                        season_number = None
                        episode_number = None

                        description = ""
                        episode_title = ""
                        for cat_entry in resolver._catalog:
                            if cat_entry.canonical_id == asset_id:
                                series_title = cat_entry.series_title or series_title
                                season_number = cat_entry.season
                                episode_number = cat_entry.episode
                                description = getattr(cat_entry, "description", "") or ""
                                episode_title = getattr(cat_entry, "title", "") or ""
                                break

                        start_dt = datetime.fromisoformat(block["start_at"])
                        slot_sec = block["slot_duration_sec"]
                        ep_sec = block["episode_duration_sec"]
                        end_dt = start_dt + timedelta(seconds=slot_sec)

                        all_entries.append({
                            "channel_id": ch["channel_id"],
                            "channel_name": ch["name"],
                            "start_time": start_dt.isoformat(),
                            "end_time": end_dt.isoformat(),
                            "title": series_title,
                            "episode_title": episode_title,
                            "season": season_number,
                            "episode": episode_number,
                            "description": description,
                            "duration_minutes": round(ep_sec / 60, 1),
                            "slot_minutes": round(slot_sec / 60, 1),
                        })
                except Exception as e:
                    self._logger.error("EPG compile error for %s: %s", ch["channel_id"], e, exc_info=True)
                    all_entries.append({
                        "channel_id": ch["channel_id"],
                        "channel_name": ch["name"],
                        "error": str(e),
                    })

            return {"broadcast_day": broadcast_day, "entries": all_entries}


        # --- HLS Endpoints ---

        @self.fastapi_app.get("/hls/{channel_id}/live.m3u8")
        async def hls_playlist(channel_id: str, request: Request) -> Response:
            """Serve HLS playlist.

            If a raw-TS viewer is already connected (ChannelStream running),
            the segmenter is fed via tee in the reader loop — just ensure
            the segmenter is started.

            If no viewer exists, start the channel normally (tune_in triggers
            FFmpeg).  The ChannelStream reader loop will tee to HLS.

            HLS phantom viewer lifecycle: phantom tunes in when first HLS
            client requests the playlist, and tunes out after no client has
            fetched a playlist or segment for LINGER_SECONDS. This lets the
            normal viewer_count -> 0 -> linger -> teardown lifecycle work.
            """
            import time as _time

            # Track activity for this channel
            with self._hls_activity_lock:
                self._hls_last_activity[channel_id] = _time.monotonic()

            seg = self._hls_manager.get_or_create(channel_id)
            if not seg.is_running():
                seg.start()

                # Ensure the channel is running so ChannelStream feeds us
                try:
                    if self._channel_manager_provider is not None:
                        manager = self._channel_manager_provider.get_channel_manager(channel_id)
                    else:
                        manager = self._get_or_create_manager(channel_id)
                except Exception as e:
                    return Response(
                        content=f"Channel not available: {e}",
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    )

                # Tune in to trigger producer + ChannelStream start
                hls_session_id = f"hls-{channel_id}-{uuid.uuid4().hex[:8]}"
                with self._hls_activity_lock:
                    self._hls_phantom_sessions[channel_id] = hls_session_id
                try:
                    manager.tune_in(hls_session_id, {"channel_id": channel_id})
                except Exception as e:
                    self._logger.warning("HLS tune_in error: %s", e)

                # Wait for fanout (which starts the reader loop that tees to HLS)
                fanout = None
                for _ in range(20):
                    fanout = self._get_or_create_fanout_buffer(channel_id, manager)
                    if fanout:
                        break
                    await asyncio.sleep(1)
                if fanout:
                    hls_queue = fanout.subscribe(hls_session_id)
                    import threading as _td

                    # Drain thread: keeps fanout alive, but monitors HLS client activity.
                    # When no client has fetched playlist/segments for LINGER_SECONDS,
                    # the phantom disconnects — letting viewer_count hit 0 and linger begin.
                    def _drain_hls_phantom(q=hls_queue, s=seg, mgr=manager, sid=hls_session_id, cid=channel_id):
                        IDLE_CHECK_INTERVAL = 5.0  # seconds between idle checks
                        # Use the channel manager's LINGER_SECONDS if available, else default 20s
                        idle_timeout = getattr(mgr, 'LINGER_SECONDS', 20)
                        self._logger.info(
                            "[HLS-phantom %s] started, idle_timeout=%ds", cid, idle_timeout
                        )
                        while s.is_running():
                            try:
                                chunk = q.get(timeout=IDLE_CHECK_INTERVAL)
                                if not chunk:
                                    break
                            except Exception:
                                pass
                            # Check if any HLS client is still active
                            with self._hls_activity_lock:
                                last = self._hls_last_activity.get(cid, 0)
                            idle_seconds = _time.monotonic() - last
                            if idle_seconds > idle_timeout:
                                self._logger.info(
                                    "[HLS-phantom %s] no client activity for %.0fs (timeout=%ds), disconnecting",
                                    cid, idle_seconds, idle_timeout
                                )
                                break

                        # Cleanup: tune out the phantom viewer
                        self._logger.info("[HLS-phantom %s] tearing down phantom viewer %s", cid, sid)
                        try:
                            mgr.tune_out(sid)
                        except Exception as e:
                            self._logger.warning("[HLS-phantom %s] tune_out error: %s", cid, e)
                        try:
                            fanout.unsubscribe(sid)
                        except Exception:
                            pass
                        # Stop the segmenter
                        try:
                            s.stop()
                        except Exception:
                            pass
                        # Clean up tracking
                        with self._hls_activity_lock:
                            self._hls_phantom_sessions.pop(cid, None)
                            self._hls_last_activity.pop(cid, None)

                    _td.Thread(target=_drain_hls_phantom, daemon=True, name=f"hls-phantom-{channel_id}").start()

                # Wait for first playlist to appear
                for _ in range(30):
                    if seg.playlist_path.exists():
                        break
                    await asyncio.sleep(0.5)

            playlist = seg.playlist_path
            if not playlist.exists():
                return Response(
                    content="Playlist not ready yet",
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            return Response(
                content=playlist.read_text(),
                media_type="application/vnd.apple.mpegurl",
                headers={
                    "Cache-Control": "no-cache, no-store",
                    "Access-Control-Allow-Origin": "*",
                },
            )

        @self.fastapi_app.get("/hls/{channel_id}/{segment}")
        async def hls_segment(channel_id: str, segment: str) -> Response:
            """Serve HLS .ts segments."""
            import time as _time
            # Track activity — client is still watching
            with self._hls_activity_lock:
                self._hls_last_activity[channel_id] = _time.monotonic()

            seg_path = HLS_BASE_DIR / channel_id / segment
            if not seg_path.exists() or ".." in segment:
                return Response(content="Not found", status_code=404)
            return FileResponse(
                str(seg_path),
                media_type="video/mp2t",
                headers={
                    "Cache-Control": "no-cache",
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
        async def epg_guide_html() -> HTMLResponse:
            """Serve the EPG HTML page."""
            html_path = Path("/opt/retrovue/pkg/core/templates") / "epg" / "guide.html"
            return HTMLResponse(content=html_path.read_text())

    def _start_http_server(self) -> None:
        """Start the HTTP server in a background thread."""
        if self._server_thread and self._server_thread.is_alive():
            self._logger.debug("HTTP server already running")
            return

        def _run_server():
            try:
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
