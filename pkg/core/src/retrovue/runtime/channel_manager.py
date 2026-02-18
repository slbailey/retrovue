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
import queue
import socket
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


from fastapi import FastAPI, Request, Response, status
from fastapi.responses import StreamingResponse
from uvicorn import Config, Server

from .clock import MasterClock
from .schedule_types import ScheduledBlock, ScheduledSegment
from .producer.base import Producer, ProducerMode, ProducerStatus, ContentSegment, ProducerState
from .channel_stream import ChannelStream, FakeTsSource, SocketTsSource, generate_ts_stream
from .config import (
    ChannelConfig,
    ChannelConfigProvider,
    InlineChannelConfigProvider,
    MOCK_CHANNEL_CONFIG,
)
from ..usecases import channel_manager_launch
from typing import Protocol, Sequence, TYPE_CHECKING
from dataclasses import dataclass, field
from datetime import datetime
import logging
import os
import threading

# =============================================================================
# PLAYOUT AUTHORITY: BlockPlan only
# =============================================================================
# The only runtime playout path is BlockPlanProducer + PlayoutSession.
# =============================================================================
PLAYOUT_AUTHORITY: str = "blockplan"

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
    feed_ahead_horizon_current_ms,
    feed_ahead_horizon_target_ms,
    feed_ahead_ready_by_miss_total,
    feed_ahead_miss_lateness_ms,
    feed_ahead_late_decision_total,
    feed_credits_at_decision,
    feed_error_backoff_total,
    feed_queue_depth_current,
    feed_credits_current,
)

from .playout_session import FeedResult


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

    def get_block_at(self, channel_id: str, utc_ms: int) -> "ScheduledBlock | None":
        """Return the fully constructed block covering the given wall-clock time.

        READ-ONLY: This is a pure query over pre-built horizon data.
        It MUST NOT trigger schedule generation, pipeline execution, or grid rebuild.
        It MAY perform idempotent day resolution (INV-P5-002) in legacy mode.

        Returns ScheduledBlock or None (planning failure).
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
# Join-In-Progress (JIP) — pure computation
# Contract: docs/contracts/runtime/INV-JOIN-IN-PROGRESS-BLOCKPLAN.md
# ----------------------------------------------------------------------


def _apply_jip_to_segments(
    segments: list[dict[str, Any]],
    jip_offset_ms: int,
    block_dur_ms: int,
) -> list[dict[str, Any]]:
    """Apply JIP offset to pre-composed segments.

    Walks segments from the start, skipping fully elapsed ones and trimming
    the partially elapsed one.  Extends (or appends) a trailing pad so the
    result sums to exactly block_dur_ms.
    """
    result: list[dict[str, Any]] = []
    remaining = jip_offset_ms
    for seg in segments:
        seg = dict(seg)
        dur = seg["segment_duration_ms"]
        if remaining >= dur:
            remaining -= dur
            continue  # fully elapsed — skip
        if remaining > 0:
            if seg.get("asset_uri"):
                seg["asset_start_offset_ms"] = (
                    seg.get("asset_start_offset_ms", 0) + remaining
                )
            seg["segment_duration_ms"] -= remaining
            remaining = 0
        result.append(seg)
    # Extend pad to fill block
    placed = sum(s["segment_duration_ms"] for s in result)
    gap = block_dur_ms - placed
    if gap > 0:
        if result and result[-1].get("segment_type") == "pad":
            result[-1]["segment_duration_ms"] += gap
        else:
            result.append({"segment_type": "pad", "segment_duration_ms": gap})
    return result


def compute_jip_position(
    playout_plan: list[dict[str, Any]],
    block_duration_ms: int,
    cycle_origin_utc_ms: int,
    now_utc_ms: int,
) -> tuple[int, int]:
    """
    Compute Join-In-Progress position within a cyclic playout plan.

    .. deprecated::
        Legacy utility from pre-INV-EXEC-NO-STRUCTURE-001 era. JIP is now
        computed within BlockPlanProducer._generate_next_block() using
        ScheduledBlock timing from the schedule service. This function
        remains only for backward-compatible tests. Do not use in new code.

    INV-JIP-BP-002: returned offset is in [0, entry_duration).
    INV-JIP-BP-003: deterministic for identical inputs.

    Args:
        playout_plan: Ordered cycle entries (each with optional duration_ms,
                      asset_path, asset_start_offset_ms).
        block_duration_ms: Default block duration when entry lacks duration_ms.
        cycle_origin_utc_ms: Wall-clock epoch (ms) anchoring cycle position 0.
        now_utc_ms: Current wall-clock time (ms since Unix epoch).

    Returns:
        (active_entry_index, block_offset_ms) where active_entry_index is the
        0-based plan entry, and block_offset_ms is in [0, entry_duration).
    """
    if not playout_plan:
        return (0, 0)

    # Resolve per-entry durations and compute cycle length
    durations = [
        entry.get("duration_ms", block_duration_ms) for entry in playout_plan
    ]
    cycle_length_ms = sum(durations)

    if cycle_length_ms <= 0:
        return (0, 0)

    # Elapsed time since origin, wrapped to one cycle.
    # Python's % always returns non-negative when divisor is positive,
    # so negative elapsed (now < origin) wraps correctly.
    elapsed_ms = (now_utc_ms - cycle_origin_utc_ms) % cycle_length_ms

    # Walk entries to find the active one
    accumulated = 0
    for i, dur in enumerate(durations):
        if accumulated + dur > elapsed_ms:
            return (i, elapsed_ms - accumulated)
        accumulated += dur

    # Should never reach here (modulo guarantees), but satisfy the type checker
    last = len(durations) - 1
    return (last, elapsed_ms - sum(durations[:last]))


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


# ----------------------------------------------------------------------
# Playlist contract types (PlaylistArchitecture.md)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class PlaylistSegment:
    """A single executable entry in a Playlist.

    Fields match PlaylistArchitecture.md § Segment Fields.
    All timestamps are timezone-aware datetimes.

    Frame-authoritative execution:
        ``frame_count`` is the total number of frames in this segment when
        played from offset 0.  It is the authoritative execution quantity —
        all CT-domain exhaustion math, preload timing, and switch-before-
        exhaustion decisions derive from it.  ``duration_seconds`` is
        retained for metadata, logging, and positional time-lookup only.
    """

    segment_id: str
    start_at: datetime
    duration_seconds: int
    type: str
    asset_id: str
    asset_path: str
    frame_count: int


@dataclass(frozen=True)
class Playlist:
    """Time-bounded, ordered list of executable segments for a channel.

    Fields match PlaylistArchitecture.md § Playlist Fields.
    All timestamps are timezone-aware datetimes.
    """

    channel_id: str
    channel_timezone: str
    window_start_at: datetime
    window_end_at: datetime
    generated_at: datetime
    source: str
    segments: Sequence[PlaylistSegment] = field(default_factory=tuple)


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
        evidence_endpoint: str = "",
    ):
        """
        Initialize the ChannelManager for a specific channel.

        Args:
            channel_id: Channel this manager controls
            clock: MasterClock for authoritative time
            schedule_service: ScheduleService for read-only access to current playout plan
            program_director: ProgramDirector for global policy/mode
            event_loop: Optional event loop for P11F-005; when set, switch issuance uses call_later instead of threading.Timer
            evidence_endpoint: host:port for evidence gRPC, empty = disabled
        """
        self.channel_id = channel_id
        self.clock = clock
        self.schedule_service = schedule_service
        self.program_director = program_director
        self._loop: asyncio.AbstractEventLoop | None = event_loop
        self._evidence_endpoint = evidence_endpoint
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

        # Mock grid configuration (when using mock grid schedule)
        self._mock_grid_block_minutes = 30  # Fixed 30-minute grid
        self._mock_grid_program_asset_path: str | None = None  # Set from daemon config
        self._mock_grid_filler_asset_path: str | None = None  # Set from daemon config
        self._mock_grid_filler_epoch: datetime | None = None  # Epoch for filler offset calculation

        # Channel lifecycle: RUNNING (on-air or idle with viewers) or STOPPED (last viewer left).
        # When STOPPED, health/reconnect logic does nothing; ProgramDirector calls stop_channel on last viewer.
        self._channel_state: str = "RUNNING"  # "RUNNING" | "STOPPED"

        # Linger: grace period before tearing down producer after last viewer leaves.
        self.LINGER_SECONDS: int = 20
        self._linger_handle: asyncio.TimerHandle | None = None
        self._linger_deadline: float | None = None

        # INV-VIEWER-LIFECYCLE: Thread-safe viewer count transitions
        self._viewer_lock: threading.Lock = threading.Lock()

        # BlockPlan only
        self._blockplan_mode: bool = True
        self._pending_fatal: BaseException | None = None

        # Channel configuration (set by daemon when creating manager)
        self.channel_config: ChannelConfig | None = None

    def stop_channel(self) -> None:
        """
        Enter STOPPED state and stop the producer. No wait for EOF or segment completion.
        Called by ProgramDirector when the last viewer disconnects (StopChannel(channel_id)).
        Explicit stop bypasses linger — teardown is immediate.
        """
        self._logger.info(
            "[teardown] stopping producer for channel %s (no wait for EOF)", self.channel_id
        )
        self._cancel_linger()
        self._channel_state = "STOPPED"
        self._teardown_reason = None
        self._pending_fatal = None
        self._stop_producer_if_idle()

    def _request_teardown(self, reason: str) -> bool:
        """
        Request permission to teardown. BlockPlan path has no boundary deferral; always permitted.
        """
        return True

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

            # Cancel linger if a viewer reconnects during the grace period.
            if old_count == 0 and self.runtime_state.viewer_count == 1:
                self._cancel_linger()

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

        Starts a linger grace period instead of immediately stopping the producer.
        If no viewer reconnects within LINGER_SECONDS, the producer is stopped.
        """
        if self.runtime_state.viewer_count != 0:
            return  # Not actually last viewer
        self._start_linger()

    def _start_linger(self) -> None:
        """Start linger grace period. Producer stays alive until timeout."""
        if self._linger_handle is not None:
            return  # already lingering
        self._logger.info(
            "[channel %s] LINGER_STARTED %ds", self.channel_id, self.LINGER_SECONDS
        )
        if self._loop is not None:
            self._linger_deadline = self._loop.time() + self.LINGER_SECONDS
            self._linger_handle = self._loop.call_later(
                self.LINGER_SECONDS, self._linger_expire
            )
        else:
            # No event loop — fall back to immediate teardown.
            self._channel_state = "STOPPED"
            self._stop_producer_if_idle()

    def _linger_expire(self) -> None:
        """Linger timer fired. Stop producer if still no viewers."""
        self._linger_handle = None
        self._linger_deadline = None
        if self.runtime_state.viewer_count == 0:
            self._logger.info(
                "[channel %s] LINGER_EXPIRED stopping producer", self.channel_id
            )
            self._channel_state = "STOPPED"
            self._stop_producer_if_idle()

    def _cancel_linger(self) -> None:
        """Cancel any pending linger timer."""
        if self._linger_handle is not None:
            self._linger_handle.cancel()
            self._linger_handle = None
            self._linger_deadline = None
            self._logger.info(
                "[channel %s] LINGER_CANCELLED viewer_reconnected", self.channel_id
            )

    def _ensure_producer_running(self) -> None:
        """Enforce 'channel goes on-air' (BlockPlan path only)."""
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

        # Get authoritative station time.
        station_time = self.clock.now_utc()

        # INV-EXEC-NO-BOUNDARY-001: No grid math here.
        # INV-EXEC-NO-STRUCTURE-001: Block timing from schedule service.
        now_utc_ms = int(station_time.timestamp() * 1000)
        current_block = self.schedule_service.get_block_at(self.channel_id, now_utc_ms)
        if not current_block:
            self.runtime_state.producer_status = "error"
            self.active_producer = None
            raise NoScheduleDataError(
                f"No block for channel {self.channel_id} at {now_utc_ms}"
            )

        # INV-EXEC-OFFSET-001: offset within block is allowed
        jip_offset_ms = now_utc_ms - current_block.start_utc_ms
        block_start_utc_ms = current_block.start_utc_ms
        self._logger.info(
            "INV-JIP-BP-BOOT: channel_id=%s station_now=%d "
            "block_start=%d block_dur=%d "
            "jip_offset=%d",
            self.channel_id, now_utc_ms,
            block_start_utc_ms, current_block.duration_ms,
            jip_offset_ms,
        )

        # Ask the Producer to start with JIP parameters.
        started_ok = self.active_producer.start(
            station_time,
            jip_offset_ms=jip_offset_ms,
        )
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

        # P12-CORE-010 INV-SESSION-CREATION-UNGATED-001: Session created for viewer.
        self._logger.info(
            "INV-SESSION-CREATION-UNGATED-001: Session created for viewer at %s",
            station_time.isoformat() if hasattr(station_time, "isoformat") else station_time,
        )

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

    def deferred_teardown_triggered(self) -> bool:
        """True when deferred teardown executed (BlockPlan path has no deferral; always False)."""
        return False

    @property
    def is_live(self) -> bool:
        """True when the channel has an active producer in running state (BlockPlan path)."""
        if self.active_producer is None:
            return False
        return self.active_producer.status == ProducerStatus.RUNNING

    def tick(self) -> None:
        """Clock-driven health/state update. BlockPlan path: no LoadPreview/SwitchToLive; producer owns execution."""
        self._check_teardown_completion()
        if self._pending_fatal is not None:
            e = self._pending_fatal
            self._pending_fatal = None
            raise e
        if self._channel_state == "STOPPED" or self.active_producer is None:
            return
        # BlockPlanProducer owns execution; tick does not drive segment boundaries

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
        # Exception: during linger grace period, the producer stays alive awaiting a reconnect.
        viewer_count = len(self.viewer_sessions)
        if viewer_count == 0 and self._linger_handle is None:
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
        """Build the Producer for the given mode. BlockPlanProducer only."""
        if not self._blockplan_mode:
            self._logger.error(
                "Channel %s: _blockplan_mode is False. Only BlockPlanProducer is permitted.",
                self.channel_id,
            )
            raise RuntimeError(
                f"Channel {self.channel_id}: Only BlockPlanProducer is permitted. "
                "Call set_blockplan_mode(True) before starting the channel."
            )
        self._logger.info(
            "Channel %s: Building BlockPlanProducer (mode=%s)",
            self.channel_id, mode,
        )
        return BlockPlanProducer(
            channel_id=self.channel_id,
            configuration={},
            channel_config=self._get_channel_config(),
            schedule_service=self.schedule_service,
            clock=self.clock,
            evidence_endpoint=self._evidence_endpoint,
        )

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
            enabled: True to use BlockPlanProducer (only valid option).
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


# =============================================================================
# BlockPlanProducer: Viewer-lifecycle-driven BlockPlan execution
# =============================================================================


class _FeedState(Enum):
    """Feed-ahead controller state machine.

    CREATED → SEEDED → RUNNING → DRAINING
    """
    CREATED = auto()   # Before seed
    SEEDED = auto()    # After seed, before first BlockCompleted
    RUNNING = auto()   # Active feeding (maintain runway >= horizon)
    DRAINING = auto()  # Session ending, no new feeds


@dataclass(frozen=True)
class _AsRunAnnotation:
    """Lightweight as-run annotation for block-level events.

    In-process only. Will be piped into the full AsRunLogger
    when that integration lands.
    """
    annotation_type: str       # e.g. "missed_ready_by"
    block_id: str
    timestamp_utc_ms: int
    metadata: dict[str, Any]   # e.g. {"lateness_ms": 3200}


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

    # Credit-based flow control constants (INV-FEED-CREDIT-*)
    DEFAULT_QUEUE_DEPTH = 3            # Default AIR queue depth (A executing, B pending, C queued)
    ERROR_BACKOFF_BASE_TICKS = 4       # ~1s at 3.75 Hz
    ERROR_BACKOFF_MAX_TICKS = 112      # ~30s at 3.75 Hz

    def __init__(
        self,
        channel_id: str,
        configuration: dict[str, Any] | None = None,
        channel_config: ChannelConfig | None = None,
        schedule_service: ScheduleService | None = None,
        clock: MasterClock | None = None,
        evidence_endpoint: str = "",
    ):
        super().__init__(channel_id, ProducerMode.NORMAL, configuration or {})
        self.channel_config = channel_config if channel_config is not None else MOCK_CHANNEL_CONFIG
        self.schedule_service = schedule_service
        self.clock = clock
        self._evidence_endpoint = evidence_endpoint

        # PlayoutSession instance (created on start, destroyed on stop)
        self._session: "PlayoutSession | None" = None

        # Thread-safety lock for all state mutations
        self._lock = threading.RLock()

        # State tracking
        self._started = False
        self._start_count = 0  # Debug: track start attempts
        self._stop_count = 0   # Debug: track stop attempts

        # INV-FEED-NO-FEED-AFTER-END: Track session termination
        self._session_ended = False
        self._session_end_reason: str | None = None

        # INV-FEED-EXACTLY-ONCE: Track fed blocks to prevent duplicates
        self._fed_block_ids: set[str] = set()

        # INV-WALLCLOCK-FENCE-002: Track active (seeded/fed, not yet completed) blocks
        self._in_flight_block_ids: set[str] = set()

        # Block generation state
        self._block_index = 0
        self._next_block_start_ms = 0
        # _cycle_origin_utc_ms removed: INV-EXEC-NO-STRUCTURE-001

        # INV-FEED-QUEUE-002: Pending block slot for QUEUE_FULL retry
        self._pending_block: "BlockPlan | None" = None

        # ---- Feed-ahead controller state ----
        self._feed_state: _FeedState = _FeedState.CREATED
        # Max end_utc_ms of all blocks delivered to AIR (seed + feed)
        self._max_delivered_end_utc_ms: int = 0
        # Configurable queue depth (default 3, minimum 2)
        cfg = configuration or {}
        self._queue_depth: int = max(2, cfg.get("queue_depth", self.DEFAULT_QUEUE_DEPTH))
        # Backward compat: set True on first BlockStarted event
        self._block_started_supported: bool = False
        # Feed-ahead horizon: maintain this many ms of runway (configurable)
        self._feed_ahead_horizon_ms: int = cfg.get(
            "feed_ahead_horizon_ms", 20_000
        )
        # Preload budget: how far before a block's start_utc_ms it must arrive
        # at AIR to guarantee preload completes on time. Based on observed
        # p95/p99 decode-open-seek latency + margin.
        self._preload_budget_ms: int = cfg.get(
            "preload_budget_ms", 10_000
        )
        # Tick throttle counter (on_paced_tick runs at 30 Hz, we evaluate at ~4 Hz)
        self._feed_tick_counter: int = 0
        # Credit-based flow control (INV-FEED-CREDIT-*)
        self._feed_credits: int = 0
        self._consecutive_feed_errors: int = 0
        self._error_backoff_remaining: int = 0
        # Deadline miss counter (in-process, also exported to Prometheus)
        self._ready_by_miss_count: int = 0
        # Late-decision counter: block noticed before start but fed after start
        self._late_decision_count: int = 0
        # Tracks when _feed_ahead first noticed the next block was due
        # (ready_by deadline reached).  Set even when credits=0 so that
        # a later feed can distinguish "decision evaluated late" from
        # "block became ready late".  Reset after each successful feed.
        self._next_block_first_due_utc_ms: int = 0
        # As-run annotations (in-process; future AsRunLogger integration)
        self._asrun_annotations: list[_AsRunAnnotation] = []

        # UDS socket for TS output
        self._socket_path: Path | None = None
        self._stream_endpoint = f"/channel/{channel_id}.ts"

        # Phase 0: UDS listener for AIR connection (Core is server, AIR is client)
        self._uds_server_socket: socket.socket | None = None
        self._reader_socket_queue: queue.Queue[socket.socket] = queue.Queue()
        self._accept_thread: threading.Thread | None = None

        # Program format for encoding (extracted from ChannelConfig.program_format).
        # Must match AIR's ProgramFormat::FromJson: frame_rate is a string (e.g. "30/1").
        pf = self.channel_config.program_format
        self._program_format = {
            "video": {
                "width": pf.video_width,
                "height": pf.video_height,
                "frame_rate": pf.frame_rate,
            },
            "audio": {
                "sample_rate": pf.audio_sample_rate,
                "channels": pf.audio_channels,
            },
        }

    def start(
        self,
        start_at_station_time: datetime,
        *,
        jip_offset_ms: int = 0,
    ) -> bool:
        """
        Start BlockPlan execution.

        Called by ChannelManager.on_first_viewer() when viewer count goes 0→1.
        Creates PlayoutSession, seeds initial 2 blocks, and begins execution.

        INV-VIEWER-LIFECYCLE-001: AIR starts exactly once per first-viewer event.
        INV-EXEC-NO-STRUCTURE-001: Block timing from schedule service via ScheduledBlock.
        INV-JIP-BP-005/006: jip_offset_ms applied only to block_a.
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

                # Phase 0: Set up UDS listener BEFORE starting AIR
                # Core is the server, AIR is the client (connects via AttachStream)
                if self._socket_path.exists():
                    self._socket_path.unlink()
                self._uds_server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self._uds_server_socket.bind(str(self._socket_path))
                self._uds_server_socket.listen(1)

                # Start accept thread (daemon so it doesn't block shutdown)
                def accept_air_connection():
                    try:
                        conn, _ = self._uds_server_socket.accept()
                        self._reader_socket_queue.put(conn)
                        self._logger.info(
                            "FIRST-ON-AIR: Channel %s: AIR connected to UDS socket",
                            self.channel_id
                        )
                    except Exception as e:
                        if not self._started:
                            return  # Expected during cleanup
                        self._logger.error(
                            "Channel %s: UDS accept error: %s",
                            self.channel_id, e
                        )

                self._accept_thread = threading.Thread(
                    target=accept_air_connection, daemon=True
                )
                self._accept_thread.start()

                # Create PlayoutSession
                self._session = PlayoutSession(
                    channel_id=self.channel_id,
                    channel_id_int=self.channel_config.channel_id_int,
                    ts_socket_path=self._socket_path,
                    program_format=self._program_format,
                    on_block_complete=self._on_block_complete,
                    on_session_end=self._on_session_end,
                    on_block_started=self._on_block_started,
                    evidence_endpoint=self._evidence_endpoint,
                )

                # Start AIR subprocess
                join_utc_ms = int(start_at_station_time.timestamp() * 1000)
                if not self._session.start(join_utc_ms=join_utc_ms):
                    raise RuntimeError("PlayoutSession.start() failed")

                # INV-EXEC-NO-STRUCTURE-001: Block timing from schedule service
                current_entry = self._resolve_plan_for_block_at(join_utc_ms)
                if not current_entry:
                    raise RuntimeError("No block data from schedule service")
                self._next_block_start_ms = current_entry.start_utc_ms
                self._in_flight_block_ids.clear()

                # Generate and seed initial 2 blocks
                # INV-JIP-BP-005/006: Only block_a carries JIP offset
                block_a = self._generate_next_block(
                    current_entry, jip_offset_ms=jip_offset_ms,
                    now_utc_ms=join_utc_ms,
                )
                self._advance_cursor(block_a)
                # INV-JIP-ADBLOCK-001: If JIP used TX log segments (previously
                # filled ads), skip re-fill to preserve ad continuity.
                if not getattr(block_a, '_txlog_filled', False):
                    block_a = self._fill_block_at_feed_time(block_a)

                next_entry = self._resolve_plan_for_block()
                if not next_entry:
                    raise RuntimeError("No next block data from schedule service")
                block_b = self._generate_next_block(next_entry)
                self._advance_cursor(block_b)
                block_b = self._fill_block_at_feed_time(block_b)

                if not self._session.seed(block_a, block_b,
                                         join_utc_ms=join_utc_ms,
                                         max_queue_depth=self._queue_depth):
                    raise RuntimeError("PlayoutSession.seed() failed")

                # INV-EXEC-NO-STRUCTURE-001: Canary proof — every session start
                # emits one unambiguous line proving timing came from schedule.
                self._logger.info(
                    "INV-EXEC-NO-STRUCTURE-001: USING_SCHEDULED_BLOCK | "
                    "block_a=%s start=%d end=%d dur=%d segs=%d jip_offset=%d | "
                    "block_b=%s start=%d end=%d dur=%d segs=%d jip_offset=0",
                    block_a.block_id, block_a.start_utc_ms, block_a.end_utc_ms,
                    block_a.end_utc_ms - block_a.start_utc_ms, len(block_a.segments),
                    jip_offset_ms,
                    block_b.block_id, block_b.start_utc_ms, block_b.end_utc_ms,
                    block_b.end_utc_ms - block_b.start_utc_ms, len(block_b.segments),
                )

                # INV-WALLCLOCK-FENCE-002: Track seeded blocks as active
                self._in_flight_block_ids.add(block_a.block_id)
                self._in_flight_block_ids.add(block_b.block_id)

                # Feed-ahead controller: enter SEEDED state.
                # After seed, 2 blocks are in AIR's queue. If queue_depth > 2,
                # we have (queue_depth - 2) credits to proactively fill extra slots.
                # The first _feed_ahead() call (on BlockStarted or tick) will fill them.
                self._feed_state = _FeedState.SEEDED
                self._max_delivered_end_utc_ms = block_b.end_utc_ms
                self._feed_credits = self._queue_depth - 2  # Extra slots beyond seed
                self._consecutive_feed_errors = 0
                self._error_backoff_remaining = 0
                self._feed_tick_counter = 0

                self._started = True
                self.status = ProducerStatus.RUNNING
                self.started_at = start_at_station_time
                self.output_url = self._stream_endpoint

                self._logger.info(
                    "Channel %s: BlockPlan execution started, seeded 2 blocks",
                    self.channel_id
                )

                # =============================================================
                # ARCHITECTURAL TELEMETRY: One-time per-session declaration
                # =============================================================
                self._logger.info(
                    "INV-PLAYOUT-AUTHORITY: Channel %s session started | "
                    "playout_path=blockplan | "
                    "encoder_scope=session | "
                    "execution_model=serial_block | "
                    "block_a_duration_ms=%d | "
                    "authority=%s",
                    self.channel_id,
                    block_a.end_utc_ms - block_a.start_utc_ms,
                    PLAYOUT_AUTHORITY,
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
        """
        Clean up PlayoutSession and resources.

        INV-CM-RESTART-SAFETY: Resets all state for clean restart.
        """
        if self._session:
            try:
                self._session.stop(reason="last_viewer_left")
            except Exception as e:
                self._logger.warning(
                    "Channel %s: Session stop error: %s",
                    self.channel_id, e
                )
            self._session = None

        # Close UDS server socket
        if self._uds_server_socket:
            try:
                self._uds_server_socket.close()
            except Exception:
                pass
            self._uds_server_socket = None

        # Clear reader socket queue (drain any remaining sockets)
        while not self._reader_socket_queue.empty():
            try:
                sock = self._reader_socket_queue.get_nowait()
                sock.close()
            except Exception:
                pass

        # Reset block generation state for next start
        self._block_index = 0
        self._next_block_start_ms = 0

        # INV-CM-RESTART-SAFETY: Reset session state flags
        self._session_ended = False
        self._session_end_reason = None
        self._fed_block_ids.clear()
        self._pending_block = None  # INV-FEED-QUEUE-002: Clear pending slot

        # Reset feed-ahead controller state
        self._feed_state = _FeedState.CREATED
        self._max_delivered_end_utc_ms = 0
        self._feed_credits = 0
        self._block_started_supported = False
        self._consecutive_feed_errors = 0
        self._error_backoff_remaining = 0
        self._feed_tick_counter = 0
        self._ready_by_miss_count = 0
        self._late_decision_count = 0
        self._next_block_first_due_utc_ms = 0
        self._asrun_annotations.clear()

    def _resolve_plan_for_block(self) -> ScheduledBlock | None:
        """INV-EXEC-NO-STRUCTURE-001: Request fully constructed block from schedule service.

        Pure read — does not trigger schedule generation.
        """
        if self.schedule_service is None:
            self._logger.error(
                "INV-BLOCKPLAN-HORIZON-MISS: No schedule_service configured for channel=%s",
                self.channel_id,
            )
            return None
        return self.schedule_service.get_block_at(self.channel_id, self._next_block_start_ms)

    def _resolve_plan_for_block_at(self, utc_ms: int) -> ScheduledBlock | None:
        """INV-EXEC-NO-STRUCTURE-001: Request block at arbitrary time."""
        if self.schedule_service is None:
            self._logger.error(
                "INV-BLOCKPLAN-HORIZON-MISS: No schedule_service configured for channel=%s",
                self.channel_id,
            )
            return None
        return self.schedule_service.get_block_at(self.channel_id, utc_ms)

    def _lookup_txlog_segments(self, block_id: str) -> list[dict[str, Any]] | None:
        """Look up filled segments from TransmissionLog for a previously-played block.

        INV-JIP-ADBLOCK-001: On re-join, use the same ad assignments that were
        originally played.  Without this, JIP into a filler segment would
        trigger fresh ad selection, causing the viewer to see a different
        commercial than what was originally scheduled.

        Returns None if no TX log entry exists (first play of this block).
        """
        try:
            from retrovue.infra.uow import session as db_session_factory
            from retrovue.domain.entities import TransmissionLog

            with db_session_factory() as db:
                entry = db.query(TransmissionLog).filter(
                    TransmissionLog.block_id == block_id,
                ).first()
                if entry is not None:
                    self._logger.info(
                        "INV-JIP-ADBLOCK-001: TX log hit for block=%s — "
                        "using previously filled segments (%d segs)",
                        block_id, len(entry.segments),
                    )
                    return list(entry.segments)
        except Exception as e:
            self._logger.warning(
                "INV-JIP-ADBLOCK-001: TX log lookup failed for block=%s: %s "
                "(falling back to fresh fill)",
                block_id, e,
            )
        return None

    def _generate_next_block(
        self,
        scheduled: ScheduledBlock,
        *,
        jip_offset_ms: int = 0,
        now_utc_ms: int = 0,
    ) -> "BlockPlan":
        """Generate BlockPlan from a ScheduledBlock provided by the schedule service.

        INV-EXEC-NO-STRUCTURE-001: Block timing comes from scheduled.start_utc_ms/end_utc_ms.
        INV-EXEC-OFFSET-001: JIP offset computed as now - block.start (offset within block).
        INV-EXEC-NO-BOUNDARY-001: No grid alignment math here.
        """
        from .playout_session import BlockPlan

        start_ms = scheduled.start_utc_ms
        end_ms = scheduled.end_utc_ms
        block_id = scheduled.block_id

        # INV-EXEC-OFFSET-001: JIP adjusts start forward (offset within block)
        if jip_offset_ms > 0 and now_utc_ms > 0:
            raw_offset = now_utc_ms - start_ms
            jip_offset_ms = max(0, min(raw_offset, scheduled.duration_ms))
            start_ms = start_ms + jip_offset_ms

        effective_dur = end_ms - start_ms

        # INV-JIP-ADBLOCK-001: On re-join, prefer previously-filled segments
        # from TransmissionLog so JIP resumes into the same ads that were
        # originally playing (not fresh random assignments).
        txlog_segments = None
        if jip_offset_ms > 0:
            txlog_segments = self._lookup_txlog_segments(block_id)

        if txlog_segments is not None:
            # Use TX log segments (already filled with real ad URIs)
            plan_segments = txlog_segments
        else:
            # Convert ScheduledSegment tuple to segment dicts for BlockPlan/AIR
            plan_segments: list[dict[str, Any]] = []
            for i, seg in enumerate(scheduled.segments):
                d = {
                    "segment_index": i,
                    "segment_type": seg.segment_type,
                    "asset_uri": seg.asset_uri,
                    "asset_start_offset_ms": seg.asset_start_offset_ms,
                    "segment_duration_ms": seg.segment_duration_ms,
                }
                # Propagate transition fields (INV-TRANSITION-001)
                if seg.transition_in != "TRANSITION_NONE":
                    d["transition_in"] = seg.transition_in
                    d["transition_in_duration_ms"] = seg.transition_in_duration_ms
                if seg.transition_out != "TRANSITION_NONE":
                    d["transition_out"] = seg.transition_out
                    d["transition_out_duration_ms"] = seg.transition_out_duration_ms
                plan_segments.append(d)

        # Log transition fields for debugging (INV-TRANSITION-001)
        import logging as _logging
        _tlog = _logging.getLogger(__name__)
        for d in plan_segments:
            t_in = d.get("transition_in", "TRANSITION_NONE")
            t_out = d.get("transition_out", "TRANSITION_NONE")
            if t_in != "TRANSITION_NONE" or t_out != "TRANSITION_NONE":
                _tlog.info(
                    "TRANSITION_TAG block=%s seg=%d type=%s t_in=%s/%dms t_out=%s/%dms",
                    block_id, d["segment_index"], d["segment_type"],
                    t_in, d.get("transition_in_duration_ms", 0),
                    t_out, d.get("transition_out_duration_ms", 0),
                )

        if jip_offset_ms > 0:
            plan_segments = _apply_jip_to_segments(plan_segments, jip_offset_ms, effective_dur)
            for i, seg in enumerate(plan_segments):
                seg["segment_index"] = i

        block = BlockPlan(
            block_id=block_id,
            channel_id=self.channel_config.channel_id_int,
            start_utc_ms=start_ms,
            end_utc_ms=end_ms,
            segments=plan_segments,
        )

        # INV-JIP-ADBLOCK-001: Mark block so caller can skip redundant ad fill
        block._txlog_filled = txlog_segments is not None

        # INV-EXEC-NO-STRUCTURE-001: Immutability enforcement
        # Non-JIP: outbound (start, end) must equal scheduled (start, end)
        # JIP: outbound start == scheduled_start + jip_offset, outbound end == scheduled_end
        assert block.end_utc_ms == scheduled.end_utc_ms, (
            f"INV-EXEC-NO-STRUCTURE-001 VIOLATION: outbound end_utc_ms={block.end_utc_ms} "
            f"!= scheduled end_utc_ms={scheduled.end_utc_ms}"
        )
        if jip_offset_ms > 0:
            assert block.start_utc_ms == scheduled.start_utc_ms + jip_offset_ms, (
                f"INV-EXEC-NO-STRUCTURE-001 VIOLATION: outbound start_utc_ms={block.start_utc_ms} "
                f"!= scheduled start + jip ({scheduled.start_utc_ms + jip_offset_ms})"
            )
        else:
            assert block.start_utc_ms == scheduled.start_utc_ms, (
                f"INV-EXEC-NO-STRUCTURE-001 VIOLATION: outbound start_utc_ms={block.start_utc_ms} "
                f"!= scheduled start_utc_ms={scheduled.start_utc_ms}"
            )

        # INV-EXEC-NO-STRUCTURE-001 proof
        self._logger.info(
            "INV-EXEC-NO-STRUCTURE-001: block=%s dur=%d start=%d end=%d "
            "segs=%d jip_offset=%d (timing from schedule service)",
            block.block_id, effective_dur, start_ms, end_ms,
            len(plan_segments), jip_offset_ms,
        )

        return block

    def _advance_cursor(self, block: "BlockPlan"):
        """
        Advance block generation cursor after a successful feed.

        INV-FEED-QUEUE-001: Cursor advances ONLY after feed() returns True.
        """
        self._block_index += 1
        self._next_block_start_ms = block.end_utc_ms

    def _persist_transmission_log(self, block: "BlockPlan", db_session) -> None:
        """Persist a filled block to the transmission_log table.

        INV-TXLOG-WRITE-BEFORE-FEED-001: Called before session.feed(block).
        Gracefully degrades on DB error -- playout is never interrupted.
        """
        try:
            from retrovue.domain.entities import TransmissionLog
            from datetime import date, timezone

            def _derive_title_simple(seg_type: str, asset_uri: str) -> str:
                if seg_type == "pad" or not asset_uri:
                    return "BLACK"
                name = asset_uri.rsplit("/", 1)[-1] if "/" in asset_uri else asset_uri
                if "." in name:
                    name = name.rsplit(".", 1)[0]
                for prefix in ("Interstitial - Commercial - ", "Interstitial - ", "Commercial - "):
                    if name.startswith(prefix):
                        name = name[len(prefix):]
                        break
                return name

            segments_data = []
            for seg in block.segments:
                seg_type = seg.get("segment_type", "content") if isinstance(seg, dict) else getattr(seg, "segment_type", "content")
                uri = seg.get("asset_uri", "") if isinstance(seg, dict) else getattr(seg, "asset_uri", "")
                duration = seg.get("segment_duration_ms", 0) if isinstance(seg, dict) else getattr(seg, "segment_duration_ms", 0)
                offset = seg.get("asset_start_offset_ms", 0) if isinstance(seg, dict) else getattr(seg, "asset_start_offset_ms", 0)
                idx = seg.get("segment_index", len(segments_data)) if isinstance(seg, dict) else getattr(seg, "segment_index", len(segments_data))
                segments_data.append({
                    "segment_index": idx,
                    "segment_type": seg_type,
                    "asset_uri": uri or "",
                    "asset_start_offset_ms": offset,
                    "segment_duration_ms": duration,
                    "title": _derive_title_simple(seg_type, uri or ""),
                })

            import datetime as _dt
            broadcast_day = _dt.datetime.fromtimestamp(
                block.start_utc_ms / 1000.0, tz=_dt.timezone.utc
            ).date()

            row = TransmissionLog(
                block_id=block.block_id,
                channel_slug=str(self.channel_id),
                broadcast_day=broadcast_day,
                start_utc_ms=block.start_utc_ms,
                end_utc_ms=block.end_utc_ms,
                segments=segments_data,
            )
            db_session.merge(row)
            db_session.flush()
            self._logger.info(
                "TXLOG: Persisted transmission_log block=%s segs=%d",
                block.block_id, len(segments_data),
            )
        except Exception as e:
            self._logger.warning(
                "TXLOG: Failed to persist transmission_log for block=%s: %s",
                block.block_id, e,
            )

    def _try_feed_block(self, block: "BlockPlan") -> FeedResult:
        """
        Attempt to feed a block to AIR.

        INV-TRAFFIC-LATE-BIND-001: Traffic fill happens here, ~30 min before air.
        INV-FEED-QUEUE-001: Cursor advances only on ACCEPTED.
        INV-FEED-QUEUE-002: Rejected block stored in _pending_block.
        INV-FEED-CREDIT-001: Credits decremented on ACCEPTED, zeroed on QUEUE_FULL.
        """
        if not self._session:
            return FeedResult.ERROR

        # INV-TRAFFIC-LATE-BIND-001: Fill empty filler placeholders with real
        # interstitials at feed time (~30 min before air).
        # Open a fresh DB session; do NOT hold it across feeds.
        block = self._fill_block_at_feed_time(block)

        result = self._session.feed(block)

        if result == FeedResult.ACCEPTED:
            self._advance_cursor(block)
            self._pending_block = None
            self._feed_credits = max(0, self._feed_credits - 1)
            # INV-WALLCLOCK-FENCE-002: Track fed block as active
            self._in_flight_block_ids.add(block.block_id)
            # Success clears error state
            self._consecutive_feed_errors = 0
            self._error_backoff_remaining = 0
            return FeedResult.ACCEPTED

        elif result == FeedResult.QUEUE_FULL:
            self._pending_block = block
            self._feed_credits = 0  # Authoritative correction
            self._logger.warning(
                "INV-FEED-QUEUE-002: Block %s pending (QUEUE_FULL), credits=0",
                block.block_id,
            )
            return FeedResult.QUEUE_FULL

        else:  # ERROR
            self._pending_block = block
            self._consecutive_feed_errors += 1
            self._error_backoff_remaining = min(
                self.ERROR_BACKOFF_BASE_TICKS
                * (2 ** (self._consecutive_feed_errors - 1)),
                self.ERROR_BACKOFF_MAX_TICKS,
            )
            if feed_error_backoff_total is not None:
                feed_error_backoff_total.labels(
                    channel_id=self.channel_id
                ).inc()
            self._logger.error(
                "FEED-ERROR: Block %s pending, errors=%d backoff=%d ticks",
                block.block_id,
                self._consecutive_feed_errors,
                self._error_backoff_remaining,
            )
            return FeedResult.ERROR

    def _fill_block_at_feed_time(self, block: "BlockPlan") -> "BlockPlan":
        """Fill empty filler placeholders with real interstitials at feed time.

        INV-TRAFFIC-LATE-BIND-001: Called from _try_feed_block(), ~30 min before air.
        Opens and closes its own DB session. On any error, falls back to the
        unmodified block (empty placeholders will become black via AIR).

        Also persists the filled block to transmission_log and writes
        traffic_play_log entries for each commercial.
        """
        try:
            from retrovue.runtime.traffic_manager import fill_ad_blocks
            from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment
            from retrovue.infra.uow import session as db_session_factory

            # Get filler config from channel_config.schedule_config
            filler_uri = ""
            filler_duration_ms = 3_650_000
            if self.channel_config:
                sc = getattr(self.channel_config, "schedule_config", {}) or {}
                filler_uri = sc.get("filler_path", "/opt/retrovue/assets/filler.mp4")
                filler_duration_ms = sc.get("filler_duration_ms", 3_650_000)

            # Convert BlockPlan segments to ScheduledBlock for fill_ad_blocks
            # (fill_ad_blocks expects ScheduledBlock, not BlockPlan)
            sched_segments = []
            for seg in block.segments:
                seg_type = seg.get("segment_type", "content") if isinstance(seg, dict) else getattr(seg, "segment_type", "content")
                uri = seg.get("asset_uri", "") if isinstance(seg, dict) else getattr(seg, "asset_uri", "")
                duration = seg.get("segment_duration_ms", 0) if isinstance(seg, dict) else getattr(seg, "segment_duration_ms", 0)
                offset = seg.get("asset_start_offset_ms", 0) if isinstance(seg, dict) else getattr(seg, "asset_start_offset_ms", 0)
                sched_segments.append(ScheduledSegment(
                    segment_type=seg_type,
                    asset_uri=uri or "",
                    asset_start_offset_ms=offset,
                    segment_duration_ms=duration,
                ))

            sched_block = ScheduledBlock(
                block_id=block.block_id,
                start_utc_ms=block.start_utc_ms,
                end_utc_ms=block.end_utc_ms,
                segments=tuple(sched_segments),
            )

            with db_session_factory() as db:
                # Create asset library for this channel
                asset_lib = None
                if filler_uri:  # Only try if we have a filler configured
                    try:
                        from retrovue.catalog.db_asset_library import DatabaseAssetLibrary
                        asset_lib = DatabaseAssetLibrary(db, channel_slug=str(self.channel_id))
                    except Exception as e:
                        self._logger.warning("TRAFFIC: Could not create DatabaseAssetLibrary: %s", e)

                # Fill empty filler placeholders
                if filler_uri:
                    filled_sched = fill_ad_blocks(
                        sched_block,
                        filler_uri=filler_uri,
                        filler_duration_ms=filler_duration_ms,
                        asset_library=asset_lib,
                    )
                else:
                    filled_sched = sched_block
                    self._logger.debug(
                        "TRAFFIC: No filler_uri configured for channel=%s, skipping fill",
                        self.channel_id,
                    )

                # Build a new BlockPlan from the filled ScheduledBlock
                filled_segments = []
                for i, seg in enumerate(filled_sched.segments):
                    d = {
                        "segment_index": i,
                        "segment_type": seg.segment_type,
                        "asset_uri": seg.asset_uri,
                        "asset_start_offset_ms": seg.asset_start_offset_ms,
                        "segment_duration_ms": seg.segment_duration_ms,
                    }
                    filled_segments.append(d)

                from retrovue.runtime.playout_session import BlockPlan as _BlockPlan
                filled_block = _BlockPlan(
                    block_id=block.block_id,
                    channel_id=block.channel_id,
                    start_utc_ms=block.start_utc_ms,
                    end_utc_ms=block.end_utc_ms,
                    segments=filled_segments,
                )

                # INV-TXLOG-WRITE-BEFORE-FEED-001: persist before feed
                self._persist_transmission_log(filled_block, db)
                db.commit()

                # Write traffic_play_log entries separately (non-critical)
                try:
                    self._write_traffic_play_log(filled_block, db)
                    db.commit()
                except Exception as e:
                    db.rollback()
                    self._logger.warning(
                        "TRAFFIC: traffic_play_log write failed (non-critical): %s", e
                    )

            self._logger.info(
                "TRAFFIC: Filled block=%s at feed time segs=%d",
                block.block_id, len(filled_segments),
            )
            return filled_block

        except Exception as e:
            self._logger.warning(
                "TRAFFIC: Feed-time fill failed for block=%s: %s -- using unfilled block",
                block.block_id, e,
            )
            return block

    def _write_traffic_play_log(self, block: "BlockPlan", db_session) -> None:
        """Write traffic_play_log entries for each commercial/promo in the block.

        Called from _fill_block_at_feed_time after fill_ad_blocks succeeds.
        Gracefully degrades on error.
        """
        try:
            from retrovue.domain.entities import TrafficPlayLog, Asset
            import datetime as _dt
            import uuid as _uuid

            interstitial_types = {"commercial", "promo", "ident", "psa", "filler", "ad"}
            played_at = _dt.datetime.now(_dt.timezone.utc)

            for seg in block.segments:
                seg_type = seg.get("segment_type", "") if isinstance(seg, dict) else getattr(seg, "segment_type", "")
                if seg_type not in interstitial_types:
                    continue
                uri = seg.get("asset_uri", "") if isinstance(seg, dict) else getattr(seg, "asset_uri", "")
                if not uri:
                    continue
                duration = seg.get("segment_duration_ms", 0) if isinstance(seg, dict) else getattr(seg, "segment_duration_ms", 0)
                idx = seg.get("segment_index", 0) if isinstance(seg, dict) else getattr(seg, "segment_index", 0)

                # Look up asset UUID from URI
                asset = db_session.query(Asset).filter(
                    Asset.canonical_uri == uri
                ).first()
                if asset is None:
                    self._logger.debug("TRAFFIC: No asset found for URI=%s, skipping play log", uri)
                    continue

                row = TrafficPlayLog(
                    channel_slug=str(self.channel_id),
                    asset_uuid=asset.uuid,
                    asset_uri=uri,
                    asset_type=seg_type,
                    played_at=played_at,
                    break_index=idx,
                    block_id=block.block_id,
                    duration_ms=duration,
                )
                db_session.add(row)

        except Exception as e:
            self._logger.warning(
                "TRAFFIC: Failed to write traffic_play_log for block=%s: %s",
                block.block_id, e,
            )

    def _feed_ahead(self) -> None:
        """Deadline-driven feed-ahead: feed blocks whose ready_by deadline
        has arrived or whose absence would let runway drop below horizon.

        For each candidate block X (pending or next-to-generate):
          ready_by_utc_ms = X.start_utc_ms - preload_budget_ms

        Feed when: now_utc_ms >= ready_by_utc_ms  OR  runway < horizon.

        Must be called under self._lock.

        Invariants preserved:
        - INV-FEED-QUEUE-003: Retry _pending_block before generating new
        - INV-FEED-QUEUE-001: Cursor advances only on successful feed
        - INV-FEED-NO-FEED-AFTER-END: Gated by _feed_state

        FLOW CONTROL (credit-based, INV-FEED-CREDIT-*):
          - Credits = available queue slots in AIR, tracked locally.
          - If credits <= 0, return immediately (no gRPC call).
          - BlockCompleted increments credits; ACCEPTED decrements.
          - QUEUE_FULL authoritatively resets credits to 0.
          - gRPC errors trigger escalating backoff; credits unchanged.

        MISS POLICY (deterministic, passive):
        When a block is fed after its start_utc_ms (now > start_utc_ms):
          1. Do NOT reorder blocks — sequence is sacred (INV-FEED-SEQUENCE).
          2. Do NOT swap to emergency filler — no reactive substitution.
          3. Continue feeding ahead as normal — loop proceeds unchanged.
          4. Allow AIR to output black+silence (PADDED_GAP) — Core does not fight it.
          5. Record as-run annotation: missed_ready_by with block_id and lateness_ms.
        Core's only response to a miss is observability (log, metric, annotation).
        No control flow changes occur on miss.

        MISS vs LATE DECISION (INV-FEED-MISS-ACCURACY):
        A block fed after start_utc_ms is classified as:
          - MISS_READY_BY (WARNING): feed-ahead first noticed the block AFTER
            start_utc_ms.  The block was genuinely not prepared in time.
          - LATE_DECISION (INFO): feed-ahead noticed the block BEFORE start_utc_ms
            (in the [ready_by, start) window) but could not feed due to no credits.
            The block was prepared on time; seam-correct transitions cover this.
        _next_block_first_due_utc_ms tracks when the deadline was first noticed,
        even when credits=0.  This separates evaluation timing from readiness.
        """
        if self._feed_state != _FeedState.RUNNING:
            return
        if self._session_ended or not self._started or not self._session:
            return

        # Runway controller telemetry
        if feed_credits_current is not None:
            feed_credits_current.labels(channel_id=self.channel_id).set(self._feed_credits)
        if feed_queue_depth_current is not None:
            feed_queue_depth_current.labels(channel_id=self.channel_id).set(
                self._queue_depth - self._feed_credits
            )

        now_utc_ms = int(time.time() * 1000)

        # Pre-evaluate next block deadline BEFORE the credit gate.
        # This records when _feed_ahead first noticed the upcoming block
        # was due, even when credits=0.  Enables accurate miss vs
        # late-decision classification when credits arrive later.
        if self._next_block_first_due_utc_ms == 0:
            next_start = (
                self._pending_block.start_utc_ms
                if self._pending_block is not None
                else self._next_block_start_ms
            )
            if next_start > 0:
                next_ready_by = next_start - self._preload_budget_ms
                if now_utc_ms >= next_ready_by:
                    self._next_block_first_due_utc_ms = now_utc_ms

        # Credit gate: no slots available → return immediately.
        # Eliminates QUEUE_FULL thrash on the tick-driven path.
        if feed_credits_at_decision is not None:
            feed_credits_at_decision.labels(
                channel_id=self.channel_id
            ).observe(self._feed_credits)
        if self._feed_credits <= 0:
            return

        for _ in range(min(self._feed_credits, self._queue_depth)):
            # INV-FEED-QUEUE-003: Retry pending before generating new
            if self._pending_block is not None:
                block = self._pending_block
            else:
                scheduled = self._resolve_plan_for_block()
                if scheduled is None:
                    self._logger.warning(
                        "INV-BLOCKPLAN-HORIZON-MISS: No block at %d for channel=%s — "
                        "planning gap. AIR will pad (PADDED_GAP). Retry next tick.",
                        self._next_block_start_ms, self.channel_id,
                    )
                    return  # Skip tick; retry next tick
                block = self._generate_next_block(scheduled)

            # Compute per-block deadline
            ready_by_utc_ms = block.start_utc_ms - self._preload_budget_ms
            runway_ms = self._compute_runway_ms()
            deadline_due = now_utc_ms >= ready_by_utc_ms
            runway_low = runway_ms < self._feed_ahead_horizon_ms
            # Proactive fill-to-depth: always feed if we have credits
            fill_to_depth = self._feed_credits > 0

            if not deadline_due and not runway_low and not fill_to_depth:
                # No trigger met — nothing to feed yet
                self._logger.debug(
                    "FEED_AHEAD_DECISION now=%d block=%s start=%d "
                    "ready_by=%d reason=skip_not_due runway=%dms",
                    now_utc_ms, block.block_id, block.start_utc_ms,
                    ready_by_utc_ms, runway_ms,
                )
                return

            # Determine reason for feeding
            if deadline_due and runway_low:
                reason = "deadline+runway"
            elif deadline_due:
                reason = "deadline"
            elif runway_low:
                reason = "runway"
            else:
                reason = "fill_to_depth"

            # MISS POLICY: detect and record, but do NOT alter control flow.
            # AIR handles the gap via PADDED_GAP (black+silence).
            #
            # A block is a TRUE miss only if the feed-ahead logic first
            # noticed it AFTER start_utc_ms.  If the logic noticed the
            # deadline earlier (in the [ready_by, start) window) but
            # could not feed due to credits/queue, that is a LATE
            # DECISION — the block was prepared on time but delivered
            # late.  Seam-correct transitions cover this case.
            first_due_utc_ms = (
                self._next_block_first_due_utc_ms or now_utc_ms
            )
            is_miss = first_due_utc_ms > block.start_utc_ms
            is_late_decision = (
                not is_miss and now_utc_ms > block.start_utc_ms
            )

            if is_miss:
                lateness_ms = now_utc_ms - block.start_utc_ms
                self._ready_by_miss_count += 1
                self._record_miss_annotation(block.block_id, lateness_ms)
                if feed_ahead_ready_by_miss_total is not None:
                    feed_ahead_ready_by_miss_total.labels(
                        channel_id=self.channel_id
                    ).inc()
                if feed_ahead_miss_lateness_ms is not None:
                    feed_ahead_miss_lateness_ms.labels(
                        channel_id=self.channel_id
                    ).observe(lateness_ms)
                self._logger.warning(
                    "MISS_READY_BY channel=%s block=%s lateness_ms=%d "
                    "ready_by=%d start=%d now=%d first_due=%d",
                    self.channel_id, block.block_id, lateness_ms,
                    ready_by_utc_ms, block.start_utc_ms, now_utc_ms,
                    first_due_utc_ms,
                )
            elif is_late_decision:
                decision_lag_ms = now_utc_ms - block.start_utc_ms
                self._late_decision_count += 1
                if feed_ahead_late_decision_total is not None:
                    feed_ahead_late_decision_total.labels(
                        channel_id=self.channel_id
                    ).inc()
                self._logger.info(
                    "LATE_DECISION channel=%s block=%s decision_lag_ms=%d "
                    "ready_by=%d start=%d now=%d first_due=%d",
                    self.channel_id, block.block_id, decision_lag_ms,
                    ready_by_utc_ms, block.start_utc_ms, now_utc_ms,
                    first_due_utc_ms,
                )

            self._logger.info(
                "FEED_AHEAD_DECISION now=%d block=%s start=%d "
                "ready_by=%d reason=%s runway=%dms miss=%s late_decision=%s",
                now_utc_ms, block.block_id, block.start_utc_ms,
                ready_by_utc_ms, reason, runway_ms, is_miss, is_late_decision,
            )

            result = self._try_feed_block(block)
            if result != FeedResult.ACCEPTED:
                self._logger.info(
                    "FEED-AHEAD: %s for %s, credits=%d",
                    result.value, block.block_id, self._feed_credits,
                )
                return

            # Block accepted — reset first-due tracker for next block.
            self._next_block_first_due_utc_ms = 0

            # Update runway tracker
            self._max_delivered_end_utc_ms = max(
                self._max_delivered_end_utc_ms, block.end_utc_ms
            )

            # Emit metrics
            new_runway_ms = self._compute_runway_ms()
            lead_time_ms = max(0, block.start_utc_ms - now_utc_ms)
            if feed_ahead_horizon_current_ms is not None:
                feed_ahead_horizon_current_ms.labels(
                    channel_id=self.channel_id
                ).observe(new_runway_ms)
            if feed_ahead_horizon_target_ms is not None:
                feed_ahead_horizon_target_ms.labels(
                    channel_id=self.channel_id
                ).observe(lead_time_ms)

            # Credit re-check after successful feed
            if self._feed_credits <= 0:
                return

    def _compute_runway_ms(self) -> int:
        """How many ms of delivered content remain ahead of current UTC."""
        if self._max_delivered_end_utc_ms == 0:
            return 0
        current_utc_ms = int(time.time() * 1000)
        return max(0, self._max_delivered_end_utc_ms - current_utc_ms)

    def _compute_ready_by_ms(self, block: "BlockPlan") -> int:
        """Compute the ready_by deadline for a block.

        ready_by_utc_ms = start_utc_ms - preload_budget_ms
        """
        return block.start_utc_ms - self._preload_budget_ms

    def _record_miss_annotation(self, block_id: str, lateness_ms: int) -> None:
        """Record a missed_ready_by as-run annotation.

        Called under self._lock.
        """
        annotation = _AsRunAnnotation(
            annotation_type="missed_ready_by",
            block_id=block_id,
            timestamp_utc_ms=int(time.time() * 1000),
            metadata={"lateness_ms": lateness_ms},
        )
        self._asrun_annotations.append(annotation)

    def get_asrun_annotations(self) -> list[_AsRunAnnotation]:
        """Return a copy of the as-run annotations list.

        Thread-safe. For testing and future AsRunLogger integration.
        """
        with self._lock:
            return list(self._asrun_annotations)

    def _on_block_started(self, block_id: str):
        """
        Callback when a block starts (popped from AIR queue).

        BlockStarted = queue slot consumed → credit += 1.
        This is the preferred credit signal; BlockCompleted is fallback.
        Also triggers SEEDED→RUNNING transition (earlier than BlockCompleted).
        """
        with self._lock:
            if self._session_ended or not self._started:
                return

            # Mark that AIR supports BlockStarted events
            self._block_started_supported = True

            # BlockStarted = queue slot consumed → credit += 1
            self._feed_credits = min(self._feed_credits + 1, self._queue_depth)

            # State transition: SEEDED → RUNNING on first BlockStarted
            if self._feed_state == _FeedState.SEEDED:
                self._feed_state = _FeedState.RUNNING
                self._logger.info(
                    "FEED-AHEAD: SEEDED->RUNNING on BlockStarted(%s) "
                    "runway=%dms",
                    block_id, self._compute_runway_ms(),
                )

            self._feed_ahead()

    def _on_block_complete(self, block_id: str):
        """
        Callback when a block completes - feed next block.

        INV-FEED-EXACTLY-ONCE: Only feeds once per BlockCompleted event.
        INV-FEED-NO-FEED-AFTER-END: Does not feed after SessionEnded.
        INV-FEED-NO-MID-BLOCK: Only called by event callback (never by timer/poll).
        """
        with self._lock:
            # INV-FEED-NO-FEED-AFTER-END: Guard against feeding after session end
            if self._session_ended:
                self._logger.debug(
                    "INV-FEED-NO-FEED-AFTER-END: Channel %s: Ignoring block_complete "
                    "after session ended (reason=%s)",
                    self.channel_id, self._session_end_reason
                )
                return

            if not self._started or not self._session:
                return

            # INV-FEED-EXACTLY-ONCE: Prevent duplicate feeds for same block
            if block_id in self._fed_block_ids:
                self._logger.warning(
                    "INV-FEED-EXACTLY-ONCE: Channel %s: Duplicate completion for %s, ignoring",
                    self.channel_id, block_id
                )
                return

            # INV-WALLCLOCK-FENCE-002: Only active blocks may complete
            if block_id not in self._in_flight_block_ids:
                self._logger.warning(
                    "INV-WALLCLOCK-FENCE-002: Channel %s: BlockCompleted for "
                    "unknown/inactive block %s, discarding",
                    self.channel_id, block_id
                )
                return

            self._fed_block_ids.add(block_id)
            self._in_flight_block_ids.discard(block_id)

            self._logger.debug(
                "Channel %s: Block %s completed, feeding next",
                self.channel_id, block_id
            )

            # State transition: SEEDED → RUNNING on first BlockCompleted
            # (fallback if BlockStarted wasn't received first)
            if self._feed_state == _FeedState.SEEDED:
                self._feed_state = _FeedState.RUNNING
                self._logger.info(
                    "FEED-AHEAD: SEEDED->RUNNING on BlockCompleted(%s) "
                    "runway=%dms horizon=%dms",
                    block_id,
                    self._compute_runway_ms(),
                    self._feed_ahead_horizon_ms,
                )

            # Backward compat: if AIR doesn't emit BlockStarted, credit on BlockCompleted
            if not self._block_started_supported:
                self._feed_credits = min(self._feed_credits + 1, self._queue_depth)

            # AIR is responsive: clear error state
            self._consecutive_feed_errors = 0
            self._error_backoff_remaining = 0

            # Proactive feed-ahead (replaces direct _try_feed_block)
            self._feed_ahead()

    def _on_session_end(self, reason: str):
        """
        Callback when session ends.

        INV-FEED-NO-FEED-AFTER-END: Sets flag to prevent further feeding.
        INV-FEED-SESSION-END-REASON: Logs the termination reason.
        """
        with self._lock:
            self._session_ended = True
            self._session_end_reason = reason
            self._feed_state = _FeedState.DRAINING

        self._logger.info(
            "INV-FEED-SESSION-END-REASON: Channel %s: Session ended: %s",
            self.channel_id, reason
        )

        # Handle specific termination reasons
        if reason == "error":
            self._logger.error(
                "Channel %s: Session ended with error, halting feeding",
                self.channel_id
            )
        elif reason == "lookahead_exhausted":
            self._logger.info(
                "Channel %s: Lookahead exhausted - no more blocks in schedule",
                self.channel_id
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

    # Throttle: evaluate feed-ahead at ~4 Hz (every 8th tick of 30 Hz pace)
    FEED_AHEAD_TICK_DIVISOR = 8

    def on_paced_tick(self, t_now: float, dt: float) -> None:
        """
        Advance producer state using pacing ticks.

        In BlockPlan mode, most work happens asynchronously in AIR.
        Tick handles teardown advancement and throttled feed-ahead evaluation.
        """
        # Handle graceful teardown if in progress
        if self._advance_teardown(dt):
            return

        # Throttled feed-ahead evaluation
        self._feed_tick_counter += 1
        if self._feed_tick_counter % self.FEED_AHEAD_TICK_DIVISOR != 0:
            return

        with self._lock:
            if self._error_backoff_remaining > 0:
                self._error_backoff_remaining -= 1
                return

            if self._feed_state == _FeedState.RUNNING:
                self._feed_ahead()

    def get_socket_path(self) -> Path | None:
        """Return the UDS socket path for TS output."""
        with self._lock:
            return self._socket_path

    @property
    def socket_path(self) -> Path | None:
        """UDS socket path (for _get_or_create_fanout_buffer compatibility)."""
        return self._socket_path

    @property
    def reader_socket_queue(self) -> queue.Queue[socket.socket]:
        """Queue containing accepted AIR socket (for _get_or_create_fanout_buffer)."""
        return self._reader_socket_queue

