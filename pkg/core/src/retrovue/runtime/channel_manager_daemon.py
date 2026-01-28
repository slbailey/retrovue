"""
RetroVue Core runtime.

System-wide runtime that manages ALL channels using the runtime ChannelManager.
Runs an HTTP server and bridges HTTP requests to ChannelManager instances.

This is an internal implementation detail. The public-facing product is RetroVue.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import StreamingResponse
from uvicorn import Config, Server

from .clock import MasterClock
from .producer.base import Producer, ProducerMode, ProducerStatus, ContentSegment, ProducerState
from .channel_stream import ChannelStream, FakeTsSource, SocketTsSource, generate_ts_stream
from ..usecases import channel_manager_launch
from typing import Protocol, TYPE_CHECKING
from dataclasses import dataclass
from datetime import datetime
import logging
import os

if TYPE_CHECKING:
    from retrovue.runtime.metrics import ChannelMetricsSample, MetricsPublisher


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
    ):
        """
        Initialize the ChannelManager for a specific channel.

        Args:
            channel_id: Channel this manager controls
            clock: MasterClock for authoritative time
            schedule_service: ScheduleService for read-only access to current playout plan
            program_director: ProgramDirector for global policy/mode
        """
        self.channel_id = channel_id
        self.clock = clock
        self.schedule_service = schedule_service
        self.program_director = program_director

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

        # Clock-driven segment switching (schedule advances because time advanced, not EOF).
        self._segment_end_time_utc: datetime | None = None  # When current segment ends (from schedule)
        self._preload_lead_seconds: float = 3.0  # Load next segment this many seconds before segment end
        self._preload_done_for_next: bool = False  # Have we already LoadPreview'd the segment that starts at _segment_end_time_utc?
        self._last_switch_at_segment_end_utc: datetime | None = None  # Guard: fire switch_to_live() once per segment

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
        self._preload_done_for_next = False
        self._last_switch_at_segment_end_utc = None
        self._stop_producer_if_idle()

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
        """Called when a viewer starts watching this channel."""
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
        if old_count == 0 and self.runtime_state.viewer_count == 1:
            self.on_first_viewer()

        # If we have an active producer, surface its endpoint for new viewers.
        if self.active_producer:
            self.runtime_state.stream_endpoint = self.active_producer.get_stream_endpoint()

    def viewer_leave(self, session_id: str) -> None:
        """Called when a viewer stops watching."""
        if session_id in self.viewer_sessions:
            del self.viewer_sessions[session_id]

        old_count = self.runtime_state.viewer_count
        self.runtime_state.viewer_count = len(self.viewer_sessions)

        # Fanout rule: last viewer stops Producer.
        if old_count == 1 and self.runtime_state.viewer_count == 0:
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

        # Clock-driven switching: segment end time from schedule (not media). Time alone advances the schedule.
        duration_s = self._segment_duration_seconds(playout_plan[0])
        if duration_s > 0:
            self._segment_end_time_utc = station_time + timedelta(seconds=duration_s)
            self._preload_done_for_next = False
        else:
            self._segment_end_time_utc = None
            self._preload_done_for_next = False

    def _segment_duration_seconds(self, segment: dict[str, Any]) -> float:
        """Duration of segment from schedule (seconds). Uses duration_seconds or metadata.segment_seconds."""
        v = segment.get("duration_seconds")
        if v is not None:
            return float(v)
        v = segment.get("metadata", {}).get("segment_seconds")
        return float(v) if v is not None else 0.0

    def tick(self) -> None:
        """
        Clock-driven segment advancement. Called periodically (e.g. from daemon health loop).

        When now >= segment_end_time, calls SwitchToLive() on Air and advances to the next
        segment. Preloads next asset before segment end (segment_end_time - preload_lead).
        Does NOT wait for EOF or inspect decode/presentation state; time alone advances the schedule.
        """
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

        # Preload: before segment end, load next asset into preview (time-based, not EOF).
        preload_at = segment_end - timedelta(seconds=self._preload_lead_seconds)
        if not self._preload_done_for_next and now >= preload_at:
            next_plan = self.schedule_service.get_playout_plan_now(self.channel_id, segment_end)
            if next_plan:
                next_seg = next_plan[0]
                asset_path = next_seg.get("asset_path")
                if asset_path:
                    start_pts_ms = int(next_seg.get("start_pts", 0))
                    ok = producer.load_preview(asset_path, start_offset_ms=start_pts_ms, hard_stop_time_ms=0)
                    if ok:
                        self._preload_done_for_next = True
                        self._logger.info(
                            "Channel %s clock-driven preload: LoadPreview(%s)",
                            self.channel_id, asset_path,
                        )

        # Switch: when now >= segment_end_time, promote preview to live (once per segment; no EOF).
        if now >= segment_end and segment_end != self._last_switch_at_segment_end_utc:
            ok = producer.switch_to_live()
            if ok:
                seg_ts = segment_end.timestamp()
                actual_ts = now.timestamp()
                self._logger.info(
                    "Channel %s clock-driven switch: Scheduled end: %.3fs | Actual switch: %.3fs",
                    self.channel_id, seg_ts, actual_ts,
                )
                self._last_switch_at_segment_end_utc = segment_end
                # Advance to next segment: end time = current boundary + next segment duration.
                next_plan = self.schedule_service.get_playout_plan_now(self.channel_id, segment_end)
                if next_plan:
                    next_duration = self._segment_duration_seconds(next_plan[0])
                    if next_duration > 0:
                        self._segment_end_time_utc = segment_end + timedelta(seconds=next_duration)
                        self._preload_done_for_next = False
                    else:
                        self._segment_end_time_utc = None
                else:
                    self._segment_end_time_utc = None

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

        This method is intentionally a stub here. It will be overridden by the RetroVue Core runtime.
        """
        _ = mode  # avoid unused var lint
        return None


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
        
        Logic:
        - Calculate grid block start (floor to 30-minute grid)
        - Determine if we're in program or filler segment
        - Calculate join-in-progress offset
        - Return playout plan with correct asset and start_pts
        """
        now = at_station_time
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        
        # Calculate grid block start (30-minute grid)
        block_start = self._floor_to_grid(now)
        
        # Determine active content and calculate join offset
        content_type, start_pts_ms = self._calculate_join_offset(
            now, block_start, self.program_duration_seconds
        )
        
        # Select asset path
        if content_type == "program":
            asset_path = self.program_asset_path
        else:
            asset_path = self.filler_asset_path
            # For filler, calculate absolute offset within filler file
            filler_offset_seconds = self._calculate_filler_offset(
                now, self.filler_epoch, self.filler_duration_seconds
            )
            # Adjust start_pts to account for filler's continuous virtual stream
            # start_pts_ms is offset within current block's filler segment
            # Add filler epoch offset to get absolute position in filler file
            block_filler_offset_seconds = start_pts_ms / 1000.0
            filler_absolute_offset_seconds = (filler_offset_seconds + block_filler_offset_seconds) % self.filler_duration_seconds
            start_pts_ms = int(filler_absolute_offset_seconds * 1000)
        
        # Build playout plan segment
        segment = {
            "asset_path": asset_path,
            "start_pts": start_pts_ms,  # Join-in-progress offset in milliseconds
            "content_type": content_type,  # "program" or "filler"
            "block_start_utc": block_start.isoformat(),
            "metadata": {
                "phase": "mock_grid",
                "grid_block_minutes": self.grid_block_minutes,
            },
        }
        
        return [segment]


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

    def __init__(self, channel_id: str, configuration: dict[str, Any]):
        super().__init__(channel_id, ProducerMode.NORMAL, configuration)
        self.air_process: channel_manager_launch.ProcessHandle | None = None
        self.socket_path: Path | None = None
        self.reader_socket_queue: Any = None  # queue.Queue: accepted UDS socket from Air after AttachStream
        self._stream_endpoint = f"/channel/{channel_id}.ts"
        self._grpc_addr: str | None = None  # Set after start(); used for LoadPreview/SwitchToLive

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
        }

        try:
            self._logger.info("Playout engine: AIR (no fallback)")
            socket_path_arg = self.socket_path if self.socket_path else None

            process, socket_path, reader_socket_queue, grpc_addr = channel_manager_launch.launch_air(
                playout_request=playout_request,
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
        start_offset_ms: int = 0,
        hard_stop_time_ms: int = 0,
    ) -> bool:
        """Load next asset into Air preview slot (clock-driven; no EOF). Returns success."""
        if not self._grpc_addr:
            self._logger.warning("Channel %s: load_preview skipped (no grpc_addr)", self.channel_id)
            return False
        try:
            ok = channel_manager_launch.air_load_preview(
                self._grpc_addr,
                channel_id_int=1,
                asset_path=asset_path,
                start_offset_ms=start_offset_ms,
                hard_stop_time_ms=hard_stop_time_ms,
            )
            if not ok:
                self._logger.warning("Channel %s: Air LoadPreview returned success=false", self.channel_id)
            return ok
        except Exception as e:
            self._logger.warning("Channel %s: LoadPreview failed: %s", self.channel_id, e)
            return False

    def switch_to_live(self) -> bool:
        """Promote Air preview to live (clock-driven; no EOF). Returns success."""
        if not self._grpc_addr:
            self._logger.warning("Channel %s: switch_to_live skipped (no grpc_addr)", self.channel_id)
            return False
        try:
            ok = channel_manager_launch.air_switch_to_live(self._grpc_addr, channel_id_int=1)
            if not ok:
                self._logger.warning("Channel %s: Air SwitchToLive returned success=false", self.channel_id)
            return ok
        except Exception as e:
            self._logger.warning("Channel %s: SwitchToLive failed: %s", self.channel_id, e)
            return False


class ChannelManagerDaemon:
    """
    RetroVue Core runtime managing all channels using runtime ChannelManager instances.
    
    Implements ChannelManagerProvider protocol for ProgramDirector integration.
    This is an internal implementation detail. The public-facing product is RetroVue.
    """

    def __init__(
        self,
        schedule_dir: Path | None,
        host: str = "0.0.0.0",
        port: int = 9000,
        *,
        mock_schedule_grid_mode: bool = False,
        program_asset_path: str | None = None,
        program_duration_seconds: float | None = None,
        filler_asset_path: str | None = None,
        filler_duration_seconds: float = 3600.0,
        mock_schedule_ab_mode: bool = False,
        asset_a_path: str | None = None,
        asset_b_path: str | None = None,
        segment_seconds: float = 10.0,
    ):
        self.schedule_dir = schedule_dir or Path(".")
        self._mock_schedule = schedule_dir is None and not mock_schedule_grid_mode and not mock_schedule_ab_mode
        self.host = host
        self.port = port
        self.clock = MasterClock()
        
        # Mock schedule configuration
        self.mock_schedule_grid_mode = mock_schedule_grid_mode
        self.program_asset_path = program_asset_path
        self.program_duration_seconds = program_duration_seconds
        self.filler_asset_path = filler_asset_path
        self.filler_duration_seconds = filler_duration_seconds
        self.mock_schedule_ab_mode = mock_schedule_ab_mode
        self.asset_a_path = asset_a_path
        self.asset_b_path = asset_b_path
        self.segment_seconds = segment_seconds
        
        # Internal implementations
        if mock_schedule_ab_mode:
            if not asset_a_path or not asset_b_path:
                raise ValueError("Mock A/B mode requires --asset-a and --asset-b")
            self.schedule_service = MockAlternatingScheduleService(
                clock=self.clock,
                asset_a_path=asset_a_path,
                asset_b_path=asset_b_path,
                segment_seconds=segment_seconds,
            )
        elif mock_schedule_grid_mode:
            if not program_asset_path or program_duration_seconds is None:
                raise ValueError("Mock grid mode requires program_asset_path and program_duration_seconds")
            if not filler_asset_path:
                raise ValueError("Mock grid mode requires filler_asset_path")
            self.schedule_service = MockGridScheduleService(
                clock=self.clock,
                program_asset_path=program_asset_path,
                program_duration_seconds=program_duration_seconds,
                filler_asset_path=filler_asset_path,
                filler_duration_seconds=filler_duration_seconds,
            )
        elif self._mock_schedule:
            self.schedule_service = Phase8MockScheduleService(self.clock)
        else:
            self.schedule_service = Phase8ScheduleService(self.schedule_dir, self.clock)
        self.program_director = Phase8ProgramDirector()
        
        # Channel registry: channel_id -> ChannelManager instance
        self.managers: dict[str, ChannelManager] = {}
        self.lock = threading.Lock()
        
        # ChannelStream registry per channel
        self.channel_streams: dict[str, ChannelStream] = {}
        
        # HTTP server
        self.fastapi_app = FastAPI(title="ChannelManager")
        self._register_endpoints()
        
        # Factory for creating Producers
        self._producer_factory = self._create_air_producer
        
        # Test mode flag (allows fake TS source)
        self.test_mode = os.getenv("RETROVUE_TEST_MODE") == "1"

        # Health-check thread: runs check_health() on all managers so segment-exit
        # (e.g. Phase 0 A/B 10s segment) triggers next-segment restart.
        self._health_check_stop = threading.Event()
        self._health_check_thread: threading.Thread | None = None
        self._health_check_interval_seconds = 1.0

    def _health_check_loop(self) -> None:
        """Background loop: periodically call check_health() on active (registered) channel managers only.
        When a channel is torn down (stop_channel), its manager is removed from the registry, so this
        loop will no longer invoke it. Stopped via _health_check_stop.set() in stop() — no wait for I/O.
        """
        _logger = logging.getLogger(__name__)
        while not self._health_check_stop.wait(timeout=self._health_check_interval_seconds):
            try:
                with self.lock:
                    managers = list(self.managers.values())
                for manager in managers:
                    try:
                        manager.check_health()
                        manager.tick()
                    except Exception as e:
                        _logger.warning(
                            "Health check failed for channel %s: %s",
                            getattr(manager, "channel_id", "?"),
                            e,
                            exc_info=True,
                        )
            except Exception as e:
                _logger.warning("Health check loop error: %s", e, exc_info=True)

    def _create_air_producer(self, channel_id: str, mode: str, config: dict[str, Any]) -> Producer | None:
        """Factory for creating Producer instances."""
        if mode != "normal":
            return None  # Only supports normal mode
        return Phase8AirProducer(channel_id, config)

    def _get_or_create_manager(self, channel_id: str) -> ChannelManager:
        """Get or create ChannelManager instance for a channel."""
        with self.lock:
            if channel_id not in self.managers:
                # Load schedule first (mock: no-op, Phase 8: loads from file)
                success, error = self.schedule_service.load_schedule(channel_id)
                if not success:
                    raise ChannelManagerError(f"Failed to load schedule for {channel_id}: {error}")

                # Create ChannelManager instance
                manager = ChannelManager(
                    channel_id=channel_id,
                    clock=self.clock,
                    schedule_service=self.schedule_service,
                    program_director=self.program_director,
                )
                
                # Mock grid: configure grid settings if in mock grid mode
                if self.mock_schedule_grid_mode:
                    manager._mock_grid_block_minutes = 30
                    manager._mock_grid_program_asset_path = self.program_asset_path
                    manager._mock_grid_filler_asset_path = self.filler_asset_path
                    manager._mock_grid_filler_epoch = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
                
                # Override _build_producer_for_mode to use our factory
                # Store original method and replace with our factory
                original_factory = manager._build_producer_for_mode
                def factory_wrapper(mode: str) -> Producer | None:
                    return self._producer_factory(channel_id, mode, {})
                manager._build_producer_for_mode = factory_wrapper
                
                self.managers[channel_id] = manager
                logging.getLogger(__name__).info(
                    "[channel %s] ChannelManager created",
                    channel_id,
                )

            return self.managers[channel_id]

    def _get_or_create_channel_stream(
        self, channel_id: str, manager: ChannelManager
    ) -> ChannelStream | None:
        """
        Get or create ChannelStream for a channel.
        
        If Producer is running and has socket_path, create ChannelStream.
        If test mode, use FakeTsSource (even if Producer lacks socket_path).
        """
        with self.lock:
            if channel_id in self.channel_streams:
                stream = self.channel_streams[channel_id]
                if stream.is_running():
                    return stream
                # Stream stopped, remove it
                self.channel_streams.pop(channel_id, None)

            # Create ChannelStream
            if self.test_mode:
                # Test mode: use fake TS source (doesn't need real Producer/playout engine)
                def ts_source_factory():
                    return FakeTsSource()

                channel_stream = ChannelStream(
                    channel_id=channel_id,
                    ts_source_factory=ts_source_factory,
                )
                self.channel_streams[channel_id] = channel_stream
                return channel_stream

            # Production: check if Producer is running (Phase8AirProducer)
            producer = manager.active_producer
            if not producer or not isinstance(producer, Phase8AirProducer):
                return None

            # Air-only: we are the UDS server; socket is delivered via queue (one per channel)
            if producer.reader_socket_queue is None:
                return None

            def ts_source_factory():
                return SocketTsSource(producer.reader_socket_queue.get(timeout=10))

            channel_stream = ChannelStream(
                channel_id=channel_id,
                ts_source_factory=ts_source_factory,
            )
            self.channel_streams[channel_id] = channel_stream
            return channel_stream

    def _register_endpoints(self):
        """Register HTTP endpoints with FastAPI."""

        @self.fastapi_app.get("/channellist.m3u")
        def get_channellist() -> Response:
            """Serve global M3U playlist for channel discovery."""
            with self.lock:
                channel_ids = sorted(self.managers.keys())

            if not channel_ids:
                return Response(
                    content="#EXTM3U\n",
                    media_type="application/vnd.apple.mpegurl",
                    status_code=status.HTTP_200_OK,
                )

            lines = ["#EXTM3U"]
            for channel_id in channel_ids:
                lines.append(
                    f'#EXTINF:-1 tvg-id="{channel_id}" tvg-name="{channel_id}",{channel_id}'
                )
                lines.append(f"http://localhost:{self.port}/channel/{channel_id}.ts")

            content = "\n".join(lines) + "\n"
            return Response(
                content=content,
                media_type="application/vnd.apple.mpegurl",
                status_code=status.HTTP_200_OK,
            )

        async def _wait_disconnect_then_cleanup(request: Request, cleanup: Any) -> None:
            """Phase 8.7: When client disconnects, run cleanup so viewer_count→0 triggers teardown."""
            try:
                await request.receive()
            except Exception:
                pass
            cleanup()

        @self.fastapi_app.get("/channel/{channel_id}.ts")
        async def get_channel_stream(request: Request, channel_id: str) -> Response:
            """Serve MPEG-TS stream for a specific channel (UDS fan-out). Phase 8.7: disconnect triggers teardown."""
            try:
                manager = self._get_or_create_manager(channel_id)
            except ChannelManagerError as e:
                return Response(
                    content=str(e),
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            import uuid
            session_id = str(uuid.uuid4())

            try:
                manager.viewer_join(session_id, {"channel_id": channel_id})
            except NoScheduleDataError:
                return Response(
                    content="No active schedule item",
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            except ProducerStartupError:
                return Response(
                    content="Air playout engine unavailable",
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            except Exception as e:
                print(f"Error starting playout for channel {channel_id}: {e}", file=sys.stderr)
                return Response(
                    content=f"Error starting playout: {e}",
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            channel_stream = self._get_or_create_channel_stream(channel_id, manager)
            if not channel_stream:
                return Response(
                    content="Air playout engine unavailable",
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            client_queue = channel_stream.subscribe(session_id)
            cleaned = []

            def cleanup_stream() -> None:
                if cleaned:
                    return
                cleaned.append(1)
                channel_stream.unsubscribe(session_id)
                manager.viewer_leave(session_id)
                if channel_stream.get_subscriber_count() == 0:
                    self.stop_channel(channel_id)
                    channel_stream.stop()
                    with self.lock:
                        self.channel_streams.pop(channel_id, None)

            asyncio.create_task(_wait_disconnect_then_cleanup(request, cleanup_stream))

            def generate_stream_from_channel():
                try:
                    for chunk in generate_ts_stream(client_queue):
                        yield chunk
                except GeneratorExit:
                    pass
                finally:
                    cleanup_stream()

            return StreamingResponse(
                generate_stream_from_channel(),
                media_type="video/mp2t",
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
                status_code=status.HTTP_200_OK,
            )

    def load_all_schedules(self) -> list[str]:
        """Load schedule data for discoverable channels. Phase 8.7: do NOT create ChannelManager
        here; managers are created only when viewer count goes 0 → 1 (get_channel_manager).
        """
        loaded_channels = []
        if self.mock_schedule_ab_mode:
            channel_id = MockAlternatingScheduleService.MOCK_AB_CHANNEL_ID
            success, _ = self.schedule_service.load_schedule(channel_id)
            if success:
                loaded_channels.append(channel_id)
            return loaded_channels
        if self._mock_schedule:
            channel_id = Phase8MockScheduleService.MOCK_CHANNEL_ID
            success, _ = self.schedule_service.load_schedule(channel_id)
            if success:
                loaded_channels.append(channel_id)
            return loaded_channels
        if not self.schedule_dir.exists():
            return loaded_channels

        for schedule_file in self.schedule_dir.glob("*.json"):
            channel_id = schedule_file.stem
            success, _ = self.schedule_service.load_schedule(channel_id)
            if success:
                loaded_channels.append(channel_id)

        return loaded_channels

    # ChannelManagerProvider protocol implementation
    def list_channels(self) -> list[str]:
        """List all available channel IDs (for ProgramDirector integration)."""
        with self.lock:
            return list(self.managers.keys())

    def has_channel_stream(self, channel_id: str) -> bool:
        """Return True if this channel has an active ChannelStream (for tests / Phase 8.7 invariants)."""
        with self.lock:
            return channel_id in self.channel_streams

    def get_channel_manager(self, channel_id: str) -> ChannelManager:
        """Get or create ChannelManager for a channel (ChannelManagerProvider protocol)."""
        return self._get_or_create_manager(channel_id)

    def stop_channel(self, channel_id: str) -> None:
        """Stop channel when last viewer disconnects; destroy ChannelManager (Phase 8.7). No wait for EOF or I/O."""
        _log = logging.getLogger(__name__)
        with self.lock:
            manager = self.managers.get(channel_id)
        if manager is not None:
            _log.info("[channel %s] ChannelManager destroyed (viewer count 0)", channel_id)
            manager.stop_channel()
            # Phase 8.7: Force-stop producer (terminates Air process) before removing manager from registry.
            if manager.active_producer:
                _log.info("[channel %s] Force-stopping producer (terminating Air)", channel_id)
                try:
                    manager.active_producer.stop()
                    manager.active_producer = None
                except Exception as e:
                    _log.warning("Error stopping producer for channel %s: %s", channel_id, e)
            # Phase 8.7: destroy ChannelManager — remove from registry so health-check will no longer invoke it.
            with self.lock:
                self.managers.pop(channel_id, None)
                channel_stream = self.channel_streams.pop(channel_id, None)
            if channel_stream is not None:
                _log.info("[teardown] stopping reader loop for channel %s", channel_id)
                try:
                    channel_stream.stop()
                except Exception as e:
                    _log.warning(
                        "Error stopping channel stream for %s: %s", channel_id, e
                    )
            _log.info("[teardown] channel %s removed from registry (health-check will no longer run for this channel)", channel_id)

    def start(self) -> None:
        """Start the HTTP server."""
        # Load all schedules on startup so /channellist.m3u can list available channels
        self.load_all_schedules()

        # Start health-check thread so segment-exit (e.g. mock A/B) restarts next segment
        self._health_check_stop.clear()
        self._health_check_thread = threading.Thread(
            target=self._health_check_loop,
            name="channel-manager-health-check",
            daemon=True,
        )
        self._health_check_thread.start()

        config = Config(self.fastapi_app, host=self.host, port=self.port, log_level="info")
        self.server = Server(config)
        self.server.run()

    def stop(self) -> None:
        """Stop the HTTP server and terminate all Producers. No wait for EOF or external I/O."""
        _log = logging.getLogger(__name__)
        if hasattr(self, "server") and self.server:
            self.server.should_exit = True

        # Stop health-check thread synchronously (set event, then join with timeout)
        if getattr(self, "_health_check_stop", None) is not None:
            _log.info("[teardown] stopping health-check loop")
            self._health_check_stop.set()
        if getattr(self, "_health_check_thread", None) is not None and self._health_check_thread.is_alive():
            self._health_check_thread.join(timeout=5.0)

        # Stop all ChannelStreams
        with self.lock:
            for channel_stream in self.channel_streams.values():
                channel_stream.stop()
            self.channel_streams.clear()

            # Terminate all Producers via ChannelManager instances
            for manager in self.managers.values():
                # Stop Producer if running (via viewer_leave if needed, or directly)
                if manager.active_producer:
                    manager.active_producer.stop()
                    manager.active_producer = None

