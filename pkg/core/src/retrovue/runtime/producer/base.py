"""
Producer Protocol (Capability Provider)

Pattern: Output Generator

The Producer is the component that actually emits audiovisual output for a channel.
Producers are swappable. ChannelManager chooses which Producer implementation to run for a channel.
All Producers must implement the same interface so ChannelManager can control them in a consistent way.

Key Responsibilities:
- Generate broadcast streams for assigned channel
- Support multiple output modes (normal, emergency, guide)
- Handle real-time encoding and streaming
- Ensure seamless transitions between content segments
- Provide stream URLs for viewer access

Boundaries:
- Producer IS allowed to: Generate output, handle encoding, manage streams, play provided content
- Producer IS NOT allowed to: Pick content, make content decisions, access Content Manager directly, make scheduling decisions
- Producer cannot talk to Content Manager or Schedule Manager directly. All instructions come from ChannelManager via the playout plan.

Design Principles:
- Pure output generation
- Mode-based operation
- Content-agnostic (plays what it's told to play)
- Real-time streaming and encoding
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import logging
from typing import Any


class ProducerMode(Enum):
    """Producer operational modes"""

    NORMAL = "normal"
    EMERGENCY = "emergency"
    GUIDE = "guide"


class ProducerStatus(Enum):
    """Producer operational status"""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class ProducerState:
    """Current state of a producer"""

    producer_id: str
    channel_id: str
    mode: ProducerMode
    status: ProducerStatus
    output_url: str | None
    started_at: datetime | None
    configuration: dict[str, Any]


@dataclass
class ContentSegment:
    """Content segment to play"""

    asset_id: str
    start_time: datetime
    end_time: datetime
    segment_type: str  # e.g. "content", "commercial", "bumper", etc.
    metadata: dict[str, Any]


@dataclass
class SegmentEdge:
    """Represents a boundary event for a content segment."""

    segment: ContentSegment
    kind: str  # e.g. "end"
    station_time: float


class Producer(ABC):
    """
    Base class for output generators that create broadcast streams.

    Pattern: Output Generator

    This is the base class for all producers that generate broadcast output.
    It defines the interface for content playback and stream generation.

    Key Responsibilities:
    - Generate broadcast streams for assigned channel
    - Support multiple output modes (normal, emergency, guide)
    - Handle real-time encoding and streaming
    - Ensure seamless transitions between content segments
    - Provide stream URLs for viewer access
    - Honor pacing ticks and station-time offsets

    Boundaries:
    - IS allowed to: Generate output, handle encoding, manage streams, play provided content
    - IS NOT allowed to: Pick content, make content decisions, access Content Manager directly, make scheduling decisions
    """

    def __init__(self, channel_id: str, mode: ProducerMode, configuration: dict[str, Any]):
        """
        Initialize the Producer.

        Args:
            channel_id: Channel this producer serves
            mode: Producer operational mode
            configuration: Producer-specific settings
        """
        self.channel_id = channel_id
        self.mode = mode
        self.configuration = configuration
        self.status = ProducerStatus.STOPPED
        self.output_url = None
        self.started_at = None
        self._segment_edges: list[SegmentEdge] = []
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # Teardown management
        default_grace = 0.5
        default_timeout = 5.0
        if isinstance(configuration, dict):
            default_grace = float(configuration.get("teardown_grace_seconds", default_grace))
            default_timeout = float(configuration.get("teardown_timeout_seconds", default_timeout))
        self._teardown_grace_seconds = default_grace
        self._teardown_timeout_default = default_timeout
        self._tearing_down = False
        self._teardown_elapsed = 0.0
        self._teardown_timeout = default_timeout
        self._teardown_reason: str | None = None
        self._teardown_ready = False

    @abstractmethod
    def start(self, playout_plan: list[dict[str, Any]], start_at_station_time: datetime) -> bool:
        """
        Begin output for this channel.

        Args:
            playout_plan: The resolved segment sequence that should air
            start_at_station_time: From MasterClock, allows us to join mid-program instead of always starting at frame 0

        Returns:
            True if producer started successfully
        """
        pass

    @abstractmethod
    def stop(self) -> bool:
        """
        Stop the producer and clean up resources.

        Returns:
            True if producer stopped successfully
        """
        pass

    @abstractmethod
    def play_content(self, content: ContentSegment) -> bool:
        """
        Play a content segment.

        Args:
            content: Content segment to play

        Returns:
            True if content started playing successfully
        """
        pass

    @abstractmethod
    def get_stream_endpoint(self) -> str | None:
        """
        Return a handle / URL / socket description that viewers can attach to.

        Returns:
            Stream endpoint URL, or None if not available
        """
        pass

    @abstractmethod
    def health(self) -> str:
        """
        Report whether the Producer is running, degraded, or stopped.

        Returns:
            Health status: 'running', 'degraded', or 'stopped'
        """
        pass

    def get_state(self) -> ProducerState:
        """
        Get current state of the producer.

        Returns:
            ProducerState with current information
        """
        return ProducerState(
            producer_id=self.get_producer_id(),
            channel_id=self.channel_id,
            mode=self.mode,
            status=self.status,
            output_url=self.output_url,
            started_at=self.started_at,
            configuration=self.configuration,
        )

    @abstractmethod
    def get_producer_id(self) -> str:
        """
        Get unique identifier for this producer.

        Returns:
            Producer identifier
        """
        pass

    @abstractmethod
    def on_paced_tick(self, t_now: float, dt: float) -> None:
        """
        Advance the producer using the pace loop.

        Args:
            t_now: Current station time supplied by MasterClock.
            dt: Seconds elapsed since the previous tick (already clamped by PaceController).
        """
        pass

    def poll_segment_edges(self) -> list[SegmentEdge]:
        """Return and clear the list of queued segment boundary events."""
        edges = self._segment_edges
        self._segment_edges = []
        return edges

    def _emit_segment_edge(self, edge: SegmentEdge) -> None:
        """Utility for subclasses to queue a segment boundary event."""
        self._segment_edges.append(edge)

    def get_segment_progress(self) -> tuple[str | None, float]:
        """
        Return the current segment identifier and position in seconds.

        Defaults to no segment information.
        """
        return (None, 0.0)

    def get_frame_counters(self) -> tuple[int | None, int | None]:
        """
        Return dropped and queued frame counters if available.

        Defaults to unknown counters.
        """
        return (None, None)

    # ------------------------------------------------------------------
    # Teardown orchestration
    # ------------------------------------------------------------------

    def request_teardown(self, reason: str, timeout: float | None = None) -> None:
        """Begin graceful teardown and transition to STOPPING state."""
        if self._tearing_down:
            return
        self._tearing_down = True
        self._teardown_elapsed = 0.0
        self._teardown_timeout = timeout if timeout is not None else self._teardown_timeout_default
        self._teardown_reason = reason
        self._teardown_ready = False
        self.status = ProducerStatus.STOPPING
        self._logger.info(
            "Producer %s teardown requested (reason=%s, timeout=%.2fs)",
            self.channel_id,
            reason,
            self._teardown_timeout,
        )
        self._on_teardown_requested(reason)

    def teardown_in_progress(self) -> bool:
        """Return True while the producer is draining for shutdown."""
        return self._tearing_down

    def signal_teardown_ready(self) -> None:
        """Signal that buffers are drained and teardown can complete."""
        if self._tearing_down:
            self._teardown_ready = True

    def _on_teardown_requested(self, reason: str) -> None:
        """Hook for subclasses to initiate resource draining."""

    def _advance_teardown(self, dt: float) -> bool:
        """
        Progress graceful shutdown.

        Returns True when teardown consumed the tick (no further work this tick).
        """
        if not self._tearing_down:
            return False
        if dt > 0.0:
            self._teardown_elapsed += dt
        timeout_reached = self._teardown_elapsed >= self._teardown_timeout
        if not self._teardown_ready and self._teardown_elapsed >= self._teardown_grace_seconds:
            self._teardown_ready = True
        if self._teardown_ready or timeout_reached:
            self._finish_teardown(force=timeout_reached and not self._teardown_ready)
        return True

    def _finish_teardown(self, *, force: bool) -> None:
        if not self._tearing_down:
            return
        reason = self._teardown_reason or "unspecified"
        if force:
            self._logger.warning(
                "Producer %s forced to stop after teardown timeout (reason=%s)",
                self.channel_id,
                reason,
            )
        else:
            self._logger.info(
                "Producer %s completed teardown (reason=%s)",
                self.channel_id,
                reason,
            )
        stopped = self.stop()
        if not stopped:
            self._logger.warning("Producer %s failed to acknowledge stop during teardown", self.channel_id)
        self.status = ProducerStatus.STOPPED
        self._teardown_cleanup()

    def _teardown_cleanup(self) -> None:
        self._tearing_down = False
        self._teardown_elapsed = 0.0
        self._teardown_ready = False
        self._teardown_reason = None
