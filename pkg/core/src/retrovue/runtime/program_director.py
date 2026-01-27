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

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from threading import Thread
from typing import Any, Callable, Optional, Protocol

from fastapi import FastAPI, Response, status
from fastapi.responses import StreamingResponse
from uvicorn import Config, Server

from retrovue.runtime.clock import MasterClock, RealTimeMasterClock
from retrovue.runtime.pace import PaceController
from retrovue.runtime.channel_stream import ChannelStream, generate_ts_stream

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
    ) -> None:
        """Initialize the Program Director.
        
        Args:
            channel_manager_provider: Provider for ChannelManager instances
            clock: MasterClock instance (optional)
            target_hz: Pacing target frequency (optional)
            host: HTTP server bind address
            port: HTTP server port
            sleep_fn: Sleep function for testing (optional)
        """
        self._logger = logging.getLogger(__name__)
        self._clock = clock or RealTimeMasterClock()
        if target_hz is None and RuntimeSettings:
            target_hz = RuntimeSettings.pace_target_hz
        self._pace = PaceController(clock=self._clock, target_hz=target_hz or 30.0, sleep_fn=sleep_fn)
        self._pace_thread: Optional[Thread] = None
        
        # Phase 0: ChannelManager integration
        self._channel_manager_provider = channel_manager_provider
        
        # Phase 0: FanoutBuffer (ChannelStream) per channel
        self._fanout_buffers: dict[str, ChannelStream] = {}
        self._fanout_lock = threading.Lock()
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

    # Lifecycle -------------------------------------------------------------
    def start(self) -> None:
        """Start the pacing loop and HTTP server."""
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
            if channel_id in self._fanout_buffers:
                fanout = self._fanout_buffers[channel_id]
                if fanout.is_running():
                    return fanout
                # Remove stopped fanout
                self._fanout_buffers.pop(channel_id, None)

            # Check if Producer is running and has socket_path
            producer = getattr(manager, "active_producer", None)
            if not producer:
                return None

            # Get socket path from Producer
            socket_path = getattr(producer, "socket_path", None)
            if not socket_path:
                return None

            # Create ChannelStream as FanoutBuffer (or use test factory for Phase 7 E2E)
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
            
            Returns list of available channels.
            """
            if not self._channel_manager_provider:
                return {"channels": []}
            
            # Get list of channels from provider
            channels = []
            try:
                if hasattr(self._channel_manager_provider, "list_channels"):
                    channel_ids = self._channel_manager_provider.list_channels()
                    channels = [{"id": cid, "name": cid} for cid in channel_ids]
            except Exception as e:
                self._logger.warning("Error getting channel list: %s", e)
            
            return {"channels": channels}

        @self.fastapi_app.get("/channels/{channel_id}.ts")
        async def stream_channel(channel_id: str) -> StreamingResponse:
            """
            Phase 0 contract: Live stream endpoint for a channel.
            
            - Joins mid-stream (no restart)
            - Emits continuous MPEG-TS bytes
            - Stops playout engine pipeline when last viewer disconnects
            """
            if not self._channel_manager_provider:
                return Response(
                    content="Channel manager provider not configured",
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            try:
                # Get ChannelManager for this channel
                manager = self._channel_manager_provider.get_channel_manager(channel_id)
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
                def generate_placeholder():
                    fanout_buffer = None
                    try:
                        # Wait a bit for Producer to start
                        import time
                        for _ in range(10):  # Wait up to 10 seconds
                            time.sleep(1)
                            fanout_buffer = self._get_or_create_fanout_buffer(channel_id, manager)
                            if fanout_buffer:
                                break
                        
                        if not fanout_buffer:
                            # Still no fanout, send error
                            yield b""
                            return
                        
                        # Subscribe to fanout
                        client_queue = fanout_buffer.subscribe(session_id)
                        for chunk in generate_ts_stream(client_queue):
                            yield chunk
                    except GeneratorExit:
                        pass
                    finally:
                        if fanout_buffer:
                            fanout_buffer.unsubscribe(session_id)
                        manager.tune_out(session_id)

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

            # Generate stream from FanoutBuffer
            def generate_stream():
                try:
                    for chunk in generate_ts_stream(client_queue):
                        yield chunk
                except GeneratorExit:
                    pass
                finally:
                    # Phase 0: Stop playout engine pipeline when last viewer disconnects
                    fanout.unsubscribe(session_id)
                    manager.tune_out(session_id)
                    
                    # Check if this was the last viewer
                    if fanout.get_subscriber_count() == 0:
                        # Last viewer disconnected - ChannelManager will stop Producer
                        # via on_last_viewer() callback
                        pass

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
            if not self._channel_manager_provider:
                return Response(
                    content="Channel manager provider not configured",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            try:
                manager = self._channel_manager_provider.get_channel_manager(channel_id)
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
