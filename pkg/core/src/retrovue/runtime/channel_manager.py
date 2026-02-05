"""
RetroVue Core runtime.

System-wide runtime that manages ALL channels using the runtime ChannelManager.
Runs an HTTP server and bridges HTTP requests to ChannelManager instances.

This is an internal implementation detail. The public-facing product is RetroVue.
"""

from __future__ import annotations

import asyncio
import math
import json
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Any


# P11E-001: Single source for prefeed/startup timing (env RETROVUE_MIN_PREFEED_LEAD_TIME_MS).
from .constants import (
    MIN_PREFEED_LEAD_TIME,
    MIN_PREFEED_LEAD_TIME_MS,
    SCHEDULING_BUFFER_SECONDS,
    STARTUP_LATENCY,
)


class SwitchState(Enum):
    """Phase 8: State machine for clock-driven segment switching.

    This enum makes invalid states unrepresentable. The transitions are:
    - IDLE: No pending switch. LoadPreview() → PREVIEW_LOADED
    - PREVIEW_LOADED: Preview loaded, buffers filling. SwitchToLive() → SWITCH_ARMED or IDLE
    - SWITCH_ARMED: Switch in progress, waiting for auto-complete. SwitchToLive() → IDLE

    CRITICAL: LoadPreview() is FORBIDDEN in SWITCH_ARMED state.
    Calling LoadPreview while a switch is armed would destroy the preview producer
    that's currently filling buffers, preventing the switch from ever completing.
    """
    IDLE = auto()           # No pending switch, ready for LoadPreview
    PREVIEW_LOADED = auto() # Preview loaded, ready for SwitchToLive
    SWITCH_ARMED = auto()   # SwitchToLive called, awaiting auto-complete


# P11F-002 INV-BOUNDARY-LIFECYCLE-001: Unidirectional boundary state machine.
class BoundaryState(Enum):
    """P11F-002: Boundary lifecycle. Illegal transitions force FAILED_TERMINAL."""
    NONE = auto()              # No boundary planned
    PLANNED = auto()           # Boundary computed, LoadPreview scheduled
    PRELOAD_ISSUED = auto()    # LoadPreview sent to AIR
    SWITCH_SCHEDULED = auto()  # Switch timer registered (one-shot)
    SWITCH_ISSUED = auto()     # SwitchToLive sent to AIR
    LIVE = auto()              # AIR confirmed switch complete
    FAILED_TERMINAL = auto()   # Unrecoverable failure (absorbing)


_ALLOWED_BOUNDARY_TRANSITIONS: dict[BoundaryState, set[BoundaryState]] = {
    BoundaryState.NONE: {BoundaryState.PLANNED},
    BoundaryState.PLANNED: {BoundaryState.PRELOAD_ISSUED, BoundaryState.FAILED_TERMINAL},
    BoundaryState.PRELOAD_ISSUED: {BoundaryState.SWITCH_SCHEDULED, BoundaryState.FAILED_TERMINAL},
    BoundaryState.SWITCH_SCHEDULED: {BoundaryState.SWITCH_ISSUED, BoundaryState.FAILED_TERMINAL},
    BoundaryState.SWITCH_ISSUED: {BoundaryState.LIVE, BoundaryState.FAILED_TERMINAL},
    BoundaryState.LIVE: {BoundaryState.NONE, BoundaryState.PLANNED},
    BoundaryState.FAILED_TERMINAL: set(),
}

# P12-CORE-001 INV-TEARDOWN-STABLE-STATE-001: Teardown deferred until boundary state stable.
_STABLE_STATES: set[BoundaryState] = {
    BoundaryState.NONE,
    BoundaryState.LIVE,
    BoundaryState.FAILED_TERMINAL,
}
_TRANSIENT_STATES: set[BoundaryState] = {
    BoundaryState.PLANNED,
    BoundaryState.PRELOAD_ISSUED,
    BoundaryState.SWITCH_SCHEDULED,
    BoundaryState.SWITCH_ISSUED,
}
_TEARDOWN_GRACE_TIMEOUT: timedelta = timedelta(seconds=10)
# P12-CORE-011 INV-STARTUP-CONVERGENCE-001: Max time to achieve first boundary; expiry → FAILED_TERMINAL (P12-CORE-013).
MAX_STARTUP_CONVERGENCE_WINDOW: timedelta = timedelta(seconds=120)

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import StreamingResponse
from uvicorn import Config, Server

from .clock import MasterClock
from .producer.base import Producer, ProducerMode, ProducerStatus, ContentSegment, ProducerState
from .channel_stream import ChannelStream, FakeTsSource, SocketTsSource, generate_ts_stream
from .config import (
    ChannelConfig,
    ChannelConfigProvider,
    InlineChannelConfigProvider,
    MOCK_CHANNEL_CONFIG,
)
from ..usecases import channel_manager_launch
from typing import Protocol, TYPE_CHECKING
from dataclasses import dataclass
from datetime import datetime
import logging
import os
import threading

# BlockPlan imports (lazy to avoid circular imports)
if TYPE_CHECKING:
    from .playout_session import PlayoutSession, BlockPlan

if TYPE_CHECKING:
    from retrovue.runtime.metrics import ChannelMetricsSample, MetricsPublisher

# P11E-004: Prefeed/switch lead time metrics (None if prometheus_client not installed)
from .metrics import (
    prefeed_lead_time_ms,
    prefeed_lead_time_violations_total,
    switch_lead_time_ms,
    switch_lead_time_violations_total,
)


# ----------------------------------------------------------------------
# Protocols
# ----------------------------------------------------------------------


class ScheduleService(Protocol):
    """Read-only schedule accessor."""

    def get_playout_plan_now(
        self,
        channel_id: str,
        at_station_time: datetime,
    ) -> list[dict[str, Any]]:
        """
        Return the resolved segment sequence that should be airing 'right now' on this channel.

        Must include correct timing offsets so we can join mid-program instead of restarting at frame 0.
        Must NOT mutate schedule state.
        """
        ...


class ProgramDirector(Protocol):
    """Global policy/mode provider."""

    def get_channel_mode(self, channel_id: str) -> str:
        """
        Return the required mode for this channel: "normal", "emergency", "guide", etc.
        ChannelManager is not allowed to make this decision on its own.
        """
        ...


# ----------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------


class ChannelManagerError(Exception):
    """Base exception for ChannelManager errors."""

    pass


class ProducerStartupError(ChannelManagerError):
    """Raised when a Producer cannot be constructed or fails to start."""

    pass


class NoScheduleDataError(ChannelManagerError):
    """
    Raised if ScheduleService returns nothing for "right now".

    This is considered an upstream scheduling failure, NOT permission for
    ChannelManager to improvise content.
    """

    pass


class SchedulingError(ChannelManagerError):
    """P11D-006: Raised when scheduling would violate INV-CONTROL-NO-POLL-001 (e.g. insufficient lead time)."""

    pass


class ChannelFailedError(ChannelManagerError):
    """
    Raised if ChannelManager cannot get any Producer on-air for this channel.

    This encodes the invariant that a channel is either on-air or failed:
    we do not allow a 'partially started' channel.
    """

    pass


# ----------------------------------------------------------------------
# ChannelManager (Per-Channel Orchestrator)
# ----------------------------------------------------------------------


@dataclass
class ChannelRuntimeState:
    """
    Runtime state that ChannelManager is responsible for tracking and reporting up to ProgramDirector.
    ProgramDirector and any operator UI should treat ChannelManager as the source of truth for on-air status.
    """

    channel_id: str
    current_mode: str  # "normal" | "emergency" | "guide"
    viewer_count: int
    producer_status: str  # mirrors ProducerStatus as string
    producer_started_at: datetime | None
    stream_endpoint: str | None  # what viewers attach to
    last_health: str | None  # "running", "degraded", "stopped", etc.

    def to_dict(self) -> dict[str, Any]:
        """
        Convert runtime state to dictionary for reporting/telemetry.
        """
        return {
            "channel_id": self.channel_id,
            "current_mode": self.current_mode,
            "viewer_count": self.viewer_count,
            "producer_status": self.producer_status,
            "producer_started_at": (
                self.producer_started_at.isoformat() if self.producer_started_at else None
            ),
            "stream_endpoint": self.stream_endpoint,
            "last_health": self.last_health,
        }


class ChannelManager:
    """
    Per-channel runtime controller that manages individual channel operations.

    Pattern: Per-Channel Orchestrator

    ChannelManager is the per-channel board operator. It runs the fanout model. It is the only
    component that actually starts/stops Producers. It obeys ProgramDirector's global mode.
    It consumes the schedule but does not write it. It never chooses content; it only plays
    what it is told.

    ChannelManager is how a RetroVue channel actually goes on-air.

    Responsibilities (enforced here):
    - Ask ScheduleService what should be airing 'right now', using MasterClock for authoritative time
    - Start/stop the Producer based on viewer fanout rules (first viewer starts, last viewer stops)
    - Swap Producers when ProgramDirector changes global mode (normal/emergency/guide)
    - Expose the Producer's stream endpoint so viewers can attach
    - Surface health/status upward to ProgramDirector

    Hard boundaries:
    - ChannelManager does NOT pick content
    - ChannelManager does NOT modify schedule
    - ChannelManager does NOT call ffmpeg or manage OS processes directly
    - ChannelManager does NOT "fill gaps" if schedule is missing
    """

    def __init__(
        self,
        channel_id: str,
        clock: MasterClock,
        schedule_service: ScheduleService,
        program_director: ProgramDirector,
        event_loop: asyncio.AbstractEventLoop | None = None,
    ):
        """
        Initialize the ChannelManager for a specific channel.

        Args:
            channel_id: Channel this manager controls
            clock: MasterClock for authoritative time
            schedule_service: ScheduleService for read-only access to current playout plan
            program_director: ProgramDirector for global policy/mode
            event_loop: Optional event loop for P11F-005; when set, switch issuance uses call_later instead of threading.Timer
        """
        self.channel_id = channel_id
        self.clock = clock
        self.schedule_service = schedule_service
        self.program_director = program_director
        self._loop: asyncio.AbstractEventLoop | None = event_loop
        # P11F-005: asyncio handle when using event loop (cancel on teardown)
        self._switch_handle: asyncio.TimerHandle | None = None

        # Track active tuning sessions (viewer_id -> session data)
        self.viewer_sessions: dict[str, dict[str, Any]] = {}

        # At most one active producer for this channel.
        self.active_producer: Producer | None = None

        # Runtime snapshot for ProgramDirector / dashboards / analytics.
        self.runtime_state = ChannelRuntimeState(
            channel_id=channel_id,
            current_mode="normal",
            viewer_count=0,
            producer_status="stopped",
            producer_started_at=None,
            stream_endpoint=None,
            last_health=None,
        )
        self._metrics_publisher: "MetricsPublisher | None" = None
        self._logger = logging.getLogger(__name__)
        self._teardown_timeout_seconds = 5.0
        self._teardown_started_station: float | None = None
        self._teardown_reason: str | None = None
        # P12-CORE-001 INV-TEARDOWN-STABLE-STATE-001: Deferred teardown state scaffolding
        self._teardown_pending: bool = False
        self._teardown_deadline: datetime | None = None
        # P12-CORE-003: Signal to ProgramDirector that deferred teardown executed (poll and destroy)
        self._deferred_teardown_triggered: bool = False
        # P12-CORE-011 INV-STARTUP-CONVERGENCE-001: Startup convergence until first successful boundary
        self._converged: bool = False
        self._convergence_deadline: datetime | None = None

        # Mock grid configuration (when using mock grid schedule)
        self._mock_grid_block_minutes = 30  # Fixed 30-minute grid
        self._mock_grid_program_asset_path: str | None = None  # Set from daemon config
        self._mock_grid_filler_asset_path: str | None = None  # Set from daemon config
        self._mock_grid_filler_epoch: datetime | None = None  # Epoch for filler offset calculation

        # Channel lifecycle: RUNNING (on-air or idle with viewers) or STOPPED (last viewer left).
        # When STOPPED, health/reconnect logic does nothing; ProgramDirector calls stop_channel on last viewer.
        self._channel_state: str = "RUNNING"  # "RUNNING" | "STOPPED"

        # Clock-driven segment switching (schedule advances because time advanced, not EOF).
        self._segment_end_time_utc: datetime | None = None  # When current segment ends (from schedule)
        # P11E-002: LoadPreview at boundary - MIN_PREFEED_LEAD_TIME - SCHEDULING_BUFFER (trigger time).
        self._preload_lead_seconds: float = max(
            7.0, MIN_PREFEED_LEAD_TIME.total_seconds() + SCHEDULING_BUFFER_SECONDS
        )
        # P11D-011 INV-SWITCH-ISSUANCE-DEADLINE-001: Issuance is deadline-scheduled (issue_at = boundary - MIN_PREFEED_LEAD_TIME).
        self._switch_lead_seconds: float = MIN_PREFEED_LEAD_TIME.total_seconds()
        self._last_switch_at_segment_end_utc: datetime | None = None  # Guard: fire switch_to_live() once per segment
        # P11D-011: Deadline-scheduled switch issuance (not cadence-detected)
        self._switch_issue_timer: threading.Timer | None = None
        self._switch_issue_timer_lock: threading.Lock = threading.Lock()

        # INV-VIEWER-LIFECYCLE: Thread-safe viewer count transitions
        # Protects viewer_sessions dict and viewer_count for concurrent join/leave
        self._viewer_lock: threading.Lock = threading.Lock()

        # BlockPlan mode: when True, use BlockPlanProducer instead of Phase8AirProducer
        # Set via set_blockplan_mode() or configuration
        self._blockplan_mode: bool = False
        self._pending_fatal: BaseException | None = None  # Set by timer callback if late/fatal; tick() re-raises
        # Phase 8: State machine for clock-driven switching (replaces boolean flags)
        self._switch_state: SwitchState = SwitchState.IDLE
        # P11F-002 INV-BOUNDARY-LIFECYCLE-001: Unidirectional boundary state machine
        self._boundary_state: BoundaryState = BoundaryState.NONE
        # P11F-006 INV-BOUNDARY-DECLARED-MATCHES-PLAN-001: Plan-derived boundary (ms) for validation
        self._plan_boundary_ms: int | None = None

        # =======================================================================
        # CT-Domain Switching (INV-PLAYOUT-SWITCH-BEFORE-EXHAUSTION)
        # =======================================================================
        # Each segment tracks:
        #   - ct_start_us: when segment began in CT domain
        #   - frame_count: explicit frame budget (>= 0)
        #   - frame_duration_us: derived from fps
        #
        # Compute: ct_exhaust_us = ct_start_us + (frame_count * frame_duration_us)
        # Switch thresholds are in CT domain - no UTC conversions needed.
        self._segment_ct_start_us: int | None = None
        self._segment_frame_count: int | None = None
        self._segment_frame_duration_us: int = 33333  # Default 30fps = 33333us per frame
        self._preload_lead_us: int = 3_000_000  # 3 seconds in microseconds
        self._switch_lead_us: int = 100_000  # 100ms in microseconds

        # INV-PLAYOUT-SWITCH-BEFORE-EXHAUSTION: One-shot violation logging
        self._segment_readiness_violation_logged: bool = False

        # Track successor segment info for logging/diagnostics
        self._successor_loaded: bool = False
        self._successor_asset_path: str | None = None

        # Channel configuration (set by daemon when creating manager)
        self.channel_config: ChannelConfig | None = None

    def stop_channel(self) -> None:
        """
        Enter STOPPED state and stop the producer. No wait for EOF or segment completion.
        Called by ProgramDirector when the last viewer disconnects (StopChannel(channel_id)).
        Health/reconnect logic checks this state and does nothing while STOPPED.
        """
        self._logger.info(
            "[teardown] stopping producer for channel %s (no wait for EOF)", self.channel_id
        )
        self._channel_state = "STOPPED"
        self._segment_end_time_utc = None
        self._switch_state = SwitchState.IDLE
        self._boundary_state = BoundaryState.NONE
        # P12-CORE-001/003: Clear deferred teardown state on explicit stop
        self._teardown_pending = False
        self._teardown_deadline = None
        self._teardown_reason = None
        self._deferred_teardown_triggered = False
        self._converged = False
        self._convergence_deadline = None
        self._last_switch_at_segment_end_utc = None
        self._segment_readiness_violation_logged = False
        # P11D-011 / P11F-005: Cancel deadline-scheduled switch issuance (Timer or call_later handle)
        with self._switch_issue_timer_lock:
            if self._switch_issue_timer is not None:
                self._switch_issue_timer.cancel()
                self._switch_issue_timer = None
        if self._switch_handle is not None:
            self._switch_handle.cancel()
            self._switch_handle = None
        self._pending_fatal = None
        # Reset CT-domain state
        self._segment_ct_start_us = None
        self._segment_frame_count = None
        self._successor_loaded = False
        self._successor_asset_path = None
        self._stop_producer_if_idle()

    def _request_teardown(self, reason: str) -> bool:
        """
        P12-CORE-002 INV-TEARDOWN-STABLE-STATE-001: Request permission to teardown.

        Returns True if teardown may proceed (boundary state is stable).
        Returns False if teardown must be deferred (transient state) or already pending.
        Does NOT execute teardown; caller decides what to do with the result.
        Idempotent: second call while pending is a no-op (does not extend deadline).
        """
        if self._teardown_pending:
            self._logger.debug(
                "INV-TEARDOWN-STABLE-STATE-001: Teardown already pending (reason=%s)",
                reason,
            )
            return False
        if self._boundary_state in _STABLE_STATES:
            self._logger.info(
                "INV-TEARDOWN-STABLE-STATE-001: Teardown permitted (state=%s, reason=%s)",
                self._boundary_state.name,
                reason,
            )
            return True
        now = self.clock.now_utc()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        self._teardown_pending = True
        self._teardown_deadline = now + _TEARDOWN_GRACE_TIMEOUT
        self._teardown_reason = reason
        self._logger.warning(
            "INV-TEARDOWN-STABLE-STATE-001: Teardown DEFERRED (state=%s, reason=%s, deadline=%s)",
            self._boundary_state.name,
            reason,
            self._teardown_deadline.isoformat(),
        )
        return False

    def _get_current_mode(self) -> str:
        """Ask ProgramDirector which mode this channel must be in."""
        mode = self.program_director.get_channel_mode(self.channel_id)
        self.runtime_state.current_mode = mode
        return mode

    def _get_playout_plan(self) -> list[dict[str, Any]]:
        """Ask ScheduleService what should be airing right now for this channel."""
        station_time = self.clock.now_utc()
        playout_plan = self.schedule_service.get_playout_plan_now(self.channel_id, station_time)

        if not playout_plan:
            raise NoScheduleDataError(
                f"No schedule data for channel {self.channel_id} at {station_time}"
            )

        return playout_plan

    # Mock grid: alignment & offset calculation -----------------------------------------

    def _floor_to_grid(self, now: datetime) -> datetime:
        """
        Calculate the grid block start time (floor to nearest grid boundary).
        
        Mock grid uses a fixed 30-minute grid. Blocks start at HH:00 and HH:30.
        
        Args:
            now: Current UTC time
            
        Returns:
            Grid block start time (floored to nearest :00 or :30)
        """
        # Fixed 30-minute grid (mock grid schedule)
        grid_minutes = self._mock_grid_block_minutes
        
        # Get current minute and second
        current_minute = now.minute
        current_second = now.second
        current_microsecond = now.microsecond
        
        # Calculate which grid block we're in
        # Grid blocks are at :00 and :30 (for 30-minute grid)
        block_minute = (current_minute // grid_minutes) * grid_minutes
        
        # Floor to grid boundary: set minutes to block_minute, seconds/microseconds to 0
        block_start = now.replace(minute=block_minute, second=0, microsecond=0)
        
        return block_start

    def _calculate_join_offset(
        self,
        now: datetime,
        block_start: datetime,
        program_duration_seconds: float,
    ) -> tuple[str, float]:
        """
        Calculate join-in-progress offset for viewer tuning in mid-block.
        
        Per NEXTSTEPS.md:
        - If elapsed < program_len → seek into program at elapsed
        - Else → seek into filler at elapsed - program_len
        
        Args:
            now: Current UTC time
            block_start: Grid block start time (from _floor_to_grid)
            program_duration_seconds: Program duration in seconds
            
        Returns:
            Tuple of (content_type, start_pts_ms) where:
            - content_type: "program" or "filler"
            - start_pts_ms: Presentation timestamp offset in milliseconds
        """
        # Calculate elapsed time since block start
        elapsed = (now - block_start).total_seconds()
        
        if elapsed < program_duration_seconds:
            # We're in the program segment
            # Seek into program at elapsed time
            start_pts_ms = int(elapsed * 1000)  # Convert to milliseconds
            return ("program", start_pts_ms)
        else:
            # We're in the filler segment
            # Seek into filler at (elapsed - program_len)
            filler_offset = elapsed - program_duration_seconds
            start_pts_ms = int(filler_offset * 1000)  # Convert to milliseconds
            return ("filler", start_pts_ms)

    def _calculate_filler_offset(
        self,
        master_clock: datetime,
        filler_epoch: datetime,
        filler_duration_seconds: float,
    ) -> float:
        """
        Calculate filler offset for continuous virtual stream.
        
        Per NEXTSTEPS.md:
        filler_offset = (master_clock - filler_epoch) % filler_duration
        
        Args:
            master_clock: Current master clock time
            filler_epoch: Epoch time for filler calculation (when filler "starts")
            filler_duration_seconds: Filler asset duration in seconds
            
        Returns:
            Filler offset in seconds (0 to filler_duration_seconds)
        """
        if filler_epoch is None:
            # Default epoch: use a fixed reference time (e.g., Unix epoch or channel start)
            filler_epoch = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        
        # Calculate time difference
        time_diff = (master_clock - filler_epoch).total_seconds()
        
        # Modulo to get offset within filler duration
        filler_offset = time_diff % filler_duration_seconds
        
        return filler_offset

    def _determine_active_content(
        self,
        now: datetime,
        block_start: datetime,
        program_duration_seconds: float,
    ) -> tuple[str, str, float]:
        """
        Determine which content is active (program or filler) and calculate join offset.
        
        Args:
            now: Current UTC time
            block_start: Grid block start time
            program_duration_seconds: Program duration in seconds
            
        Returns:
            Tuple of (content_type, asset_path, start_pts_ms) where:
            - content_type: "program" or "filler"
            - asset_path: Path to the asset to play
            - start_pts_ms: Presentation timestamp offset in milliseconds
        """
        content_type, start_pts_ms = self._calculate_join_offset(
            now, block_start, program_duration_seconds
        )
        
        if content_type == "program":
            asset_path = self._mock_grid_program_asset_path
        else:
            asset_path = self._mock_grid_filler_asset_path
        
        if not asset_path:
            raise ChannelManagerError(
                f"Phase 0: {content_type} asset path not configured for channel {self.channel_id}"
            )
        
        return (content_type, asset_path, start_pts_ms)

    def _build_mock_grid_playout_plan(
        self,
        now: datetime,
        program_asset_path: str,
        program_duration_seconds: float,
        filler_asset_path: str,
        filler_duration_seconds: float,
    ) -> list[dict[str, Any]]:
        """
        Build playout plan using mock grid + filler model.
        
        Per NEXTSTEPS.md:
        - Calculate grid block start (floor to 30-minute grid)
        - Determine if we're in program or filler segment
        - Calculate join-in-progress offset
        - Return playout plan with correct asset and start_pts
        
        Args:
            now: Current UTC time
            program_asset_path: Path to program asset
            program_duration_seconds: Program duration in seconds
            filler_asset_path: Path to filler asset
            filler_duration_seconds: Filler duration in seconds (typically 3600 for 1-hour filler)
            
        Returns:
            List of playout plan segments (single segment for current content)
        """
        # Calculate grid block start (30-minute grid)
        block_start = self._floor_to_grid(now)
        
        # Determine active content and calculate join offset
        content_type, asset_path, start_pts_ms = self._determine_active_content(
            now, block_start, program_duration_seconds
        )
        
        # Override asset_path with provided paths
        if content_type == "program":
            asset_path = program_asset_path
        else:
            asset_path = filler_asset_path
            # For filler, we need to calculate the filler offset within the filler file
            # This ensures we don't restart from 00:00 each time
            if self._mock_grid_filler_epoch:
                filler_offset_seconds = self._calculate_filler_offset(
                    now, self._mock_grid_filler_epoch, filler_duration_seconds
                )
                # Adjust start_pts to account for filler offset
                # start_pts_ms is already the offset within the current block's filler segment
                # We need to add the filler epoch offset to get the absolute position in the filler file
                filler_absolute_offset_ms = int((filler_offset_seconds + (start_pts_ms / 1000.0)) * 1000)
                start_pts_ms = filler_absolute_offset_ms % int(filler_duration_seconds * 1000)
        
        # Build playout plan segment
        segment = {
            "asset_path": asset_path,
            "start_pts": start_pts_ms,  # Join-in-progress offset in milliseconds
            "content_type": content_type,  # "program" or "filler"
            "block_start_utc": block_start.isoformat(),
            "metadata": {
                "phase": "mock_grid",
                "grid_block_minutes": self._mock_grid_block_minutes,
            },
        }
        
        return [segment]

    def viewer_join(self, session_id: str, session_info: dict[str, Any]) -> None:
        """
        Called when a viewer starts watching this channel.

        INV-VIEWER-LIFECYCLE-001: Thread-safe viewer count transitions.
        Concurrent viewer joins are serialized via _viewer_lock.
        First viewer (0→1) triggers on_first_viewer() exactly once.
        """
        with self._viewer_lock:
            now = self.clock.now_utc()

            if session_id in self.viewer_sessions:
                self.viewer_sessions[session_id]["last_activity"] = now
            else:
                self.viewer_sessions[session_id] = {
                    "session_id": session_id,
                    "channel_id": self.channel_id,
                    "started_at": now,
                    "last_activity": now,
                    "client_info": session_info,
                }

            old_count = self.runtime_state.viewer_count
            self.runtime_state.viewer_count = len(self.viewer_sessions)

            # When first viewer joins after STOPPED, re-enter RUNNING so producer can start.
            if old_count == 0 and self.runtime_state.viewer_count == 1:
                self._channel_state = "RUNNING"
            # Fanout rule: first viewer starts Producer.
            # INV-VIEWER-LIFECYCLE-001: AIR starts exactly once on 0→1 transition
            if old_count == 0 and self.runtime_state.viewer_count == 1:
                self._logger.info(
                    "INV-VIEWER-LIFECYCLE-001: First viewer joined channel %s, starting AIR",
                    self.channel_id
                )
                self.on_first_viewer()

            # If we have an active producer, surface its endpoint for new viewers.
            if self.active_producer:
                self.runtime_state.stream_endpoint = self.active_producer.get_stream_endpoint()

    def viewer_leave(self, session_id: str) -> None:
        """
        Called when a viewer stops watching.

        INV-VIEWER-LIFECYCLE-002: Thread-safe viewer count transitions.
        Concurrent viewer leaves are serialized via _viewer_lock.
        Last viewer (1→0) triggers on_last_viewer() exactly once.
        """
        with self._viewer_lock:
            if session_id in self.viewer_sessions:
                del self.viewer_sessions[session_id]

            old_count = self.runtime_state.viewer_count
            self.runtime_state.viewer_count = len(self.viewer_sessions)

            # Fanout rule: last viewer stops Producer.
            # INV-VIEWER-LIFECYCLE-002: AIR stops exactly once on 1→0 transition
            if old_count == 1 and self.runtime_state.viewer_count == 0:
                self._logger.info(
                    "INV-VIEWER-LIFECYCLE-002: Last viewer left channel %s, stopping AIR",
                    self.channel_id
                )
                self.on_last_viewer()

    # Phase 0 Contract Methods
    def tune_in(self, session_id: str, session_info: dict[str, Any] | None = None) -> None:
        """
        Phase 0 contract: Called when a viewer tunes in to this channel.
        
        Args:
            session_id: Unique identifier for this viewer session
            session_info: Optional metadata about the viewer session
        """
        if session_info is None:
            session_info = {}
        self.viewer_join(session_id, session_info)

    def tune_out(self, session_id: str) -> None:
        """
        Phase 0 contract: Called when a viewer tunes out from this channel.
        
        Args:
            session_id: Unique identifier for this viewer session
        """
        self.viewer_leave(session_id)

    def on_first_viewer(self) -> None:
        """
        Phase 0 contract: Called when the first viewer connects (viewer count goes 0 -> 1).
        
        This ensures the Producer is started when the first viewer arrives.
        """
        if self.runtime_state.viewer_count == 0:
            return  # Not actually first viewer
        
        # Ensure producer is running for first viewer
        if self.runtime_state.viewer_count == 1:
            self._ensure_producer_running()

    def on_last_viewer(self) -> None:
        """
        Phase 0 contract: Called when the last viewer disconnects (viewer count goes 1 -> 0).
        
        Enters STOPPED state and stops the Producer. ProgramDirector typically calls
        stop_channel(channel_id) first; this path ensures we still stop if tune_out is
        invoked without an explicit StopChannel.
        """
        if self.runtime_state.viewer_count != 0:
            return  # Not actually last viewer
        self._channel_state = "STOPPED"
        # Stop producer when no viewers remain
        self._stop_producer_if_idle()

    def _ensure_producer_running(self) -> None:
        """Enforce 'channel goes on-air'."""
        # P12-CORE-005 INV-TEARDOWN-NO-NEW-WORK-001: Do not start when teardown pending
        if self._teardown_pending:
            self._logger.warning(
                "INV-TEARDOWN-NO-NEW-WORK-001: Cannot start channel %s (teardown pending)",
                self.channel_id,
            )
            return
        required_mode = self._get_current_mode()

        # If there's an active producer and it's both in the correct mode and healthy, we're done.
        if (
            self.active_producer
            and self.active_producer.mode.value == required_mode
            and self.active_producer.health() == "running"
        ):
            return

        # Otherwise we need to (re)start.
        if self.active_producer:
            self.active_producer.stop()
            self.active_producer = None

        producer = self._build_producer_for_mode(required_mode)
        if producer is None:
            self.runtime_state.producer_status = "error"
            raise ProducerStartupError(
                f"Channel {self.channel_id}: cannot create Producer for mode '{required_mode}'"
            )

        self.active_producer = producer

        # Get authoritative station time and playout plan.
        station_time = self.clock.now_utc()
        playout_plan = self._get_playout_plan()

        # Ask the Producer to start.
        started_ok = self.active_producer.start(playout_plan, station_time)
        if not started_ok:
            self.runtime_state.producer_status = "error"
            self.active_producer = None
            raise ProducerStartupError(
                f"Channel {self.channel_id}: Producer failed to start in mode '{required_mode}'"
            )

        # Producer is up. Record runtime state.
        self.runtime_state.producer_status = "running"
        self.runtime_state.producer_started_at = station_time
        self.runtime_state.stream_endpoint = self.active_producer.get_stream_endpoint()

        # P12-CORE-010 INV-SESSION-CREATION-UNGATED-001: Session creation never gated on boundary feasibility.
        self._logger.info(
            "INV-SESSION-CREATION-UNGATED-001: Session created for viewer at %s",
            station_time.isoformat() if hasattr(station_time, "isoformat") else station_time,
        )

        # Clock-driven switching: use end_time_utc from schedule for exact grid boundary timing.
        # P11D-009 INV-SCHED-PLAN-BEFORE-EXEC-001: planning_time = station_utc (actual current station time).
        # P12-CORE-010: Boundary feasibility is evaluated after session creation (in tick/convergence); do not gate here.
        station_utc = station_time if station_time.tzinfo else station_time.replace(tzinfo=timezone.utc)
        planning_time = station_utc
        startup_min_lead = STARTUP_LATENCY + MIN_PREFEED_LEAD_TIME
        end_time_str = playout_plan[0].get("end_time_utc")
        if end_time_str:
            self._segment_end_time_utc = datetime.fromisoformat(end_time_str)
            if self._segment_end_time_utc.tzinfo is None:
                self._segment_end_time_utc = self._segment_end_time_utc.replace(tzinfo=timezone.utc)
            # When grid available, replace infeasible first boundary with first feasible; otherwise keep schedule value.
            if (self._segment_end_time_utc - planning_time) < startup_min_lead:
                segment_seconds_meta = playout_plan[0].get("metadata", {}).get("segment_seconds")
                if segment_seconds_meta and segment_seconds_meta > 0:
                    epoch_utc = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
                    self._segment_end_time_utc = self._first_feasible_boundary(
                        planning_time, float(segment_seconds_meta), epoch_utc, min_lead_timedelta=startup_min_lead
                    )
                # Else: keep _segment_end_time_utc from schedule; feasibility evaluated in tick/convergence (P12-CORE-012).
        else:
            # Fallback for legacy/mock schedules without end_time_utc.
            segment_seconds_meta = playout_plan[0].get("metadata", {}).get("segment_seconds")
            if segment_seconds_meta and segment_seconds_meta > 0:
                epoch_utc = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
                self._segment_end_time_utc = self._first_feasible_boundary(
                    planning_time, float(segment_seconds_meta), epoch_utc, min_lead_timedelta=startup_min_lead
                )
            else:
                duration_s = self._segment_duration_seconds(playout_plan[0])
                if duration_s > 0:
                    self._segment_end_time_utc = station_utc + timedelta(seconds=duration_s)
                else:
                    self._segment_end_time_utc = None
        # P12-CORE-010: Do not raise on infeasible first boundary; session is created; convergence handles skip (P12-CORE-012).
        self._switch_state = SwitchState.IDLE
        # P11F-002: Boundary state PLANNED when we have first boundary; switch timer scheduled after LoadPreview
        # P11F-006: Store plan-derived boundary for INV-BOUNDARY-DECLARED-MATCHES-PLAN-001
        if self._segment_end_time_utc is not None:
            self._plan_boundary_ms = int(self._segment_end_time_utc.timestamp() * 1000)
            self._transition_boundary_state(BoundaryState.PLANNED)

        # =======================================================================
        # CT-Domain State Initialization (INV-PLAYOUT-SWITCH-BEFORE-EXHAUSTION)
        # =======================================================================
        # Initialize CT-domain tracking for frame-based exhaustion detection.
        # ct_start_us = 0 because this is the first segment (TimelineController starts at CT=0).
        # For mid-segment joins, the start_pts offset is handled by AIR seeking.
        segment = playout_plan[0]
        config = self.channel_config
        if config and hasattr(config, 'program_format'):
            fps_num = getattr(config.program_format, 'frame_rate_num', 30)
            fps_den = getattr(config.program_format, 'frame_rate_den', 1)
        else:
            fps_num, fps_den = 30, 1
        fps = fps_num / fps_den if fps_den > 0 else 30.0

        self._segment_ct_start_us = 0  # First segment starts at CT=0
        self._segment_frame_duration_us = int(1_000_000 * fps_den / fps_num) if fps_num > 0 else 33333

        # Get frame_count from segment (INV-SCHED-GRID-FILLER-PADDING requires explicit budget)
        frame_count = segment.get("frame_count", -1)
        if frame_count < 0:
            # Fallback: compute from duration_seconds
            duration_s = self._segment_duration_seconds(segment)
            if duration_s > 0:
                frame_count = int(duration_s * fps)
            else:
                frame_count = None  # Unknown - fallback to UTC timing
        self._segment_frame_count = frame_count if frame_count and frame_count > 0 else None

        # Reset successor tracking
        self._successor_loaded = False
        self._successor_asset_path = None

        # P12-CORE-011 INV-STARTUP-CONVERGENCE-001: Session created; convergence until first boundary
        self._converged = False
        self._convergence_deadline = self.clock.now_utc() + MAX_STARTUP_CONVERGENCE_WINDOW

    def _segment_duration_seconds(self, segment: dict[str, Any]) -> float:
        """Duration of segment from schedule (seconds). Uses duration_seconds or metadata.segment_seconds."""
        v = segment.get("duration_seconds")
        if v is not None:
            return float(v)
        v = segment.get("metadata", {}).get("segment_seconds")
        return float(v) if v is not None else 0.0

    def _first_feasible_boundary(
        self,
        planning_time: datetime,
        segment_seconds: float,
        epoch_utc: datetime,
        min_lead_timedelta: timedelta | None = None,
    ) -> datetime:
        """P11D-009/010: First boundary feasible by construction, aligned to grid.

        Planning discards any boundary earlier than planning_time + min_lead.
        Default min_lead = MIN_PREFEED_LEAD_TIME. At channel launch pass min_lead_timedelta =
        STARTUP_LATENCY + MIN_PREFEED_LEAD_TIME for INV-STARTUP-BOUNDARY-FEASIBILITY-001.
        """
        lead = min_lead_timedelta if min_lead_timedelta is not None else MIN_PREFEED_LEAD_TIME
        min_lead_seconds = lead.total_seconds()
        earliest_feasible = planning_time + timedelta(seconds=min_lead_seconds)
        if epoch_utc.tzinfo is None:
            epoch_utc = epoch_utc.replace(tzinfo=timezone.utc)
        if earliest_feasible.tzinfo is None:
            earliest_feasible = earliest_feasible.replace(tzinfo=timezone.utc)
        earliest_s = (earliest_feasible - epoch_utc).total_seconds()
        boundary_s = math.ceil(earliest_s / segment_seconds) * segment_seconds
        return epoch_utc + timedelta(seconds=boundary_s)

    def _cancel_transient_timers(self) -> None:
        """
        P12-CORE-009 INV-TERMINAL-TIMER-CLEARED-001: Cancel all transient boundary timers.
        Called when entering FAILED_TERMINAL to prevent ghost timer callbacks. Idempotent.
        """
        cancelled = False
        with self._switch_issue_timer_lock:
            if self._switch_issue_timer is not None:
                self._switch_issue_timer.cancel()
                self._switch_issue_timer = None
                cancelled = True
        if self._switch_handle is not None:
            self._switch_handle.cancel()
            self._switch_handle = None
            cancelled = True
        if cancelled:
            self._logger.info(
                "INV-TERMINAL-TIMER-CLEARED-001: Cancelled transient timers on terminal entry",
            )

    def _transition_boundary_state(self, new_state: BoundaryState) -> None:
        """P11F-002 INV-BOUNDARY-LIFECYCLE-001: Enforce unidirectional transitions; illegal → FAILED_TERMINAL."""
        old_state = self._boundary_state
        allowed = _ALLOWED_BOUNDARY_TRANSITIONS.get(old_state, set())
        if new_state not in allowed:
            self._logger.error(
                "INV-BOUNDARY-LIFECYCLE-001 VIOLATION: Illegal transition %s -> %s",
                old_state.name,
                new_state.name,
            )
            self._boundary_state = BoundaryState.FAILED_TERMINAL
            self._pending_fatal = SchedulingError(
                f"Illegal boundary state transition: {old_state.name} -> {new_state.name}"
            )
            # P12-CORE-009 INV-TERMINAL-TIMER-CLEARED-001: Cancel transient timers before deferred teardown
            self._cancel_transient_timers()
            # P12-CORE-003: FAILED_TERMINAL is stable; trigger deferred teardown if pending
            if self._teardown_pending:
                self._logger.info(
                    "INV-TEARDOWN-STABLE-STATE-001: Deferred teardown now permitted (state=FAILED_TERMINAL)",
                )
                self._execute_deferred_teardown()
            return
        self._logger.info(
            "INV-BOUNDARY-LIFECYCLE-001: Boundary transition %s -> %s",
            old_state.name,
            new_state.name,
        )
        self._boundary_state = new_state
        # P12-CORE-011 INV-STARTUP-CONVERGENCE-001: First successful boundary → converged
        if new_state == BoundaryState.LIVE and not self._converged:
            self._converged = True
            self._convergence_deadline = None
            self._logger.info(
                "INV-STARTUP-CONVERGENCE-001: Session converged after first boundary",
            )
        # P12-CORE-009 INV-TERMINAL-TIMER-CLEARED-001: Cancel transient timers on FAILED_TERMINAL entry
        if new_state == BoundaryState.FAILED_TERMINAL:
            self._cancel_transient_timers()
        if new_state == BoundaryState.NONE:
            self._plan_boundary_ms = None
        # P12-CORE-003 INV-TEARDOWN-STABLE-STATE-001: Entering stable state with teardown pending → execute deferred
        if self._teardown_pending and new_state in _STABLE_STATES:
            self._logger.info(
                "INV-TEARDOWN-STABLE-STATE-001: Deferred teardown now permitted (state=%s)",
                new_state.name,
            )
            self._execute_deferred_teardown()

    def _execute_deferred_teardown(self) -> None:
        """
        P12-CORE-003: Execute deferred teardown (called when boundary enters stable state).
        Clears pending state and signals ProgramDirector to destroy channel (poll deferred_teardown_triggered).
        MUST NOT call _request_teardown() or recurse into state transitions.
        """
        was_state = self._boundary_state
        reason = self._teardown_reason or "unspecified"
        self._logger.info(
            "INV-TEARDOWN-STABLE-STATE-001: Executing deferred teardown (was_state=%s, reason=%s)",
            was_state.name,
            reason,
        )
        self._teardown_pending = False
        self._teardown_deadline = None
        self._teardown_reason = None
        self._deferred_teardown_triggered = True

    def deferred_teardown_triggered(self) -> bool:
        """P12-CORE-003/006: True when deferred teardown executed; ProgramDirector should destroy channel."""
        return self._deferred_teardown_triggered

    def _check_convergence_timeout(self) -> bool:
        """
        P12-CORE-013 INV-STARTUP-CONVERGENCE-001: Returns True if session should continue, False if timed out.

        If not converged and convergence_deadline has expired, transitions to FAILED_TERMINAL and returns False.
        """
        if self._converged:
            return True
        if self._convergence_deadline is None:
            return True
        now = self.clock.now_utc()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        if now >= self._convergence_deadline:
            self._logger.error(
                "INV-STARTUP-CONVERGENCE-001 FATAL: Convergence timeout expired "
                "after %s without successful boundary transition",
                MAX_STARTUP_CONVERGENCE_WINDOW,
            )
            self._pending_fatal = SchedulingError(
                "Startup convergence timeout: no boundary executed within window"
            )
            self._transition_boundary_state(BoundaryState.FAILED_TERMINAL)
            return False
        return True

    def _advance_to_next_boundary_after_skip(self, skipped_boundary_time: datetime) -> None:
        """
        P12-CORE-012: After skipping an infeasible boundary, set _segment_end_time_utc to the next boundary.

        Uses get_playout_plan_now at skipped_boundary_time; does not change boundary state or switch state.
        """
        next_plan = self.schedule_service.get_playout_plan_now(self.channel_id, skipped_boundary_time)
        if next_plan:
            next_seg = next_plan[0]
            next_end_str = next_seg.get("end_time_utc")
            if next_end_str:
                self._segment_end_time_utc = datetime.fromisoformat(next_end_str)
                if self._segment_end_time_utc.tzinfo is None:
                    self._segment_end_time_utc = self._segment_end_time_utc.replace(tzinfo=timezone.utc)
                self._plan_boundary_ms = int(self._segment_end_time_utc.timestamp() * 1000)
            else:
                next_duration = self._segment_duration_seconds(next_seg)
                if next_duration > 0:
                    if skipped_boundary_time.tzinfo is None:
                        skipped_boundary_time = skipped_boundary_time.replace(tzinfo=timezone.utc)
                    self._segment_end_time_utc = skipped_boundary_time + timedelta(seconds=next_duration)
                    self._plan_boundary_ms = int(self._segment_end_time_utc.timestamp() * 1000)
                else:
                    self._segment_end_time_utc = None
                    self._plan_boundary_ms = None
        else:
            self._segment_end_time_utc = None
            self._plan_boundary_ms = None

    @property
    def is_live(self) -> bool:
        """
        P12-CORE-007 INV-LIVE-SESSION-AUTHORITY-001: True only when durably live.

        A channel is durably live only when _boundary_state == LIVE. Before LIVE, session is
        provisional; FAILED_TERMINAL and NONE are not live. Use this property for external
        liveness queries (metrics, EPG, overlays). is_live == False does NOT mean channel is
        stopped—it means session is provisional or dead.
        """
        return self._boundary_state == BoundaryState.LIVE

    @property
    def converged(self) -> bool:
        """
        P12-CORE-011 INV-STARTUP-CONVERGENCE-001: True after first successful boundary transition.

        During startup convergence (_converged False), infeasible boundaries are skipped.
        Once True, never reverts for this session.
        """
        return self._converged

    def _guard_switch_issuance(self, boundary_time: datetime) -> bool:
        """P11F-004 INV-SWITCH-ISSUANCE-ONESHOT-001: Returns True if issuance is allowed."""
        if self._boundary_state in (
            BoundaryState.SWITCH_ISSUED,
            BoundaryState.LIVE,
        ):
            self._logger.warning(
                "INV-SWITCH-ISSUANCE-ONESHOT-001: Suppressed duplicate issuance for %s (state=%s)",
                boundary_time.isoformat(),
                self._boundary_state.name,
            )
            return False
        if self._boundary_state == BoundaryState.FAILED_TERMINAL:
            self._logger.error(
                "INV-SWITCH-ISSUANCE-ONESHOT-001 FATAL: Attempted issuance for %s but boundary is FAILED_TERMINAL",
                boundary_time.isoformat(),
            )
            self._pending_fatal = SchedulingError(
                f"Attempted switch issuance for failed boundary {boundary_time}"
            )
            return False
        return True

    def _schedule_switch_issuance(self, boundary_time: datetime) -> None:
        """P11D-011 INV-SWITCH-ISSUANCE-DEADLINE-001: Register switch issuance; P11F-005: use call_later when loop set."""
        if boundary_time.tzinfo is None:
            boundary_time = boundary_time.replace(tzinfo=timezone.utc)
        _ISSUANCE_BUFFER = timedelta(seconds=0.5)
        issue_at = boundary_time - MIN_PREFEED_LEAD_TIME - _ISSUANCE_BUFFER
        now = self.clock.now_utc()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        delay_s = (issue_at - now).total_seconds()
        if self._loop is not None:
            self._loop.call_soon_thread_safe(
                self._schedule_switch_issuance_on_loop,
                boundary_time,
                delay_s,
            )
            return
        with self._switch_issue_timer_lock:
            if self._switch_issue_timer is not None:
                self._switch_issue_timer.cancel()
                self._switch_issue_timer = None
        if delay_s <= 0:
            self._on_switch_issue_deadline(boundary_time)
            return
        timer = threading.Timer(delay_s, self._on_switch_issue_deadline, args=[boundary_time])
        with self._switch_issue_timer_lock:
            self._switch_issue_timer = timer
        timer.start()

    def _schedule_switch_issuance_on_loop(
        self, boundary_time: datetime, delay_s: float
    ) -> None:
        """P11F-005: Runs on event loop thread; schedules _on_switch_issue_deadline via call_later."""
        if self._loop is None:
            return
        if self._switch_handle is not None:
            self._switch_handle.cancel()
            self._switch_handle = None
        if delay_s <= 0:
            self._on_switch_issue_deadline(boundary_time)
            return
        self._switch_handle = self._loop.call_later(
            delay_s,
            self._on_switch_issue_deadline,
            boundary_time,
        )
        self._logger.info(
            "INV-SWITCH-ISSUANCE-DEADLINE-001: Switch scheduled for %s (delay=%.2fs)",
            boundary_time.isoformat(),
            delay_s,
        )

    def _on_switch_issue_deadline(self, boundary_time: datetime) -> None:
        """P11D-011: Called at issue_at. P11F-003: Failure is TERMINAL. P11F-004: Guard one-shot."""
        # P11F-004: One-shot guard — suppress duplicate or FATAL if already terminal
        if not self._guard_switch_issuance(boundary_time):
            return
        # Clear timer/handle (fired)
        with self._switch_issue_timer_lock:
            self._switch_issue_timer = None
        if self._switch_handle is not None:
            self._switch_handle = None
        now = self.clock.now_utc()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        issue_at = boundary_time - MIN_PREFEED_LEAD_TIME
        if boundary_time.tzinfo is None:
            boundary_time = boundary_time.replace(tzinfo=timezone.utc)
        # Timer may fire a few ms late; treat as late only if >50ms past issue_at (timer resolution, not lead inflation)
        if (now - issue_at).total_seconds() > 0.05:
            self._boundary_state = BoundaryState.FAILED_TERMINAL
            self._pending_fatal = SchedulingError(
                "INV-SWITCH-ISSUANCE-DEADLINE-001 FATAL: Late issuance (issue_at was "
                f"{issue_at.isoformat()}, now={now.isoformat()}). Issuance must be deadline-scheduled."
            )
            self._logger.error(
                "INV-SWITCH-ISSUANCE-DEADLINE-001 FATAL: Late switch issuance | channel=%s boundary=%s",
                self.channel_id, boundary_time.isoformat(),
            )
            return
        producer = self.active_producer
        if producer is None or self._channel_state == "STOPPED":
            return
        if self._segment_end_time_utc != boundary_time:
            return
        if self._switch_state != SwitchState.PREVIEW_LOADED:
            return
        # P11F-006: target_boundary_ms MUST match plan-derived boundary
        target_boundary_ms = int(boundary_time.timestamp() * 1000)
        if self._plan_boundary_ms is not None and target_boundary_ms != self._plan_boundary_ms:
            self._logger.error(
                "INV-BOUNDARY-DECLARED-MATCHES-PLAN-001 FATAL: target_boundary_ms=%d does not match plan boundary=%d",
                target_boundary_ms,
                self._plan_boundary_ms,
            )
            self._boundary_state = BoundaryState.FAILED_TERMINAL
            self._pending_fatal = SchedulingError(
                f"Boundary mismatch: target={target_boundary_ms}, plan={self._plan_boundary_ms}"
            )
            return
        self._transition_boundary_state(BoundaryState.SWITCH_ISSUED)
        # P11F-003 INV-SWITCH-ISSUANCE-TERMINAL-001: Any exception → FAILED_TERMINAL; no retry
        try:
            ok = producer.switch_to_live(target_boundary_time_utc=boundary_time)
        except Exception as e:
            self._logger.error(
                "INV-SWITCH-ISSUANCE-TERMINAL-001 FATAL: Switch issuance failed for boundary %s: %s",
                boundary_time.isoformat(),
                e,
            )
            self._boundary_state = BoundaryState.FAILED_TERMINAL
            self._pending_fatal = SchedulingError(
                f"Switch issuance failed for boundary {boundary_time}: {e}"
            )
            self._pending_fatal.__cause__ = e
            return
        if not ok:
            # AIR returned not ready / protocol violation — treat as terminal
            self._boundary_state = BoundaryState.FAILED_TERMINAL
            self._pending_fatal = SchedulingError(
                f"SwitchToLive returned False for boundary {boundary_time}"
            )
            return
        self._switch_state = SwitchState.SWITCH_ARMED
        self._logger.info(
            "Channel %s switch armed at deadline T-%.3fs (boundary=%.3fs, successor=%s)",
            self.channel_id, (boundary_time - now).total_seconds(), boundary_time.timestamp(),
            self._successor_asset_path,
        )
        # Completion is polled by tick() Phase 3; do not call _handle_switch_complete from timer thread

    def tick(self) -> None:
        """
        Clock-driven segment advancement. Called periodically (e.g. from daemon health loop).

        INV-PLAYOUT-SWITCH-BEFORE-EXHAUSTION:
        - Preloads successor segment before current segment exhausts its frame budget
        - Switches to successor before CT reaches exhaustion point
        - Falls back to UTC timing if CT-domain data is unavailable

        INV-PLAYOUT-NO-PAD-WHEN-PREVIEW-READY:
        - If past exhaustion and preview is ready, switch immediately
        - This prevents pad frames when successor content is available
        """
        # P12-CORE-004 INV-TEARDOWN-GRACE-TIMEOUT-001: Grace timeout check FIRST (before any other tick logic)
        if self._teardown_pending and self._teardown_deadline is not None:
            now = self.clock.now_utc()
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            if now >= self._teardown_deadline:
                requested_at = self._teardown_deadline - _TEARDOWN_GRACE_TIMEOUT
                duration = (now - requested_at).total_seconds()
                reason = self._teardown_reason or "unspecified"
                self._logger.warning(
                    "INV-TEARDOWN-GRACE-TIMEOUT-001: Grace timeout expired in state %s after %.1fs (reason=%s)",
                    self._boundary_state.name,
                    duration,
                    reason,
                )
                self._pending_fatal = SchedulingError(
                    f"Teardown grace timeout in state {self._boundary_state.name}"
                )
                self._transition_boundary_state(BoundaryState.FAILED_TERMINAL)
                return
        # P12-CORE-005 INV-TEARDOWN-NO-NEW-WORK-001: Skip boundary work when teardown pending
        if self._teardown_pending:
            self._logger.debug(
                "INV-TEARDOWN-NO-NEW-WORK-001: Skipping boundary work (teardown pending)",
            )
            return
        # P12-CORE-008 INV-TERMINAL-SCHEDULER-HALT-001: Skip boundary work when terminal failure
        if self._boundary_state == BoundaryState.FAILED_TERMINAL:
            self._logger.debug(
                "INV-TERMINAL-SCHEDULER-HALT-001: Skipping boundary work (terminal failure)",
            )
            return
        # P11D-011: Re-raise fatal from deadline callback (e.g. late issuance or AIR rejection)
        if self._pending_fatal is not None:
            e = self._pending_fatal
            self._pending_fatal = None
            raise e
        # P11F-004 INV-SWITCH-ISSUANCE-ONESHOT-001: Never re-evaluate boundary already processed
        if self._boundary_state in (
            BoundaryState.SWITCH_ISSUED,
            BoundaryState.LIVE,
            BoundaryState.FAILED_TERMINAL,
        ):
            return
        if self._channel_state == "STOPPED" or self.active_producer is None:
            return
        producer = self.active_producer
        if not getattr(producer, "load_preview", None) or not getattr(producer, "switch_to_live", None):
            return
        if self._segment_end_time_utc is None:
            return

        now = self.clock.now_utc()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        segment_end = self._segment_end_time_utc
        if segment_end.tzinfo is None:
            segment_end = segment_end.replace(tzinfo=timezone.utc)

        # P12-CORE-013 INV-STARTUP-CONVERGENCE-001: Convergence timeout (before boundary work)
        if not self._check_convergence_timeout():
            return

        # P12-CORE-012 INV-STARTUP-CONVERGENCE-001: Infeasible boundary → skip (pre-convergence) or FATAL (post-convergence)
        lead_time = segment_end - now
        if lead_time < MIN_PREFEED_LEAD_TIME:
            if not self._converged:
                self._logger.info(
                    "STARTUP_BOUNDARY_SKIPPED: boundary=%s lead_time=%s min_required=%s",
                    segment_end.isoformat(),
                    lead_time,
                    MIN_PREFEED_LEAD_TIME,
                )
                self._advance_to_next_boundary_after_skip(segment_end)
                return
            self._logger.error(
                "INV-STARTUP-BOUNDARY-FEASIBILITY-001 FATAL: Infeasible boundary post-convergence",
            )
            self._pending_fatal = SchedulingError(
                "Infeasible boundary post-convergence: boundary_time < now + MIN_PREFEED_LEAD_TIME"
            )
            self._transition_boundary_state(BoundaryState.FAILED_TERMINAL)
            return

        # =======================================================================
        # Two-phase clock-driven switching (INV-PLAYOUT-SWITCH-BEFORE-EXHAUSTION)
        # =======================================================================
        # Phase 1: Preload (T - preload_lead, typically 3s before boundary)
        #   - Call LoadPreview() to start filling Air's preview buffer
        #   - State: IDLE → PREVIEW_LOADED
        #
        # Phase 2: Switch (T - switch_lead, typically 100ms before boundary)
        #   - Start calling SwitchToLive() to arm the switch
        #   - State: PREVIEW_LOADED → SWITCH_ARMED
        #   - Continue polling SwitchToLive() until it returns success
        #
        # NOTE: Currently uses UTC timing. Full CT-domain switching requires
        # AIR to expose GetCTCursor RPC. When available, replace UTC comparisons
        # with: current_ct_us >= ct_exhaust_us - lead_us
        preload_at = segment_end - timedelta(seconds=self._preload_lead_seconds)

        # Phase 1: Preload - load next asset into preview buffer
        if self._switch_state == SwitchState.IDLE and now >= preload_at:
            next_plan = self.schedule_service.get_playout_plan_now(self.channel_id, segment_end)
            if next_plan:
                next_seg = next_plan[0]
                asset_path = next_seg.get("asset_path")
                if asset_path:
                    # Frame-indexed execution (INV-FRAME-001/002/003)
                    # Get fps from channel config or default to 30fps
                    config = self.channel_config
                    if config and hasattr(config, 'program_format'):
                        fps_num = getattr(config.program_format, 'frame_rate_num', 30)
                        fps_den = getattr(config.program_format, 'frame_rate_den', 1)
                    else:
                        fps_num, fps_den = 30, 1
                    fps = fps_num / fps_den if fps_den > 0 else 30.0

                    # Convert start_pts_ms to start_frame (direction: time → frame ok here, at schedule boundary)
                    start_pts_ms = int(next_seg.get("start_pts", 0))
                    start_frame = int((start_pts_ms / 1000.0) * fps) if fps > 0 else 0

                    # Get frame_count from schedule if available
                    frame_count = next_seg.get("frame_count", -1)
                    segment_type = next_seg.get("segment_type", "content")

                    # =========================================================
                    # INV-SCHED-GRID-FILLER-PADDING: Validate filler frame_count
                    # =========================================================
                    # Filler segments MUST have explicit frame_count >= 0.
                    # frame_count=-1 (play until EOF) is forbidden for filler.
                    if segment_type == "filler" and frame_count < 0:
                        self._logger.error(
                            "INV-SCHED-GRID-FILLER-PADDING VIOLATION: "
                            "Channel %s filler segment has frame_count=%d (must be >= 0). "
                            "Filler will play to EOF which may cause buffer starvation. "
                            "asset=%s",
                            self.channel_id, frame_count, asset_path,
                        )

                    # Fallback: compute from duration_seconds if frame_count not explicit
                    if frame_count < 0:
                        duration_s = next_seg.get("duration_seconds", 0)
                        if duration_s > 0:
                            frame_count = int(duration_s * fps)

                    # P11E-003/004: Lead time at LoadPreview issuance; log violation and record metrics.
                    load_preview_lead = segment_end - now
                    load_preview_lead_ms = int(load_preview_lead.total_seconds() * 1000)
                    if prefeed_lead_time_ms is not None:
                        prefeed_lead_time_ms.labels(channel_id=self.channel_id).observe(
                            load_preview_lead_ms
                        )
                    if load_preview_lead < MIN_PREFEED_LEAD_TIME:
                        self._logger.error(
                            "INV-CONTROL-NO-POLL-001 VIOLATION: LoadPreview issued with insufficient lead time. "
                            "channel_id=%s, boundary=%s, lead_time_ms=%d, min_required_ms=%d. "
                            "This is a Core scheduling bug.",
                            self.channel_id,
                            segment_end.isoformat(),
                            load_preview_lead_ms,
                            MIN_PREFEED_LEAD_TIME_MS,
                        )
                        if prefeed_lead_time_violations_total is not None:
                            prefeed_lead_time_violations_total.labels(
                                channel_id=self.channel_id
                            ).inc()

                    ok = producer.load_preview(
                        asset_path,
                        start_frame=start_frame,
                        frame_count=frame_count,
                        fps_numerator=fps_num,
                        fps_denominator=fps_den,
                    )
                    if ok:
                        self._transition_boundary_state(BoundaryState.PRELOAD_ISSUED)
                        self._switch_state = SwitchState.PREVIEW_LOADED
                        self._successor_loaded = True
                        self._successor_asset_path = asset_path
                        # P11D-011: Schedule switch issuance after LoadPreview (P11F-002: PRELOAD_ISSUED → SWITCH_SCHEDULED)
                        if self._segment_end_time_utc is not None:
                            self._schedule_switch_issuance(self._segment_end_time_utc)
                        self._transition_boundary_state(BoundaryState.SWITCH_SCHEDULED)
                        # Contract-level observability: CORE_INTENT_FRAME_RANGE (once per segment)
                        end_frame = start_frame + frame_count - 1 if frame_count >= 0 else -1
                        ct_start_us = 0
                        if self._segment_ct_start_us is not None and self._segment_frame_count is not None:
                            ct_start_us = self._segment_ct_start_us + (
                                self._segment_frame_count * self._segment_frame_duration_us
                            )
                        mt_start_us = 0
                        start_time_str = next_seg.get("start_time_utc")
                        if start_time_str:
                            try:
                                dt = datetime.fromisoformat(
                                    start_time_str.replace("Z", "+00:00")
                                )
                                if dt.tzinfo is None:
                                    dt = dt.replace(tzinfo=timezone.utc)
                                mt_start_us = int(dt.timestamp() * 1_000_000)
                            except (ValueError, TypeError):
                                pass
                        channel_manager_launch.log_core_intent_frame_range(
                            channel_id=self.channel_id,
                            segment_id=next_seg.get("segment_id", ""),
                            asset_path=asset_path,
                            start_frame=start_frame,
                            end_frame=end_frame,
                            fps=fps,
                            CT_start_us=ct_start_us,
                            MT_start_us=mt_start_us,
                        )
                        self._logger.info(
                            "Channel %s preload: LoadPreview(%s) at T-%.1fs "
                            "(start_frame=%d, frame_count=%d, type=%s)",
                            self.channel_id, asset_path, (segment_end - now).total_seconds(),
                            start_frame, frame_count, segment_type,
                        )

        # Phase 2: Switch issuance is deadline-scheduled (P11D-011 INV-SWITCH-ISSUANCE-DEADLINE-001),
        # not cadence-detected. _schedule_switch_issuance(boundary) was called at plan time; timer fires at issue_at.

        # Phase 3: Poll for switch completion while SWITCH_ARMED
        if self._switch_state == SwitchState.SWITCH_ARMED and segment_end != self._last_switch_at_segment_end_utc:
            ok = producer.switch_to_live(target_boundary_time_utc=segment_end)  # P11C-004
            if ok:
                self._handle_switch_complete(producer, segment_end, now)
            else:
                # Switch not complete yet (NOT_READY) - keep polling
                # State remains SWITCH_ARMED; LoadPreview is blocked.
                #
                # INV-PLAYOUT-SWITCH-BEFORE-EXHAUSTION:
                # If we're past the boundary and still not complete, log violation (one-shot).
                # This indicates successor segment was not ready before CT exhausted
                # the active segment's frame budget.
                #
                # INV-PLAYOUT-NO-PAD-WHEN-PREVIEW-READY:
                # Even if past exhaustion, keep trying SwitchToLive. When preview becomes
                # ready, the switch will succeed immediately on the next poll. This prevents
                # prolonged pad frame emission when successor content becomes available.
                #
                # NOTE: Full implementation of INV-PLAYOUT-NO-PAD-WHEN-PREVIEW-READY requires
                # AIR to expose buffer state (live_buffer_empty, preview_ready) via RPC.
                # Current implementation relies on polling SwitchToLive which will succeed
                # as soon as preview is ready.
                if now > segment_end and not self._segment_readiness_violation_logged:
                    delta_ms = (now.timestamp() - segment_end.timestamp()) * 1000
                    self._logger.warning(
                        "INV-PLAYOUT-SWITCH-BEFORE-EXHAUSTION VIOLATION: "
                        "Channel %s exhaustion point passed without successor ready | "
                        "boundary=%.3fs | now=%.3fs | delta_ms=%.1f | successor_loaded=%s",
                        self.channel_id, segment_end.timestamp(), now.timestamp(), delta_ms,
                        self._successor_loaded,
                    )
                    self._segment_readiness_violation_logged = True

    def _handle_switch_complete(
        self, producer: Producer, segment_end: datetime, now: datetime
    ) -> None:
        """Handle switch completion: log timing, advance to next segment."""
        self._transition_boundary_state(BoundaryState.LIVE)
        # Reset one-shot violation flag for next segment
        self._segment_readiness_violation_logged = False

        seg_ts = segment_end.timestamp()
        actual_ts = now.timestamp()
        delta_ms = (actual_ts - seg_ts) * 1000

        # ===================================================================
        # INV-P8-SWITCH-TIMING: Diagnostic tripwire for late switches
        # ===================================================================
        # Core MUST complete switches no later than the scheduled boundary.
        # Switches that complete AFTER the boundary indicate a timing violation.
        #
        # If this warning fires, investigate:
        # - Was preload_lead_seconds too short for buffer fill?
        # - Was switch_lead_seconds too short?
        # - Was tick() not called frequently enough?
        if actual_ts > seg_ts:
            self._logger.warning(
                "INV-P8-SWITCH-TIMING VIOLATION: Channel %s switch completed %.1fms AFTER boundary | "
                "scheduled=%.3fs | actual=%.3fs",
                self.channel_id, delta_ms, seg_ts, actual_ts,
            )
        else:
            self._logger.info(
                "Channel %s switch complete: %.1fms before boundary | scheduled=%.3fs | actual=%.3fs",
                self.channel_id, -delta_ms, seg_ts, actual_ts,
            )

        self._last_switch_at_segment_end_utc = segment_end

        # Reset successor tracking for next cycle
        self._successor_loaded = False
        self._successor_asset_path = None

        # Advance to next segment: use end_time_utc from schedule for exact timing.
        next_plan = self.schedule_service.get_playout_plan_now(self.channel_id, segment_end)
        if next_plan:
            next_seg = next_plan[0]
            next_end_str = next_seg.get("end_time_utc")
            if next_end_str:
                self._segment_end_time_utc = datetime.fromisoformat(next_end_str)
                if self._segment_end_time_utc.tzinfo is None:
                    self._segment_end_time_utc = self._segment_end_time_utc.replace(tzinfo=timezone.utc)
            else:
                # Fallback for legacy schedules
                next_duration = self._segment_duration_seconds(next_seg)
                if next_duration > 0:
                    self._segment_end_time_utc = segment_end + timedelta(seconds=next_duration)
                else:
                    self._segment_end_time_utc = None

            # =======================================================================
            # CT-Domain State Update (INV-PLAYOUT-SWITCH-BEFORE-EXHAUSTION)
            # =======================================================================
            # Update CT-domain tracking for the new segment.
            # New segment's ct_start_us = previous segment's ct_exhaust_us
            # (CT is continuous across segment boundaries)
            if self._segment_ct_start_us is not None and self._segment_frame_count is not None:
                # Advance CT start to previous exhaustion point
                self._segment_ct_start_us += self._segment_frame_count * self._segment_frame_duration_us
            else:
                # Unknown CT state - can't track CT-domain switching
                self._segment_ct_start_us = None

            # Get frame_count for new segment
            config = self.channel_config
            if config and hasattr(config, 'program_format'):
                fps_num = getattr(config.program_format, 'frame_rate_num', 30)
                fps_den = getattr(config.program_format, 'frame_rate_den', 1)
            else:
                fps_num, fps_den = 30, 1
            fps = fps_num / fps_den if fps_den > 0 else 30.0
            self._segment_frame_duration_us = int(1_000_000 * fps_den / fps_num) if fps_num > 0 else 33333

            frame_count = next_seg.get("frame_count", -1)
            if frame_count < 0:
                duration_s = self._segment_duration_seconds(next_seg)
                if duration_s > 0:
                    frame_count = int(duration_s * fps)
                else:
                    frame_count = None
            self._segment_frame_count = frame_count if frame_count and frame_count > 0 else None

            self._switch_state = SwitchState.IDLE
            # P11F-002: LIVE → PLANNED when we have next boundary; switch timer scheduled in tick() after LoadPreview
            # P11F-006: Store plan-derived boundary for next switch
            if self._segment_end_time_utc is not None:
                self._plan_boundary_ms = int(self._segment_end_time_utc.timestamp() * 1000)
            self._transition_boundary_state(BoundaryState.PLANNED)
        else:
            self._segment_end_time_utc = None
            self._segment_ct_start_us = None
            self._segment_frame_count = None
            self._switch_state = SwitchState.IDLE  # Switch completed, no more segments
            self._transition_boundary_state(BoundaryState.NONE)

    def _stop_producer_if_idle(self) -> None:
        """Stop the Producer if there are no active viewers."""
        self._check_teardown_completion()
        if self.runtime_state.viewer_count != 0:
            return

        producer = self.active_producer
        if producer:
            if not producer.teardown_in_progress():
                self._teardown_started_station = self._station_now()
                self._teardown_reason = "viewer_inactive"
                self._logger.info(
                    "Channel %s initiating producer teardown (reason=%s)",
                    self.channel_id,
                    self._teardown_reason,
                )
                producer.request_teardown(
                    reason=self._teardown_reason,
                    timeout=self._teardown_timeout_seconds,
                )
            return

        self.runtime_state.producer_status = "stopped"
        self.runtime_state.stream_endpoint = None

    def check_health(self) -> None:
        """Poll Producer health and update runtime_state. Includes segment supervisor loop for Phase 0."""
        # Phase 8.5/8.6: Channel with zero viewers must not have an active producer. Suppress all
        # restart logic (health, EOF handling, reconnect). Next viewer tune-in will start producer.
        viewer_count = len(self.viewer_sessions)
        if viewer_count == 0:
            if self.active_producer is not None:
                self._logger.info(
                    "Channel %s: zero viewers, stopping producer (no restarts)",
                    self.channel_id,
                )
                self.active_producer.stop()
                self.active_producer = None
            self._channel_state = "STOPPED"
            self.runtime_state.viewer_count = 0
            self.runtime_state.producer_status = "stopped"
            self.runtime_state.stream_endpoint = None
            return
        # When last viewer disconnected, ProgramDirector called StopChannel; do nothing until next viewer.
        if self._channel_state == "STOPPED":
            return
        self._check_teardown_completion()

        if self.active_producer is None:
            self.runtime_state.producer_status = "stopped"
            self.runtime_state.last_health = "stopped"
            return

        health_status = self.active_producer.health()
        producer_state: ProducerState = self.active_producer.get_state()

        self.runtime_state.last_health = health_status
        self.runtime_state.producer_status = producer_state.status.value
        self.runtime_state.stream_endpoint = producer_state.output_url
        self.runtime_state.producer_started_at = producer_state.started_at
        
        # Phase 8.7: ChannelManager MUST NOT self-restart or self-reconnect. On producer/segment
        # exit (e.g. EOF), we stop and clear; we do NOT restart the producer or launch next segment.
        if isinstance(self.active_producer, Phase8AirProducer):
            if self.active_producer.air_process and self.active_producer.air_process.poll() is not None:
                exit_code = self.active_producer.air_process.returncode
                n = len(self.viewer_sessions)
                self._logger.info(
                    "Channel %s: segment process exited (code=%s, viewers=%s); not restarting (Phase 8.7)",
                    self.channel_id, exit_code, n,
                )
                self.active_producer.stop()
                self.active_producer = None
                self._channel_state = "STOPPED"
                self.runtime_state.producer_status = "stopped"
                self.runtime_state.stream_endpoint = None

    def attach_metrics_publisher(self, publisher: "MetricsPublisher") -> None:
        """Register the metrics publisher responsible for this channel."""
        self._metrics_publisher = publisher

    def get_channel_metrics(self) -> "ChannelMetricsSample | None":
        """Return the latest metrics sample, if publishing is configured."""
        if not self._metrics_publisher:
            return None
        return self._metrics_publisher.get_latest_sample()

    def populate_metrics_sample(self, sample: "ChannelMetricsSample") -> None:
        """Populate the provided sample with the most recent channel state."""
        self._check_teardown_completion()
        viewer_count = len(self.viewer_sessions)
        producer = self.active_producer

        producer_state = "stopped"
        segment_id: str | None = None
        segment_position = 0.0
        dropped_frames: int | None = None
        queued_frames: int | None = None

        if producer is not None:
            status_obj = getattr(producer, "status", ProducerStatus.RUNNING)
            if isinstance(status_obj, ProducerStatus):
                producer_state = status_obj.value
            else:
                producer_state = str(status_obj)

            seg_id, seg_position = producer.get_segment_progress()
            segment_id = seg_id
            segment_position = seg_position
            dropped_frames, queued_frames = producer.get_frame_counters()

        active = viewer_count > 0 or producer_state == ProducerStatus.RUNNING.value

        sample.channel_state = "active" if active else "idle"
        sample.viewer_count = viewer_count
        sample.producer_state = producer_state
        sample.segment_id = segment_id
        sample.segment_position = segment_position
        sample.dropped_frames = dropped_frames
        sample.queued_frames = queued_frames

    def _station_now(self) -> float:
        """Get current station time as float timestamp."""
        current_time = self.clock.now_utc()
        if hasattr(current_time, "timestamp"):
            return current_time.timestamp()
        return float(current_time)

    def _check_teardown_completion(self) -> None:
        if self._teardown_started_station is None:
            return
        producer = self.active_producer
        if producer is None:
            self._finalize_teardown(completed=True)
            return
        if producer.teardown_in_progress():
            return
        completed = producer.status == ProducerStatus.STOPPED
        self._finalize_teardown(completed=completed)

    def _finalize_teardown(self, *, completed: bool) -> None:
        duration = 0.0
        if self._teardown_started_station is not None:
            duration = max(0.0, self._station_now() - self._teardown_started_station)
        reason = self._teardown_reason or "unspecified"
        producer = self.active_producer

        if completed:
            self._logger.info(
                "Channel %s producer teardown completed in %.3fs (reason=%s)",
                self.channel_id,
                duration,
                reason,
            )
        else:
            self._logger.warning(
                "Channel %s producer teardown timed out after %.3fs (reason=%s); forcing stop",
                self.channel_id,
                duration,
                reason,
            )
            if producer:
                producer.stop()

        self.active_producer = None
        self.runtime_state.producer_status = "stopped"
        self.runtime_state.stream_endpoint = None
        self._teardown_started_station = None
        self._teardown_reason = None

    def _build_producer_for_mode(self, mode: str) -> Producer | None:
        """
        Factory hook: build the correct Producer implementation for the given mode.

        When _blockplan_mode is True, returns BlockPlanProducer for autonomous
        BlockPlan execution. Otherwise, returns Phase8AirProducer for legacy
        LoadPreview/SwitchToLive execution.

        INV-VIEWER-LIFECYCLE: Producer selection is deterministic based on mode flag.
        """
        if self._blockplan_mode:
            self._logger.info(
                "Channel %s: Building BlockPlanProducer (mode=%s)",
                self.channel_id, mode
            )
            return BlockPlanProducer(
                channel_id=self.channel_id,
                configuration={"block_duration_ms": 30_000},
                channel_config=self._get_channel_config(),
                schedule_service=self.schedule_service,
                clock=self.clock,
            )
        else:
            # Legacy Phase8 mode - return None (or Phase8AirProducer if available)
            # This method is typically overridden by the runtime
            _ = mode  # avoid unused var lint
            return None

    def _get_channel_config(self) -> ChannelConfig:
        """Get or create ChannelConfig for this channel."""
        # Try to get from ProgramDirector if available
        if hasattr(self.program_director, 'get_channel_config'):
            config = self.program_director.get_channel_config(self.channel_id)
            if config:
                return config
        # Fall back to mock config
        return MOCK_CHANNEL_CONFIG

    def set_blockplan_mode(self, enabled: bool) -> None:
        """
        Enable or disable BlockPlan mode.

        When enabled, ChannelManager uses BlockPlanProducer which provides:
        - Autonomous block execution (no mid-block Core↔AIR communication)
        - 2-block lookahead feeding
        - Viewer-lifecycle-driven start/stop

        Args:
            enabled: True to use BlockPlanProducer, False for legacy Phase8AirProducer
        """
        self._blockplan_mode = enabled
        self._logger.info(
            "Channel %s: BlockPlan mode %s",
            self.channel_id, "enabled" if enabled else "disabled"
        )


# ----------------------------------------------------------------------
# Mock schedule implementations
# ----------------------------------------------------------------------


class MockGridScheduleService:
    """ScheduleService implementation for mock grid + filler model.
    
    Implements the ScheduleService protocol using a fixed 30-minute grid
    and program + filler model. Used when running with --mock-schedule-grid.
    """

    def __init__(
        self,
        clock: MasterClock,
        program_asset_path: str,
        program_duration_seconds: float,
        filler_asset_path: str,
        filler_duration_seconds: float = 3600.0,  # Default 1-hour filler
        grid_block_minutes: int = 30,  # Fixed 30-minute grid
    ):
        self.clock = clock
        self.program_asset_path = program_asset_path
        self.program_duration_seconds = program_duration_seconds
        self.filler_asset_path = filler_asset_path
        self.filler_duration_seconds = filler_duration_seconds
        self.grid_block_minutes = grid_block_minutes
        self.filler_epoch = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def load_schedule(self, channel_id: str) -> tuple[bool, str | None]:
        """
        No-op schedule loading (mock grid doesn't use schedule files).
        
        Returns:
            (success, error_message) tuple - always (True, None)
        """
        return (True, None)

    def _floor_to_grid(self, now: datetime) -> datetime:
        """Calculate grid block start time (floor to nearest grid boundary)."""
        current_minute = now.minute
        block_minute = (current_minute // self.grid_block_minutes) * self.grid_block_minutes
        return now.replace(minute=block_minute, second=0, microsecond=0)

    def _calculate_join_offset(
        self,
        now: datetime,
        block_start: datetime,
        program_duration_seconds: float,
    ) -> tuple[str, float]:
        """Calculate join-in-progress offset."""
        elapsed = (now - block_start).total_seconds()
        
        if elapsed < program_duration_seconds:
            # In program segment
            start_pts_ms = int(elapsed * 1000)
            return ("program", start_pts_ms)
        else:
            # In filler segment
            filler_offset = elapsed - program_duration_seconds
            start_pts_ms = int(filler_offset * 1000)
            return ("filler", start_pts_ms)

    def _calculate_filler_offset(
        self,
        master_clock: datetime,
        filler_epoch: datetime,
        filler_duration_seconds: float,
    ) -> float:
        """Calculate filler offset for continuous virtual stream."""
        time_diff = (master_clock - filler_epoch).total_seconds()
        return time_diff % filler_duration_seconds

    def get_playout_plan_now(
        self,
        channel_id: str,
        at_station_time: datetime,
    ) -> list[dict[str, Any]]:
        """
        Return playout plan using grid + filler model.

        Returns the complete block structure (program + filler) with proper metadata
        for clock-driven switching. This enables tick() to preload filler into preview
        BEFORE the program ends.

        INV-PREVIEW-NEVER-EMPTY: CORE must ensure preview has a segment loaded before
        the current live segment exhausts. Returning both segments allows tick() to
        determine the successor and preload it in time.

        Returns:
            List of segments in playback order, starting from the segment containing
            at_station_time. Each segment includes:
            - asset_path: Path to media file
            - start_pts: Join offset in milliseconds (for first segment only)
            - segment_type: "content" or "filler"
            - start_time_utc: When segment starts (ISO format)
            - end_time_utc: When segment ends (ISO format)
            - duration_seconds: Segment duration
            - frame_count: Frame budget (fps * duration)
        """
        now = at_station_time
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # Calculate grid block boundaries
        block_start = self._floor_to_grid(now)
        block_end = block_start + timedelta(minutes=self.grid_block_minutes)

        # Segment boundaries within block
        program_end = block_start + timedelta(seconds=self.program_duration_seconds)
        filler_duration = (block_end - program_end).total_seconds()

        # Default fps for frame_count calculation (30fps)
        fps = 30.0

        # Determine which segment we're in and build the segment list
        content_type, start_pts_ms = self._calculate_join_offset(
            now, block_start, self.program_duration_seconds
        )

        segments = []

        if content_type == "program":
            # Currently in program segment - return program + filler
            elapsed = (now - block_start).total_seconds()
            remaining_program = self.program_duration_seconds - elapsed

            program_segment = {
                "asset_path": self.program_asset_path,
                "start_pts": start_pts_ms,
                "segment_type": "content",
                "start_time_utc": block_start.isoformat(),
                "end_time_utc": program_end.isoformat(),
                "duration_seconds": remaining_program,  # Remaining from join point
                "frame_count": int(remaining_program * fps),
                "metadata": {
                    "phase": "mock_grid",
                    "grid_block_minutes": self.grid_block_minutes,
                    "full_segment_duration": self.program_duration_seconds,
                },
            }
            segments.append(program_segment)

            # Add filler segment (successor) so tick() can preload it
            if filler_duration > 0:
                # INV-SCHED-GRID-FILLER-PADDING: Filler has explicit frame_count
                filler_frame_count = int(filler_duration * fps)
                filler_segment = {
                    "asset_path": self.filler_asset_path,
                    "start_pts": 0,  # Filler starts at frame 0
                    "segment_type": "filler",
                    "start_time_utc": program_end.isoformat(),
                    "end_time_utc": block_end.isoformat(),
                    "duration_seconds": filler_duration,
                    "frame_count": filler_frame_count,
                    "metadata": {
                        "phase": "mock_grid",
                        "grid_block_minutes": self.grid_block_minutes,
                    },
                }
                segments.append(filler_segment)
        else:
            # Currently in filler segment
            # Calculate filler join offset for continuous virtual stream
            filler_offset_seconds = self._calculate_filler_offset(
                now, self.filler_epoch, self.filler_duration_seconds
            )
            block_filler_offset_seconds = start_pts_ms / 1000.0
            filler_absolute_offset_seconds = (
                filler_offset_seconds + block_filler_offset_seconds
            ) % self.filler_duration_seconds

            elapsed_in_filler = (now - program_end).total_seconds()
            remaining_filler = filler_duration - elapsed_in_filler

            filler_segment = {
                "asset_path": self.filler_asset_path,
                "start_pts": int(filler_absolute_offset_seconds * 1000),
                "segment_type": "filler",
                "start_time_utc": program_end.isoformat(),
                "end_time_utc": block_end.isoformat(),
                "duration_seconds": remaining_filler,  # Remaining from join point
                "frame_count": int(remaining_filler * fps),
                "metadata": {
                    "phase": "mock_grid",
                    "grid_block_minutes": self.grid_block_minutes,
                    "full_segment_duration": filler_duration,
                },
            }
            segments.append(filler_segment)

            # Add NEXT block's program as successor so tick() can preload it
            next_block_start = block_end
            next_program_end = next_block_start + timedelta(seconds=self.program_duration_seconds)
            next_program_segment = {
                "asset_path": self.program_asset_path,
                "start_pts": 0,  # Next block starts at frame 0
                "segment_type": "content",
                "start_time_utc": next_block_start.isoformat(),
                "end_time_utc": next_program_end.isoformat(),
                "duration_seconds": self.program_duration_seconds,
                "frame_count": int(self.program_duration_seconds * fps),
                "metadata": {
                    "phase": "mock_grid",
                    "grid_block_minutes": self.grid_block_minutes,
                },
            }
            segments.append(next_program_segment)

        return segments


class MockAlternatingScheduleService:
    """ScheduleService that alternates two assets (e.g. SampleA / SampleB) for Air harness testing.

    Segment boundaries are driven by process exit (natural EOF), not wall-clock. When the
    playout process exits, health-check calls get_playout_plan_now() to get the next asset
    and start_pts; segment_seconds is used only to pick which asset (A/B) and join offset.
    Each process runs until natural EOF; asset duration is never used to forcibly stop.
    """

    MOCK_AB_CHANNEL_ID = "test-1"

    def __init__(
        self,
        clock: MasterClock,
        asset_a_path: str,
        asset_b_path: str,
        segment_seconds: float = 10.0,
    ):
        self.clock = clock
        self.asset_a_path = asset_a_path
        self.asset_b_path = asset_b_path
        self.segment_seconds = segment_seconds
        self._loaded_channels: set[str] = set()
        self._lock = threading.Lock()
        self._epoch = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def load_schedule(self, channel_id: str) -> tuple[bool, str | None]:
        if channel_id != self.MOCK_AB_CHANNEL_ID:
            return (False, f"Alternating schedule only supports channel '{self.MOCK_AB_CHANNEL_ID}'")
        with self._lock:
            self._loaded_channels.add(channel_id)
        return (True, None)

    def get_playout_plan_now(
        self,
        channel_id: str,
        at_station_time: datetime,
    ) -> list[dict[str, Any]]:
        """Return current segment: A or B depending on (time // segment_seconds) % 2, with join offset."""
        with self._lock:
            if channel_id != self.MOCK_AB_CHANNEL_ID or channel_id not in self._loaded_channels:
                return []
        now = at_station_time
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        total_seconds = (now - self._epoch).total_seconds()
        segment_index = int(total_seconds // self.segment_seconds)
        use_a = (segment_index % 2) == 0
        offset_in_segment = total_seconds % self.segment_seconds
        start_pts_ms = int(offset_in_segment * 1000)
        asset_path = self.asset_a_path if use_a else self.asset_b_path
        content_type = "a" if use_a else "b"
        segment = {
            "asset_path": asset_path,
            "start_pts": start_pts_ms,
            "content_type": content_type,
            "segment_index": segment_index,
            "metadata": {"phase": "mock_ab", "segment_seconds": self.segment_seconds},
        }
        return [segment]


# ----------------------------------------------------------------------
# Phase 8 Implementations
# ----------------------------------------------------------------------


def _resolve_mock_asset_path() -> Path:
    """Resolve path to assets/samplecontent.mp4 (Phase 8 mock schedule)."""
    # Try repo assets path, then cwd-relative, then path from this file up to repo root
    _here = Path(__file__).resolve()
    repo_root = _here.parents[5]  # runtime -> retrovue -> src -> core -> pkg -> repo
    for candidate in [
        Path("/opt/retrovue/assets/samplecontent.mp4"),
        repo_root / "assets" / "samplecontent.mp4",
        Path.cwd() / "assets" / "samplecontent.mp4",
        Path.cwd() / "samplecontent.mp4",
    ]:
        if candidate.exists():
            return candidate
    # Return repo default even if missing so startup succeeds; playout will fail with a clear error
    return Path("/opt/retrovue/assets/samplecontent.mp4")


class Phase8MockScheduleService:
    """ScheduleService for Phase 8 when no --schedule-dir is provided.

    Provides a single channel "mock" with one item: assets/samplecontent.mp4,
    always active (long duration from epoch). Used so Phase 8 runs without
    requiring a schedule directory.
    """

    MOCK_CHANNEL_ID = "mock"

    def __init__(self, clock: MasterClock):
        self.clock = clock
        asset_path = _resolve_mock_asset_path()
        # One item: from epoch, 1 year duration so always "now"
        self._schedule = [
            {
                "id": "mock-segment",
                "asset_path": str(asset_path),
                "start_time_utc": "1970-01-01T00:00:00Z",
                "duration_seconds": 365 * 24 * 3600,
                "metadata": {},
            }
        ]
        self._loaded_channels: set[str] = set()
        self._lock = threading.Lock()

    def load_schedule(self, channel_id: str) -> tuple[bool, str | None]:
        """Accept only the mock channel; no disk I/O."""
        if channel_id != self.MOCK_CHANNEL_ID:
            return (False, "Schedule file not found (mock schedule: use channel 'mock')")
        with self._lock:
            self._loaded_channels.add(channel_id)
        return (True, None)

    def get_playout_plan_now(
        self,
        channel_id: str,
        at_station_time: datetime,
    ) -> list[dict[str, Any]]:
        """Return single segment for mock channel (same structure as Phase8ScheduleService)."""
        with self._lock:
            if channel_id != self.MOCK_CHANNEL_ID or channel_id not in self._loaded_channels:
                return []
        item = self._schedule[0]
        segment = {
            "asset_id": item.get("id", ""),
            "asset_path": item.get("asset_path", ""),
            "start_time": item.get("start_time_utc"),
            "duration_seconds": item.get("duration_seconds", 0),
            "metadata": item.get("metadata", {}),
        }
        return [segment]


class Phase8ScheduleService:
    """ScheduleService implementation that reads from schedule.json files.
    
    Implements the ScheduleService protocol required by runtime ChannelManager.
    This is an internal implementation detail.
    """

    def __init__(self, schedule_dir: Path, clock: MasterClock):
        self.schedule_dir = schedule_dir
        self.clock = clock
        self._schedules: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def load_schedule(self, channel_id: str) -> tuple[bool, str | None]:
        """Load schedule.json for a channel.
        
        Returns:
            (success, error_message) tuple.
        """
        schedule_file = self.schedule_dir / f"{channel_id}.json"
        if not schedule_file.exists():
            return (False, "Schedule file not found")

        try:
            with open(schedule_file, "r") as f:
                data = json.load(f)

            with self._lock:
                self._schedules[channel_id] = data.get("schedule", [])
            return (True, None)
        except json.JSONDecodeError as e:
            error_msg = f"Malformed JSON in schedule for {channel_id}: {e}"
            print(error_msg, file=sys.stderr)
            with self._lock:
                self._schedules[channel_id] = []
            return (False, error_msg)
        except (KeyError, ValueError) as e:
            error_msg = f"Invalid schedule data for {channel_id}: {e}"
            print(error_msg, file=sys.stderr)
            with self._lock:
                self._schedules[channel_id] = []
            return (False, error_msg)

    def get_playout_plan_now(
        self,
        channel_id: str,
        at_station_time: datetime,
    ) -> list[dict[str, Any]]:
        """Return the resolved segment sequence that should be airing 'right now' on this channel.
        
        Per ChannelManagerContract.md (Phase 8):
        - Selects active ScheduleItem based on current time
        - Returns playout plan with single asset for Phase 8
        """
        with self._lock:
            schedule = self._schedules.get(channel_id, [])

        # Select active ScheduleItem
        # Ensure at_station_time is timezone-aware (UTC)
        now = at_station_time
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        active_items = []
        for item in schedule:
            start_str = item.get("start_time_utc")
            duration = item.get("duration_seconds", 0)

            if not start_str or duration is None:
                continue

            try:
                # Parse ISO 8601 UTC timestamp
                start_time_str = start_str.replace("Z", "+00:00")
                start_time = datetime.fromisoformat(start_time_str)
                if start_time.tzinfo is None:
                    start_time = start_time.replace(tzinfo=timezone.utc)

                # Calculate end_time = start_time + duration_seconds
                end_time = start_time + timedelta(seconds=duration)

                # Active if: start_time_utc ≤ now < start_time_utc + duration_seconds
                if start_time <= now < end_time:
                    active_items.append((item, start_time))
            except (ValueError, TypeError):
                continue

        if not active_items:
            return []  # No active item

        # Select earliest start_time_utc
        active_items.sort(key=lambda x: x[1])
        active_item = active_items[0][0]

        # Phase 8: Return single-segment playout plan
        # Map ScheduleItem to playout plan segment
        segment = {
            "asset_id": active_item.get("id", ""),
            "asset_path": active_item.get("asset_path", ""),
            "start_time": active_item.get("start_time_utc"),
            "duration_seconds": active_item.get("duration_seconds", 0),
            "metadata": active_item.get("metadata", {}),
        }
        return [segment]


class Phase8ProgramDirector:
    """ProgramDirector implementation (always returns 'normal' mode).
    
    Implements the ProgramDirector protocol required by runtime ChannelManager.
    This is an internal implementation detail.
    """

    def get_channel_mode(self, channel_id: str) -> str:
        """Return the required mode for this channel (always 'normal' in Phase 8)."""
        return "normal"


class Phase8AirProducer(Producer):
    """Producer that spawns an Air process to play video for the schedule.

    ChannelManager spawns Air (playout engine) processes to actually play content.
    ChannelManager does NOT spawn ProgramDirector or the main retrovue process;
    ProgramDirector spawns ChannelManager when one doesn't exist for the channel.

    Supports clock-driven segment switching via load_preview() and switch_to_live()
    called by ChannelManager tick (schedule advances because time advanced, not EOF).
    """

    def __init__(
        self,
        channel_id: str,
        configuration: dict[str, Any],
        channel_config: ChannelConfig | None = None,
    ):
        super().__init__(channel_id, ProducerMode.NORMAL, configuration)
        self.air_process: channel_manager_launch.ProcessHandle | None = None
        self.socket_path: Path | None = None
        self.reader_socket_queue: Any = None  # queue.Queue: accepted UDS socket from Air after AttachStream
        self._stream_endpoint = f"/channel/{channel_id}.ts"
        self._grpc_addr: str | None = None  # Set after start(); used for LoadPreview/SwitchToLive
        self.channel_config = channel_config if channel_config is not None else MOCK_CHANNEL_CONFIG

    def start(self, playout_plan: list[dict[str, Any]], start_at_station_time: datetime) -> bool:
        """Start output by spawning an Air process. Builds PlayoutRequest, launches Air via stdin."""
        if not playout_plan:
            return False

        segment = playout_plan[0]
        asset_path = segment.get("asset_path")
        if not asset_path:
            return False

        # Use start_pts from playout plan if provided (Phase 0 join-in-progress)
        # Otherwise default to 0 (Phase 8 behavior)
        start_pts = segment.get("start_pts", 0)
        
        playout_request = {
            "asset_path": asset_path,
            "start_pts": start_pts,  # Phase 0: join-in-progress offset in milliseconds
            "mode": "LIVE",
            "channel_id": self.channel_id,
            "metadata": segment.get("metadata", {}),
            "segment_id": segment.get("segment_id", ""),
            "start_time_utc": segment.get("start_time_utc"),
        }

        try:
            self._logger.info("Playout engine: AIR (no fallback)")
            socket_path_arg = self.socket_path if self.socket_path else None

            process, socket_path, reader_socket_queue, grpc_addr = channel_manager_launch.launch_air(
                playout_request=playout_request,
                channel_config=self.channel_config,
                ts_socket_path=socket_path_arg,
            )
            self.air_process = process
            self.socket_path = socket_path
            self.reader_socket_queue = reader_socket_queue
            self._grpc_addr = grpc_addr
            self.status = ProducerStatus.RUNNING
            self.started_at = start_at_station_time
            self.output_url = self._stream_endpoint
            return True
        except Exception as e:
            self._logger.error(f"Failed to launch Air for {self.channel_id}: {e}")
            self.status = ProducerStatus.ERROR
            return False

    def stop(self) -> bool:
        """Stop the producer by terminating the Air process."""
        if self.air_process:
            # Only terminate if process is still running
            if self.air_process.poll() is None:
                try:
                    channel_manager_launch.terminate_air(self.air_process)
                except Exception as e:
                    self._logger.error(f"Error terminating Air for {self.channel_id}: {e}")
            self.air_process = None
        self._grpc_addr = None

        # Phase 0: Don't clear socket_path on stop - we'll reuse it for next segment
        # self.socket_path = None  # Keep socket path for continuity
        self.status = ProducerStatus.STOPPED
        self.output_url = None
        self._teardown_cleanup()
        return True

    def play_content(self, content: ContentSegment) -> bool:
        """Not used (single file playout)."""
        return True

    def get_stream_endpoint(self) -> str | None:
        """Return stream endpoint URL."""
        return self.output_url

    def health(self) -> str:
        """Report Producer health."""
        if self.status == ProducerStatus.RUNNING and self.air_process:
            if self.air_process.poll() is None:
                return "running"
            return "stopped"
        if self.status == ProducerStatus.ERROR:
            return "degraded"
        return "stopped"

    def get_producer_id(self) -> str:
        """Get unique identifier for this producer."""
        return f"air_{self.channel_id}"

    def on_paced_tick(self, t_now: float, dt: float) -> None:
        """Advance producer state using pacing ticks (minimal implementation)."""
        self._advance_teardown(dt)

    def load_preview(
        self,
        asset_path: str,
        start_frame: int,
        frame_count: int,
        fps_numerator: int,
        fps_denominator: int,
    ) -> bool:
        """Load next asset into Air preview slot (frame-indexed execution, INV-FRAME-001/002/003).

        Args:
            asset_path: Fully-qualified path to media file
            start_frame: First frame index within asset (0-based, INV-FRAME-001)
            frame_count: Exact number of frames to play (INV-FRAME-002)
            fps_numerator: Frame rate numerator (e.g. 30000 for 29.97fps, INV-FRAME-003)
            fps_denominator: Frame rate denominator (e.g. 1001 for 29.97fps, INV-FRAME-003)

        Returns:
            True if preview loaded successfully, False otherwise.
        """
        if not self._grpc_addr:
            self._logger.warning("Channel %s: load_preview skipped (no grpc_addr)", self.channel_id)
            return False
        try:
            ok = channel_manager_launch.air_load_preview(
                self._grpc_addr,
                channel_id_int=self.channel_config.channel_id_int,
                asset_path=asset_path,
                start_frame=start_frame,
                frame_count=frame_count,
                fps_numerator=fps_numerator,
                fps_denominator=fps_denominator,
            )
            if not ok:
                self._logger.warning("Channel %s: Air LoadPreview returned success=false", self.channel_id)
            return ok
        except Exception as e:
            self._logger.warning("Channel %s: LoadPreview failed: %s", self.channel_id, e)
            return False

    def switch_to_live(self, target_boundary_time_utc: datetime | None = None) -> bool:
        """Promote Air preview to live (clock-driven; no EOF). Returns success.

        P11D-005: INV-CONTROL-NO-POLL-001 — no retry. PROTOCOL_VIOLATION or NOT_READY raise.
        P11C-004: INV-BOUNDARY-DECLARED-001 — pass target_boundary_time_utc so Air executes at deadline.
        """
        if not self._grpc_addr:
            self._logger.warning("Channel %s: switch_to_live skipped (no grpc_addr)", self.channel_id)
            return False
        target_ms = 0
        if target_boundary_time_utc is not None:
            target_ms = int(target_boundary_time_utc.timestamp() * 1000)
            self._logger.info(
                "INV-CONTROL-NO-POLL-001: Switch scheduled for %d", target_ms
            )
            # P11E-003/004: Lead time at SwitchToLive issuance; log violation and record metrics.
            now_utc = datetime.now(timezone.utc)
            switch_lead = target_boundary_time_utc - now_utc
            switch_lead_ms = int(switch_lead.total_seconds() * 1000)
            if switch_lead_time_ms is not None:
                switch_lead_time_ms.labels(channel_id=self.channel_id).observe(switch_lead_ms)
            if switch_lead < MIN_PREFEED_LEAD_TIME:
                self._logger.error(
                    "INV-CONTROL-NO-POLL-001 VIOLATION: SwitchToLive issued too late. "
                    "channel_id=%s, boundary=%s, lead_time_ms=%d, min_required_ms=%d. "
                    "AIR may return PROTOCOL_VIOLATION.",
                    self.channel_id,
                    target_boundary_time_utc.isoformat(),
                    switch_lead_ms,
                    MIN_PREFEED_LEAD_TIME_MS,
                )
                if switch_lead_time_violations_total is not None:
                    switch_lead_time_violations_total.labels(
                        channel_id=self.channel_id
                    ).inc()
        try:
            ok, _result_code, _violation_reason = channel_manager_launch.air_switch_to_live(
                self._grpc_addr,
                channel_id_int=self.channel_config.channel_id_int,
                target_boundary_time_ms=target_ms,
            )
            return ok
        except channel_manager_launch.SwitchTimingError as e:
            self._logger.error("Channel %s: INV-CONTROL-NO-POLL-001 VIOLATION: %s", self.channel_id, e)
            raise
        except channel_manager_launch.SwitchProtocolError as e:
            self._logger.error("Channel %s: INV-CONTROL-NO-POLL-001 VIOLATION: %s", self.channel_id, e)
            raise
        except Exception as e:
            self._logger.warning("Channel %s: SwitchToLive failed: %s", self.channel_id, e)
            return False


# =============================================================================
# BlockPlanProducer: Viewer-lifecycle-driven BlockPlan execution
# =============================================================================


class BlockPlanProducer(Producer):
    """
    Producer that uses BlockPlan-based execution via PlayoutSession.

    This producer implements the on-demand playout model:
    - AIR starts on first viewer (0 → 1 transition)
    - AIR stops on last viewer (1 → 0 transition)
    - No viewer can start/stop AIR directly
    - BlockPlan execution is autonomous (no mid-block Core↔AIR traffic)

    ChannelManager owns the viewer lifecycle; BlockPlanProducer owns the
    AIR subprocess and BlockPlan feeding.

    Thread Safety:
    - All public methods are thread-safe via _lock
    - Viewer churn (rapid join/leave) cannot double-start or double-stop
    - Concurrent viewer_join/leave are serialized
    """

    # Block duration in milliseconds (configurable via configuration)
    DEFAULT_BLOCK_DURATION_MS = 30_000  # 30 seconds

    def __init__(
        self,
        channel_id: str,
        configuration: dict[str, Any],
        channel_config: ChannelConfig | None = None,
        schedule_service: ScheduleService | None = None,
        clock: MasterClock | None = None,
    ):
        super().__init__(channel_id, ProducerMode.NORMAL, configuration)
        self.channel_config = channel_config if channel_config is not None else MOCK_CHANNEL_CONFIG
        self.schedule_service = schedule_service
        self.clock = clock

        # PlayoutSession instance (created on start, destroyed on stop)
        self._session: "PlayoutSession | None" = None

        # Thread-safety lock for all state mutations
        self._lock = threading.RLock()

        # State tracking
        self._started = False
        self._start_count = 0  # Debug: track start attempts
        self._stop_count = 0   # Debug: track stop attempts

        # Block generation state
        self._block_index = 0
        self._next_block_start_ms = 0
        self._block_duration_ms = configuration.get(
            "block_duration_ms", self.DEFAULT_BLOCK_DURATION_MS
        )

        # UDS socket for TS output
        self._socket_path: Path | None = None
        self._stream_endpoint = f"/channel/{channel_id}.ts"

        # Program format for encoding (extracted from ChannelConfig.program_format)
        pf = self.channel_config.program_format
        self._program_format = {
            "video": {
                "width": pf.video_width,
                "height": pf.video_height,
                "frame_rate": {
                    "num": pf.frame_rate_num,
                    "den": pf.frame_rate_den,
                },
            },
            "audio": {
                "sample_rate": pf.audio_sample_rate,
                "channels": pf.audio_channels,
            },
        }

    def start(self, playout_plan: list[dict[str, Any]], start_at_station_time: datetime) -> bool:
        """
        Start BlockPlan execution.

        Called by ChannelManager.on_first_viewer() when viewer count goes 0→1.
        Creates PlayoutSession, seeds initial 2 blocks, and begins execution.

        INV-VIEWER-LIFECYCLE-001: AIR starts exactly once per first-viewer event.
        """
        with self._lock:
            if self._started:
                self._logger.warning(
                    "INV-VIEWER-LIFECYCLE-001: Channel %s already started (start_count=%d)",
                    self.channel_id, self._start_count
                )
                return True  # Idempotent - already running

            self._start_count += 1
            self._logger.info(
                "INV-VIEWER-LIFECYCLE-001: Channel %s starting BlockPlan execution "
                "(start_count=%d, station_time=%s)",
                self.channel_id, self._start_count, start_at_station_time
            )

            try:
                # Import here to avoid circular imports
                from .playout_session import PlayoutSession, BlockPlan

                # Setup socket path
                self._socket_path = Path(f"/tmp/retrovue/air/{self.channel_id}.sock")
                self._socket_path.parent.mkdir(parents=True, exist_ok=True)

                # Create PlayoutSession
                self._session = PlayoutSession(
                    channel_id=self.channel_id,
                    channel_id_int=self.channel_config.channel_id_int,
                    ts_socket_path=self._socket_path,
                    program_format=self._program_format,
                    on_block_complete=self._on_block_complete,
                    on_session_end=self._on_session_end,
                )

                # Start AIR subprocess
                join_utc_ms = int(start_at_station_time.timestamp() * 1000)
                if not self._session.start(join_utc_ms=join_utc_ms):
                    raise RuntimeError("PlayoutSession.start() failed")

                # Generate and seed initial 2 blocks
                block_a = self._generate_block(playout_plan, 0)
                block_b = self._generate_block(playout_plan, 1)

                if not self._session.seed(block_a, block_b):
                    raise RuntimeError("PlayoutSession.seed() failed")

                # Feed a third block to maintain 2-block lookahead
                block_c = self._generate_block(playout_plan, 2)
                self._session.feed(block_c)

                self._started = True
                self.status = ProducerStatus.RUNNING
                self.started_at = start_at_station_time
                self.output_url = self._stream_endpoint

                self._logger.info(
                    "Channel %s: BlockPlan execution started, seeded 2 blocks",
                    self.channel_id
                )
                return True

            except Exception as e:
                self._logger.error(
                    "Channel %s: BlockPlan start failed: %s",
                    self.channel_id, e
                )
                self._cleanup()
                self.status = ProducerStatus.ERROR
                return False

    def stop(self) -> bool:
        """
        Stop BlockPlan execution.

        Called by ChannelManager.on_last_viewer() when viewer count goes 1→0.
        Stops PlayoutSession, terminates AIR, cleans up resources.

        INV-VIEWER-LIFECYCLE-002: AIR stops exactly once per last-viewer event.
        """
        with self._lock:
            if not self._started:
                self._logger.debug(
                    "Channel %s: stop() called but not started (stop_count=%d)",
                    self.channel_id, self._stop_count
                )
                return True  # Idempotent - already stopped

            self._stop_count += 1
            self._logger.info(
                "INV-VIEWER-LIFECYCLE-002: Channel %s stopping BlockPlan execution "
                "(stop_count=%d)",
                self.channel_id, self._stop_count
            )

            self._cleanup()

            self._started = False
            self.status = ProducerStatus.STOPPED
            self.output_url = None
            self._teardown_cleanup()

            return True

    def _cleanup(self):
        """Clean up PlayoutSession and resources."""
        if self._session:
            try:
                self._session.stop(reason="last_viewer_left")
            except Exception as e:
                self._logger.warning(
                    "Channel %s: Session stop error: %s",
                    self.channel_id, e
                )
            self._session = None

        # Reset block generation state for next start
        self._block_index = 0
        self._next_block_start_ms = 0

    def _generate_block(
        self,
        playout_plan: list[dict[str, Any]],
        block_offset: int,
    ) -> "BlockPlan":
        """
        Generate a BlockPlan from the playout plan.

        For now, generates fixed-duration blocks from the first segment.
        Future: proper segment slicing based on schedule.
        """
        from .playout_session import BlockPlan

        block_index = self._block_index + block_offset
        start_ms = self._next_block_start_ms + (block_offset * self._block_duration_ms)
        end_ms = start_ms + self._block_duration_ms

        # Get asset from playout plan
        if playout_plan:
            segment = playout_plan[0]
            asset_path = segment.get("asset_path", "assets/SampleA.mp4")
        else:
            asset_path = "assets/SampleA.mp4"

        block = BlockPlan(
            block_id=f"BLOCK-{self.channel_id}-{block_index}",
            channel_id=self.channel_config.channel_id_int,
            start_utc_ms=start_ms,
            end_utc_ms=end_ms,
            segments=[{
                "segment_index": 0,
                "asset_uri": asset_path,
                "asset_start_offset_ms": 0,
                "segment_duration_ms": self._block_duration_ms,
            }],
        )

        # Advance state for next generation
        if block_offset == 0:
            self._block_index += 1
            self._next_block_start_ms = end_ms

        return block

    def _on_block_complete(self, block_id: str):
        """Callback when a block completes - feed next block."""
        with self._lock:
            if not self._started or not self._session:
                return

            self._logger.debug(
                "Channel %s: Block %s completed, feeding next",
                self.channel_id, block_id
            )

            # Generate and feed next block
            # Note: Using empty playout_plan - real implementation would
            # fetch fresh schedule data
            next_block = self._generate_block([], 0)
            self._session.feed(next_block)

    def _on_session_end(self, reason: str):
        """Callback when session ends unexpectedly."""
        self._logger.info(
            "Channel %s: Session ended: %s",
            self.channel_id, reason
        )

    def play_content(self, content: ContentSegment) -> bool:
        """Not used in BlockPlan mode (blocks are fed instead)."""
        return True

    def get_stream_endpoint(self) -> str | None:
        """Return stream endpoint URL."""
        return self.output_url

    def health(self) -> str:
        """Report Producer health."""
        with self._lock:
            if not self._started:
                return "stopped"
            if self._session and self._session.is_running:
                return "running"
            if self.status == ProducerStatus.ERROR:
                return "degraded"
            return "stopped"

    def get_producer_id(self) -> str:
        """Get unique identifier for this producer."""
        return f"blockplan_{self.channel_id}"

    def on_paced_tick(self, t_now: float, dt: float) -> None:
        """
        Advance producer state using pacing ticks.

        In BlockPlan mode, most work happens asynchronously in AIR.
        This tick only handles teardown advancement.
        """
        # Handle graceful teardown if in progress
        if self._advance_teardown(dt):
            return

        # BlockPlan execution is autonomous - no per-tick work needed
        # Block feeding happens via on_block_complete callback

    def get_socket_path(self) -> Path | None:
        """Return the UDS socket path for TS output."""
        with self._lock:
            return self._socket_path


