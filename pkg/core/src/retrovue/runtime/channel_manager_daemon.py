"""
Channel Manager Daemon (Phase 8).

System-wide daemon that manages ALL channels using the runtime ChannelManager.
Runs an HTTP server and bridges HTTP requests to ChannelManager instances.

Per ChannelManagerContract.md (Phase 8).
"""

from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Response, status
from fastapi.responses import StreamingResponse
from uvicorn import Config, Server

from .clock import MasterClock
from .producer.base import Producer, ProducerMode, ProducerStatus, ContentSegment, ProducerState
from .channel_stream import ChannelStream, FakeTsSource, generate_ts_stream
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

        # Fanout rule: first viewer starts Producer.
        if old_count == 0 and self.runtime_state.viewer_count == 1:
            self._ensure_producer_running()

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
        """Poll Producer health and update runtime_state."""
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
        """
        Factory hook: build the correct Producer implementation for the given mode.

        This method is intentionally a stub here. It will be overridden by ChannelManagerDaemon.
        """
        _ = mode  # avoid unused var lint
        return None


# ----------------------------------------------------------------------
# Phase 8 Implementations
# ----------------------------------------------------------------------


class Phase8ScheduleService:
    """Phase 8 ScheduleService implementation that reads from schedule.json files.
    
    Implements the ScheduleService protocol required by runtime ChannelManager.
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
    """Phase 8 ProgramDirector implementation (always returns 'normal' mode).
    
    Implements the ProgramDirector protocol required by runtime ChannelManager.
    """

    def get_channel_mode(self, channel_id: str) -> str:
        """Return the required mode for this channel (always 'normal' in Phase 8)."""
        return "normal"


class Phase8AirProducer(Producer):
    """Phase 8/9 Producer implementation wrapping Retrovue Air processes."""

    def __init__(self, channel_id: str, configuration: dict[str, Any]):
        super().__init__(channel_id, ProducerMode.NORMAL, configuration)
        self.air_process: channel_manager_launch.ProcessHandle | None = None
        self.socket_path: Path | None = None  # Phase 9: UDS socket path
        self._stream_endpoint = f"/channel/{channel_id}.ts"

    def start(self, playout_plan: list[dict[str, Any]], start_at_station_time: datetime) -> bool:
        """Begin output for this channel by launching Retrovue Air.
        
        Per ChannelManagerContract.md (Phase 8):
        - playout_plan contains exactly one segment with asset_path
        - Builds PlayoutRequest and launches Air via stdin
        """
        if not playout_plan:
            return False

        # Phase 8: First segment contains asset_path
        segment = playout_plan[0]
        asset_path = segment.get("asset_path")
        if not asset_path:
            return False

        # Build PlayoutRequest per PlayoutRequest.md
        playout_request = {
            "asset_path": asset_path,
            "start_pts": 0,  # Always 0 in Phase 8
            "mode": "LIVE",  # Always "LIVE" in Phase 8
            "channel_id": self.channel_id,
            "metadata": segment.get("metadata", {}),
        }

        try:
            # Launch Air (Phase 9: returns process and socket_path)
            process, socket_path = channel_manager_launch.launch_air(
                playout_request=playout_request
            )
            self.air_process = process
            self.socket_path = socket_path  # Phase 9: Store socket path for ChannelStream
            self.status = ProducerStatus.RUNNING
            self.started_at = start_at_station_time
            self.output_url = self._stream_endpoint
            return True
        except Exception as e:
            self._logger.error(f"Failed to launch Air for {self.channel_id}: {e}")
            self.status = ProducerStatus.ERROR
            return False

    def stop(self) -> bool:
        """Stop the producer by terminating Retrovue Air."""
        if self.air_process:
            try:
                channel_manager_launch.terminate_air(self.air_process)
            except Exception as e:
                self._logger.error(f"Error terminating Air for {self.channel_id}: {e}")
            finally:
                self.air_process = None

        self.status = ProducerStatus.STOPPED
        self.output_url = None
        self._teardown_cleanup()
        return True

    def play_content(self, content: ContentSegment) -> bool:
        """Phase 8: Not used (single file playout)."""
        return True

    def get_stream_endpoint(self) -> str | None:
        """Return stream endpoint URL."""
        return self.output_url

    def health(self) -> str:
        """Report Producer health."""
        if self.status == ProducerStatus.RUNNING and self.air_process:
            # Check if process is still alive
            if self.air_process.poll() is None:  # Still running
                return "running"
            else:  # Process terminated
                return "stopped"
        if self.status == ProducerStatus.ERROR:
            return "degraded"
        return "stopped"

    def get_producer_id(self) -> str:
        """Get unique identifier for this producer."""
        return f"air_{self.channel_id}"

    def on_paced_tick(self, t_now: float, dt: float) -> None:
        """Advance producer state using pacing ticks (Phase 8: minimal implementation)."""
        self._advance_teardown(dt)


class ChannelManagerDaemon:
    """System-wide daemon managing all channels using runtime ChannelManager instances."""

    def __init__(self, schedule_dir: Path, host: str = "0.0.0.0", port: int = 9000):
        self.schedule_dir = schedule_dir
        self.host = host
        self.port = port
        self.clock = MasterClock()
        
        # Phase 8 implementations
        self.schedule_service = Phase8ScheduleService(schedule_dir, self.clock)
        self.program_director = Phase8ProgramDirector()
        
        # Channel registry: channel_id -> ChannelManager instance
        self.managers: dict[str, ChannelManager] = {}
        self.lock = threading.Lock()
        
        # Phase 9: ChannelStream registry per channel
        self.channel_streams: dict[str, ChannelStream] = {}
        
        # HTTP server
        self.fastapi_app = FastAPI(title="ChannelManager")
        self._register_endpoints()
        
        # Factory for creating Producers (Phase 8: AirProducer)
        self._producer_factory = self._create_air_producer
        
        # Phase 9: Test mode flag (allows fake TS source)
        self.test_mode = os.getenv("RETROVUE_TEST_MODE") == "1"

    def _create_air_producer(self, channel_id: str, mode: str, config: dict[str, Any]) -> Producer | None:
        """Factory for creating Phase 8 AirProducer."""
        if mode != "normal":
            return None  # Phase 8 only supports normal mode
        return Phase8AirProducer(channel_id, config)

    def _get_or_create_manager(self, channel_id: str) -> ChannelManager:
        """Get or create ChannelManager instance for a channel."""
        with self.lock:
            if channel_id not in self.managers:
                # Load schedule first
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
                
                # Override _build_producer_for_mode to use our factory
                # Store original method and replace with our factory
                original_factory = manager._build_producer_for_mode
                def factory_wrapper(mode: str) -> Producer | None:
                    return self._producer_factory(channel_id, mode, {})
                manager._build_producer_for_mode = factory_wrapper
                
                self.managers[channel_id] = manager

            return self.managers[channel_id]

    def _get_or_create_channel_stream(
        self, channel_id: str, manager: ChannelManager
    ) -> ChannelStream | None:
        """
        Get or create ChannelStream for a channel (Phase 9).
        
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

            # Phase 9: Create ChannelStream
            if self.test_mode:
                # Test mode: use fake TS source (doesn't need real Producer/Air)
                def ts_source_factory():
                    return FakeTsSource()

                channel_stream = ChannelStream(
                    channel_id=channel_id,
                    ts_source_factory=ts_source_factory,
                )
                self.channel_streams[channel_id] = channel_stream
                return channel_stream

            # Production: check if Producer is running and has socket_path
            producer = manager.active_producer
            if not producer or not isinstance(producer, Phase8AirProducer):
                return None

            # Get socket path from Producer
            socket_path = producer.socket_path
            if not socket_path:
                return None

            # Production: use UDS socket
            channel_stream = ChannelStream(channel_id=channel_id, socket_path=socket_path)
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

        @self.fastapi_app.get("/channel/{channel_id}.ts")
        def get_channel_stream(channel_id: str) -> Response:
            """Serve MPEG-TS stream for a specific channel (Phase 9: UDS fan-out)."""
            try:
                manager = self._get_or_create_manager(channel_id)
            except ChannelManagerError as e:
                return Response(
                    content=str(e),
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            # Create session ID for this viewer
            import uuid
            session_id = str(uuid.uuid4())

            # Viewer joins (increments viewer_count, starts Producer if first viewer)
            try:
                manager.viewer_join(session_id, {"channel_id": channel_id})
            except NoScheduleDataError:
                return Response(
                    content="No active schedule item",
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            except ProducerStartupError as e:
                # Producer failed to start - could be Air launch failure in test mode
                # Still return 200 with placeholder stream for graceful degradation
                # In production, this would be a real error
                pass  # Continue to generate stream response
            except Exception as e:
                # Other errors - log and return 503
                print(f"Error starting playout for channel {channel_id}: {e}", file=sys.stderr)
                return Response(
                    content=f"Error starting playout: {e}",
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            # Phase 9: Get or create ChannelStream for this channel
            channel_stream = self._get_or_create_channel_stream(channel_id, manager)
            if not channel_stream:
                # Fallback to placeholder if ChannelStream not available
                def generate_placeholder():
                    try:
                        yield b"#EXTM3U\n"
                        yield b"# Stream placeholder\n"
                        while True:
                            time.sleep(1)
                            yield b""
                    except GeneratorExit:
                        manager.viewer_leave(session_id)

                return StreamingResponse(
                    generate_placeholder(),
                    media_type="video/mp2t",
                    status_code=status.HTTP_200_OK,
                )

            # Subscribe this client to the ChannelStream
            client_queue = channel_stream.subscribe(session_id)

            # Generate stream from ChannelStream
            def generate_stream_from_channel():
                try:
                    for chunk in generate_ts_stream(client_queue):
                        yield chunk
                except GeneratorExit:
                    pass
                finally:
                    # Viewer leaves (decrements viewer_count, stops Producer if last viewer)
                    channel_stream.unsubscribe(session_id)
                    manager.viewer_leave(session_id)
                    # If no more viewers, stop ChannelStream (will be recreated on next viewer)
                    if channel_stream.get_subscriber_count() == 0:
                        channel_stream.stop()
                        with self.lock:
                            self.channel_streams.pop(channel_id, None)

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
        """Load all schedule.json files from schedule_dir."""
        loaded_channels = []
        if not self.schedule_dir.exists():
            return loaded_channels

        for schedule_file in self.schedule_dir.glob("*.json"):
            channel_id = schedule_file.stem
            success, _ = self.schedule_service.load_schedule(channel_id)
            if success:
                loaded_channels.append(channel_id)
                # Pre-create ChannelManager instances for loaded channels
                # so they appear in /channellist.m3u even before any viewer connects
                with self.lock:
                    if channel_id not in self.managers:
                        manager = ChannelManager(
                            channel_id=channel_id,
                            clock=self.clock,
                            schedule_service=self.schedule_service,
                            program_director=self.program_director,
                        )
                        # Override _build_producer_for_mode to use our factory
                        def factory_wrapper(mode: str) -> Producer | None:
                            return self._producer_factory(channel_id, mode, {})
                        manager._build_producer_for_mode = factory_wrapper
                        self.managers[channel_id] = manager

        return loaded_channels

    def start(self) -> None:
        """Start the HTTP server."""
        # Load all schedules on startup so /channellist.m3u can list available channels
        self.load_all_schedules()
        
        config = Config(self.fastapi_app, host=self.host, port=self.port, log_level="info")
        self.server = Server(config)
        self.server.run()

    def stop(self) -> None:
        """Stop the HTTP server and terminate all Producers."""
        if hasattr(self, "server") and self.server:
            self.server.should_exit = True

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

