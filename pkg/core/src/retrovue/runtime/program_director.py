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
from fastapi.responses import StreamingResponse
from uvicorn import Config, Server

from retrovue.runtime.clock import MasterClock, RealTimeMasterClock
from retrovue.runtime.pace import PaceController
from retrovue.runtime.channel_stream import (
    ChannelStream,
    FakeTsSource,
    SocketTsSource,
    generate_ts_stream,
)
from retrovue.runtime.config import (
    ChannelConfig,
    ChannelConfigProvider,
    InlineChannelConfigProvider,
    MOCK_CHANNEL_CONFIG,
)
from retrovue.runtime.phase3_schedule_service import Phase3ScheduleService

try:
    from retrovue.runtime.settings import RuntimeSettings  # type: ignore
except ImportError:  # pragma: no cover - settings optional
    RuntimeSettings = None  # type: ignore

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
        # Phase 5: Per-channel schedule services for Phase 3 mode
        self._phase3_schedule_services: dict[str, Phase3ScheduleService] = {}
        self._phase8_program_director: Optional[Any] = None
        self._channel_config_provider: Optional[Any] = None
        self._producer_factory: Optional[Callable[..., Any]] = None
        self._health_check_stop: Optional[threading.Event] = None
        self._health_check_thread: Optional[Thread] = None
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
        self._mock_schedule = (
            schedule_dir is None and not mock_schedule_grid_mode and not mock_schedule_ab_mode
        )

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
        
        # Register HTTP endpoints
        self._register_endpoints()
        
        self._logger.debug(
            "ProgramDirector initialized with target_hz=%s clock=%s host=%s port=%s",
            self._pace.target_hz,
            type(self._clock).__name__,
            host,
            port,
        )

    def _init_embedded_registry(
        self, channel_config_provider: Optional[Any] = None
    ) -> None:
        """Build schedule service, program director, config provider, producer factory (embedded mode)."""
        # ChannelManager and schedule services expect clock.now_utc() (datetime); use concrete MasterClock
        self._embedded_clock = MasterClock()
        from retrovue.runtime.channel_manager import (
            ChannelManager,
            MockAlternatingScheduleService,
            MockGridScheduleService,
            Phase8AirProducer,
            Phase8MockScheduleService,
            Phase8ProgramDirector,
            Phase8ScheduleService,
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
        elif self._mock_schedule:
            self._schedule_service = Phase8MockScheduleService(self._embedded_clock)
        else:
            self._schedule_service = Phase8ScheduleService(self._schedule_dir, self._embedded_clock)
        self._phase8_program_director = Phase8ProgramDirector()
        self._channel_config_provider = (
            channel_config_provider
            if channel_config_provider is not None
            else InlineChannelConfigProvider([MOCK_CHANNEL_CONFIG])
        )

        def _create_air_producer(
            channel_id: str,
            mode: str,
            config: dict[str, Any],
            channel_config: Optional[ChannelConfig] = None,
        ) -> Optional[Any]:
            if mode != "normal":
                return None
            return Phase8AirProducer(channel_id, config, channel_config=channel_config)

        self._producer_factory = _create_air_producer
        self._health_check_stop = threading.Event()

    def _get_schedule_service_for_channel(self, channel_id: str, channel_config: ChannelConfig) -> Any:
        """
        Get appropriate schedule service based on channel config.

        INV-P5-001: Config-Driven Activation - schedule_source: "phase3" enables Phase 3 mode.
        """
        schedule_source = channel_config.schedule_source

        if schedule_source == "phase3":
            # Phase 5: Use Phase3ScheduleService for this channel
            if channel_id not in self._phase3_schedule_services:
                schedule_config = channel_config.schedule_config
                programs_dir = Path(schedule_config.get("programs_dir", "config/programs"))
                schedules_dir = Path(schedule_config.get("schedules_dir", "config/schedules"))
                filler_path = schedule_config.get("filler_path", "/opt/retrovue/assets/filler.mp4")
                filler_duration = schedule_config.get("filler_duration_seconds", 3650.0)
                grid_minutes = schedule_config.get("grid_minutes", 30)

                self._logger.info(
                    "[channel %s] Creating Phase3ScheduleService (schedule_source=%s)",
                    channel_id,
                    schedule_source,
                )

                service = Phase3ScheduleService(
                    clock=self._embedded_clock,
                    programs_dir=programs_dir,
                    schedules_dir=schedules_dir,
                    filler_path=filler_path,
                    filler_duration_seconds=filler_duration,
                    grid_minutes=grid_minutes,
                )
                self._phase3_schedule_services[channel_id] = service

            return self._phase3_schedule_services[channel_id]

        # Default: use the existing schedule service (Phase 8 or mock)
        return self._schedule_service

    def _get_or_create_manager(self, channel_id: str) -> Any:
        """Get or create ChannelManager for a channel (embedded mode). PD is sole authority for creation."""
        with self._managers_lock:
            if channel_id not in self._managers:
                channel_config = self._channel_config_provider.get_channel_config(channel_id)
                if channel_config is None:
                    self._logger.warning(
                        "[channel %s] No config found, using mock config",
                        channel_id,
                    )
                    channel_config = MOCK_CHANNEL_CONFIG

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
                    program_director=self._phase8_program_director,
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

                def factory_wrapper(mode: str, cfg: ChannelConfig = cfg) -> Optional[Any]:
                    return self._producer_factory(channel_id, mode, {}, channel_config=cfg)
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
            except Exception as e:
                self._logger.warning("Health check loop error: %s", e, exc_info=True)

    def load_all_schedules(self) -> list[str]:
        """Load schedule data for discoverable channels (embedded mode)."""
        if self._schedule_service is None:
            return []
        if self._mock_schedule_ab_mode:
            from retrovue.runtime.channel_manager import MockAlternatingScheduleService
            channel_id = MockAlternatingScheduleService.MOCK_AB_CHANNEL_ID
            success, _ = self._schedule_service.load_schedule(channel_id)
            return [channel_id] if success else []
        if self._mock_schedule:
            from retrovue.runtime.channel_manager import Phase8MockScheduleService
            channel_id = Phase8MockScheduleService.MOCK_CHANNEL_ID
            success, _ = self._schedule_service.load_schedule(channel_id)
            return [channel_id] if success else []
        if not Path(self._schedule_dir).exists():
            return []
        loaded = []
        for schedule_file in Path(self._schedule_dir).glob("*.json"):
            channel_id = schedule_file.stem
            success, _ = self._schedule_service.load_schedule(channel_id)
            if success:
                loaded.append(channel_id)
        return loaded

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
                try:
                    fanout.stop()
                except Exception as e:
                    self._logger.warning(
                        "Error stopping channel stream for %s: %s", channel_id, e
                    )

    # Lifecycle -------------------------------------------------------------
    def start(self) -> None:
        """Start the pacing loop, health-check loop (embedded), and HTTP server."""
        # Embedded mode: load schedules and start health-check thread
        if self._channel_manager_provider is None:
            self.load_all_schedules()
            if self._health_check_stop is not None:
                self._health_check_stop.clear()
                self._health_check_thread = Thread(
                    target=self._health_check_loop,
                    name="program-director-health-check",
                    daemon=True,
                )
                self._health_check_thread.start()
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
        
        # Stop all fanout buffers
        with self._fanout_lock:
            for channel_id, fanout in list(self._fanout_buffers.items()):
                try:
                    fanout.stop()
                except Exception as e:
                    self._logger.warning("Error stopping fanout buffer for channel %s: %s", channel_id, e)
            self._fanout_buffers.clear()

        # Embedded mode: stop health-check thread and tear down all managers
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

                fanout = ChannelStream(channel_id=channel_id, ts_source_factory=ts_source_factory)
                self._fanout_buffers[channel_id] = fanout
                return fanout

            # Fallback: Producer exposes only socket_path (legacy/test); connect as client (may fail if server closed).
            socket_path = getattr(producer, "socket_path", None)
            if not socket_path:
                return None
            if self._channel_stream_factory:
                fanout = self._channel_stream_factory(channel_id, str(socket_path))
            else:
                fanout = ChannelStream(channel_id=channel_id, socket_path=socket_path)
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
            """Phase 8.5/8.7: Unsubscribe viewer and tear down channel when last subscriber leaves. Idempotent."""
            to_stop = None
            with self._fanout_lock:
                if fanout:
                    fanout.unsubscribe(session_id)
                if channel_id in self._fanout_buffers:
                    f = self._fanout_buffers[channel_id]
                    if f.get_subscriber_count() == 0:
                        self._fanout_buffers.pop(channel_id, None)
                        to_stop = f
            try:
                manager.tune_out(session_id)
            except Exception as e:
                self._logger.debug("tune_out on cleanup: %s", e)
            if to_stop:
                self.stop_channel(channel_id)
                to_stop.stop()

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

                def generate_placeholder():
                    fanout_buffer = None
                    try:
                        for _ in range(10):
                            time.sleep(1)
                            fanout_buffer = self._get_or_create_fanout_buffer(channel_id, manager)
                            if fanout_buffer:
                                cleanup_placeholder._fanout = fanout_buffer
                                break
                        if not fanout_buffer:
                            yield b""
                            return
                        client_queue = fanout_buffer.subscribe(session_id)
                        asyncio.create_task(_wait_disconnect_then_cleanup(request, cleanup_placeholder))
                        for chunk in generate_ts_stream(client_queue):
                            yield chunk
                    except GeneratorExit:
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

            def generate_stream():
                try:
                    for chunk in generate_ts_stream(client_queue):
                        yield chunk
                except GeneratorExit:
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
