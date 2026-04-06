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
import traceback
import weakref
from datetime import datetime, timedelta, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable


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
from .channel_stream import ChannelStream, SocketTsSource, generate_ts_stream
from .config import (
    ChannelConfig,
    ChannelConfigProvider,
    InlineChannelConfigProvider,
    MOCK_CHANNEL_CONFIG,
)
from ..usecases import channel_manager_launch
from typing import Sequence, TYPE_CHECKING
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
# Protocols — canonical definitions live in retrovue/runtime/protocols.py
# Re-exported here for backward compatibility.
# ----------------------------------------------------------------------
from .protocols import ScheduleService, ProgramDirectorProtocol as ProgramDirector  # noqa: F401


# ----------------------------------------------------------------------
# Join-In-Progress (JIP) — pure computation
# Contract: docs/contracts/runtime/INV-JOIN-IN-PROGRESS-BLOCKPLAN.md
# ----------------------------------------------------------------------


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

    durations = [
        entry.get("duration_ms", block_duration_ms) for entry in playout_plan
    ]
    cycle_length_ms = sum(durations)

    if cycle_length_ms <= 0:
        return (0, 0)

    elapsed_ms = (now_utc_ms - cycle_origin_utc_ms) % cycle_length_ms

    accumulated = 0
    for i, dur in enumerate(durations):
        if accumulated + dur > elapsed_ms:
            return (i, elapsed_ms - accumulated)
        accumulated += dur

    last = len(durations) - 1
    return (last, elapsed_ms - sum(durations[:last]))


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
    # INV-PAD-ONLY-TRAFFIC-001: JIP pads have spot_index=None (corrective, not traffic)
    placed = sum(s["segment_duration_ms"] for s in result)
    gap = block_dur_ms - placed
    if gap > 0:
        if result and result[-1].get("segment_type") == "pad" and result[-1].get("spot_index") is None:
            # Only extend an existing JIP/non-traffic pad; do not extend a traffic pad
            result[-1]["segment_duration_ms"] += gap
        else:
            result.append({"segment_type": "pad", "segment_duration_ms": gap, "spot_index": None})
    return result


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
# Playlist contract types — moved to retrovue.scheduling.playlist_types
# Re-exported here for import-site compatibility during migration.
# ----------------------------------------------------------------------
from retrovue.scheduling.playlist_types import Playlist, PlaylistSegment  # noqa: F401


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
        resolved_config: Any = None,
        on_linger_expired: Callable[[], None] | None = None,
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
            resolved_config: Frozen resolved config from config resolver (REQUIRED)
            on_linger_expired: Callback invoked when linger timer fires and no viewers remain.
                               Must be provided; PD is the sole teardown authority (INV-LIFECYCLE-PD-SOLE-TEARDOWN-001).
        """
        if resolved_config is None:
            raise RuntimeError(
                "resolved_config is required for ChannelManager — "
                "fallback defaults are no longer supported"
            )
        self.channel_id = channel_id
        self.clock = clock
        assert self.clock is not None, "ChannelManager requires a MasterClock"
        self.schedule_service = schedule_service
        self.program_director = program_director
        assert on_linger_expired is not None, (
            "INV-LIFECYCLE-PD-SOLE-TEARDOWN-001 violated: "
            "ChannelManager must be constructed with on_linger_expired callback. "
            "PD is the sole teardown authority — omitting this callback is forbidden."
        )
        self.on_linger_expired: Callable[[], None] = on_linger_expired
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
        self._resolved_config = resolved_config
        self._logger = logging.getLogger(__name__)
        # INV-CONFIG-IMMUTABLE-001: Read from resolved config (required).
        _ch = resolved_config["channel"]
        self._teardown_timeout_seconds = _ch["teardown_timeout_seconds"]
        self._teardown_started_station: float | None = None
        self._teardown_reason: str | None = None

        # Mock grid configuration (when using mock grid schedule)
        self._mock_grid_block_minutes = _ch["mock_grid_block_minutes"]
        self._mock_grid_program_asset_path: str | None = None  # Set from daemon config
        self._mock_grid_filler_asset_path: str | None = None  # Set from daemon config
        self._mock_grid_filler_epoch: datetime | None = None  # Epoch for filler offset calculation

        # Channel lifecycle: RUNNING (on-air or idle with viewers) or STOPPED (last viewer left).
        # When STOPPED, health/reconnect logic does nothing; ProgramDirector calls stop_channel on last viewer.
        self._channel_state: str = "RUNNING"  # "RUNNING" | "STOPPED"
        # Reason for stop_channel; passed to Producer/AIR for accurate StopBlockPlanSession logging.
        self._stop_reason: str = "channel_stop"

        # Linger: grace period before tearing down producer after last viewer leaves.
        self.LINGER_SECONDS: int = _ch["linger_seconds"]
        # INV-CHANNEL-LIVENESS-RECOVERY-001: Recovery constants
        _rec = _ch["recovery"]
        self._RECOVERY_BASE_DELAY_S: float = _rec["base_delay_seconds"]
        self._RECOVERY_MAX_ATTEMPTS: int = _rec["max_attempts"]
        self._linger_handle: asyncio.TimerHandle | None = None
        self._linger_deadline: float | None = None

        # INV-VIEWER-LIFECYCLE: Thread-safe viewer count transitions
        self._viewer_lock: threading.Lock = threading.Lock()
        # INV-LIFECYCLE-OBSERVABILITY-001: session that triggered current channel activation
        self._trigger_session_id: str | None = None

        # BlockPlan only
        self._blockplan_mode: bool = True
        self._pending_fatal: BaseException | None = None

        # --- HLS delivery state (Phase 5 integration) ---
        self._hls_segment_ring: "SegmentRing | None" = None
        self._hls_segmenter: "HlsSegmenter | None" = None
        self._hls_manifest_generator: "ManifestGenerator | None" = None
        self._hls_session_manager: "HlsSessionManager | None" = None
        self._hls_segment_counter: int = 0  # persists across producer restarts
        self._init_hls_state()

        # INV-CHANNEL-LIVENESS-RECOVERY-001: Recovery state
        self._recovery_attempts: int = 0
        self._recovery_timer: threading.Timer | None = None
        # Phase 8.5a: track first segment so we emit the lifecycle event once.
        self._first_segment_logged: bool = False

        # Channel configuration (set by daemon when creating manager)
        self.channel_config: ChannelConfig | None = None

    def _init_hls_state(self) -> None:
        """Initialize per-channel HLS delivery state.

        Creates SegmentRing, HlsSegmenter, ManifestGenerator, and
        HlsSessionManager for this channel. Called once at construction.
        """
        try:
            from retrovue.runtime.hls import (
                SegmentRing,
                HlsSegmenter,
                ManifestGenerator,
                HlsSessionManager,
            )
            # INV-CONFIG-IMMUTABLE-001: HLS params from resolved config (required).
            _hls = self._resolved_config["hls"]
            _hls_ring = _hls["ring"]
            _hls_seg = _hls["segmenter"]
            _hls_sess = _hls["session"]
            self._hls_segment_ring = SegmentRing(
                capacity=_hls_ring["capacity"],
                manifest_window=_hls_ring["manifest_window"],
            )
            self._hls_segmenter = HlsSegmenter(
                channel_id=self.channel_id,
                segment_ring=self._hls_segment_ring,
                target_duration_ms=_hls_seg["target_duration_ms"],
                max_gop_ms=_hls_seg["max_gop_ms"],
                starting_index=self._hls_segment_counter,
                diagnostic_hook=getattr(self.program_director, "hls_diag_event", None),
            )
            self._hls_manifest_generator = ManifestGenerator(self.channel_id)
            self._hls_session_manager = HlsSessionManager(
                channel_id=self.channel_id,
                session_timeout_ms=_hls_sess["timeout_ms"],
                reap_interval_ms=_hls_sess["reap_interval_ms"],
            )
            self._logger.debug(
                "HLS delivery state initialized for channel %s", self.channel_id,
            )
        except Exception as exc:
            self._logger.warning(
                "HLS delivery state init failed for channel %s: %s — "
                "HLS will be unavailable for this channel",
                self.channel_id, exc,
            )

    @property
    def hls_segment_ring(self) -> "SegmentRing | None":
        """Per-channel segment ring (for HLS endpoint access)."""
        return self._hls_segment_ring

    @property
    def hls_segmenter(self) -> "HlsSegmenter | None":
        """Per-channel HLS segmenter (for ChannelStream byte feed)."""
        return self._hls_segmenter

    @property
    def hls_manifest_generator(self) -> "ManifestGenerator | None":
        """Per-channel manifest generator (for HLS playlist endpoint)."""
        return self._hls_manifest_generator

    @property
    def hls_session_manager(self) -> "HlsSessionManager | None":
        """Per-channel HLS session manager (for viewer presence tracking)."""
        return self._hls_session_manager

    def _reset_hls_segmenter_for_restart(self) -> None:
        """Reset the HLS segmenter for a producer restart.

        INV-HLS-RESTART-DISCONTINUITY-001: The next segment carries discontinuity.
        INV-HLS-SEGMENT-IDENTITY-001: Index continues from counter.
        """
        if self._hls_segmenter is not None:
            self._hls_segmenter.reset_for_restart(self._hls_segment_counter)

    def _update_hls_segment_counter(self) -> None:
        """Sync the segment counter from the segmenter's state."""
        if self._hls_segmenter is not None:
            last = self._hls_segmenter.last_completed_index()
            if last is not None:
                prev = self._hls_segment_counter
                self._hls_segment_counter = last + 1
                # Phase 8.5a: emit first_segment event exactly once per activation.
                if prev == 0 and last == 0 and not self._first_segment_logged:
                    self._first_segment_logged = True
                    self._emit_lifecycle_event(
                        "first_segment",
                        event_scope="channel",
                        segment_index=last,
                        viewer_count=self.runtime_state.viewer_count,
                    )

    # ------------------------------------------------------------------
    # Phase 8.5a: Structured lifecycle event emission (DEBUG, gated)
    # ------------------------------------------------------------------

    def _emit_lifecycle_event(self, event: str, *, event_scope: str, **fields: object) -> None:
        """Emit a structured DEBUG lifecycle event. All fields are key=value.

        INV-LIFECYCLE-OBSERVABILITY-001: every event includes event_scope.
        Session-scoped events carry session_id; channel-scoped events carry
        channel_id and optionally trigger_session_id.

        Events:
            channel_activated  — producer started successfully (channel)
            first_segment      — first HLS segment pushed to ring (channel)
            viewer_join        — viewer session registered (session)
            viewer_leave       — viewer session removed (session)
            linger_start       — linger grace period started (channel)
            linger_expire      — linger fired, no viewers remain (channel)
            linger_cancel      — linger cancelled (viewer reconnected) (channel)
            teardown           — stop_channel() entered (channel)
        """
        if not self._logger.isEnabledFor(10):  # logging.DEBUG == 10
            return
        parts = " ".join(f"{k}={v}" for k, v in fields.items())
        self._logger.debug(
            "[lifecycle] channel=%s event=%s event_scope=%s %s",
            self.channel_id, event, event_scope, parts,
        )

    def stop_channel(self, reason: str = "channel_stop") -> None:
        """
        Enter STOPPED state and stop the producer. No wait for EOF or segment completion.
        Called by ProgramDirector when the last viewer disconnects (StopChannel(channel_id))
        or on explicit stop. Explicit stop bypasses linger — teardown is immediate.

        reason: Passed to AIR StopBlockPlanSession for accurate logging. Use
        "last_viewer_left" only when stopping due to viewer count 1→0; use
        "channel_stop" for admin/explicit stop.
        """
        self._emit_lifecycle_event("teardown", event_scope="channel", reason=reason, viewer_count=self.runtime_state.viewer_count)
        self._logger.debug(
            "[teardown] stopping producer for channel %s (reason=%s)", self.channel_id, reason
        )
        self._stop_reason = reason
        self._cancel_linger()
        # INV-CHANNEL-LIVENESS-RECOVERY-001: Cancel any pending recovery
        self._recovery_attempts = 0
        if self._recovery_timer is not None:
            self._recovery_timer.cancel()
            self._recovery_timer = None
        self._channel_state = "STOPPED"
        self._teardown_reason = None
        self._pending_fatal = None
        # Phase 8.5a: reset so first_segment fires again on re-activation.
        self._first_segment_logged = False
        # Clear stale HLS window so reconnect cannot consume prior-activation manifest/segments.
        if self._hls_segment_ring is not None:
            self._hls_segment_ring.clear()

        # Preserve index continuity and reset segmenter parser state for next activation.
        self._update_hls_segment_counter()
        self._reset_hls_segmenter_for_restart()

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

    # Mock grid: alignment & offset calculation — compatibility shims restored from main
    # These were deleted by the refactor but are required by contract tests.

    def _floor_to_grid(self, now: "datetime") -> "datetime":
        """Calculate the grid block start time (floor to nearest grid boundary)."""
        grid_minutes = self._mock_grid_block_minutes
        block_minute = (now.minute // grid_minutes) * grid_minutes
        return now.replace(minute=block_minute, second=0, microsecond=0)

    def _calculate_join_offset(
        self,
        now: "datetime",
        block_start: "datetime",
        program_duration_seconds: float,
    ) -> tuple[str, float]:
        """Calculate join-in-progress offset for viewer tuning in mid-block."""
        elapsed = (now - block_start).total_seconds()
        if elapsed < program_duration_seconds:
            return ("program", int(elapsed * 1000))
        else:
            return ("filler", int((elapsed - program_duration_seconds) * 1000))

    def _calculate_filler_offset(
        self,
        master_clock: "datetime",
        filler_epoch: "datetime",
        filler_duration_seconds: float,
    ) -> float:
        """Calculate filler offset for continuous virtual stream."""
        from datetime import datetime, timezone
        if filler_epoch is None:
            filler_epoch = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        time_diff = (master_clock - filler_epoch).total_seconds()
        return time_diff % filler_duration_seconds

    def _determine_active_content(
        self,
        now: "datetime",
        block_start: "datetime",
        program_duration_seconds: float,
    ) -> tuple[str, str, float]:
        """Determine which content is active (program or filler) and calculate join offset."""
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
            # Log for debugging "who" was counted as a viewer (e.g. phantom vs real TS client).
            self._emit_lifecycle_event(
                "viewer_join",
                event_scope="session",
                session_id=session_id,
                viewer_count=self.runtime_state.viewer_count,
            )
            self._logger.info(
                "[viewer_join] channel=%s session_id=%s viewer_count=%d",
                self.channel_id, session_id, self.runtime_state.viewer_count,
            )

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
                self.on_first_viewer(trigger_session_id=session_id)

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
            # Log for debugging "who" was counted as a viewer when they left.
            self._emit_lifecycle_event(
                "viewer_leave",
                event_scope="session",
                session_id=session_id,
                viewer_count=self.runtime_state.viewer_count,
            )
            self._logger.info(
                "[viewer_leave] channel=%s session_id=%s viewer_count=%d (was %d)",
                self.channel_id, session_id, self.runtime_state.viewer_count, old_count,
            )

            # Fanout rule: last viewer stops Producer.
            # INV-VIEWER-LIFECYCLE-002: AIR stops exactly once on 1→0 transition
            if old_count == 1 and self.runtime_state.viewer_count == 0:
                self._logger.info(
                    "INV-VIEWER-LIFECYCLE-002: Last viewer left channel %s, stopping AIR",
                    self.channel_id
                )
                self.on_last_viewer(trigger_session_id=session_id)

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

    def on_first_viewer(self, trigger_session_id: str | None = None) -> None:
        """
        Phase 0 contract: Called when the first viewer connects (viewer count goes 0 -> 1).

        This ensures the Producer is started when the first viewer arrives.
        """
        if self.runtime_state.viewer_count == 0:
            return  # Not actually first viewer

        # Store trigger_session_id for channel_activated event in _ensure_producer_running
        self._trigger_session_id = trigger_session_id
        # Ensure producer is running for first viewer
        if self.runtime_state.viewer_count == 1:
            self._ensure_producer_running()

    def on_last_viewer(self, trigger_session_id: str | None = None) -> None:
        """
        Phase 0 contract: Called when the last viewer disconnects (viewer count goes 1 -> 0).

        Starts a linger grace period instead of immediately stopping the producer.
        If no viewer reconnects within LINGER_SECONDS, the producer is stopped.
        """
        if self.runtime_state.viewer_count != 0:
            return  # Not actually last viewer
        self._start_linger(trigger_session_id=trigger_session_id)

    def _start_linger(self, trigger_session_id: str | None = None) -> None:
        """Start linger grace period. Producer stays alive until timeout."""
        if self._linger_handle is not None:
            return  # already lingering
        linger_fields: dict[str, object] = {
            "linger_seconds": self.LINGER_SECONDS,
            "viewer_count": self.runtime_state.viewer_count,
        }
        if trigger_session_id is not None:
            linger_fields["trigger_session_id"] = trigger_session_id
        self._emit_lifecycle_event("linger_start", event_scope="channel", **linger_fields)
        self._logger.debug(
            "[channel %s] LINGER_STARTED %ds", self.channel_id, self.LINGER_SECONDS
        )
        if self._loop is not None:
            self._linger_deadline = self._loop.time() + self.LINGER_SECONDS
            self._linger_handle = self._loop.call_later(
                self.LINGER_SECONDS, self._linger_expire
            )
        else:
            # No event loop — do full teardown immediately (same as _linger_expire)
            # so producer.stop() runs and AIR process is terminated.
            self._logger.info(
                "[channel %s] LINGER_SKIP (no event loop); stopping producer and tearing down",
                self.channel_id,
            )
            self.on_linger_expired()

    def _linger_expire(self) -> None:
        """Linger timer fired. If still no viewers, stop producer and tear down (AIR exits after linger)."""
        self._linger_handle = None
        self._linger_deadline = None
        if self.runtime_state.viewer_count == 0:
            self._emit_lifecycle_event("linger_expire", event_scope="channel", viewer_count=0)
            self._logger.info(
                "[channel %s] LINGER_EXPIRED (0 viewers); stopping producer and tearing down",
                self.channel_id,
            )
            # Full teardown: notify ProgramDirector so channel is removed and AIR is stopped.
            # Pass reason so AIR logs "last_viewer_left" only when stop was due to viewer leave.
            self.on_linger_expired()

    def _cancel_linger(self) -> None:
        """Cancel any pending linger timer."""
        if self._linger_handle is not None:
            self._linger_handle.cancel()
            self._linger_handle = None
            self._linger_deadline = None
            self._emit_lifecycle_event("linger_cancel", event_scope="channel", viewer_count=self.runtime_state.viewer_count)
            self._logger.info(
                "[channel %s] LINGER_CANCELLED viewer_reconnected", self.channel_id
            )

    def _on_producer_session_end(self, reason: str) -> None:
        """INV-CHANNEL-LIVENESS-RECOVERY-001: Handle producer failure.
        ChannelManager owns the liveness recovery decision."""
        if reason not in ("stopped", "error"):
            return  # Not recoverable (last_viewer_left, lookahead_exhausted)

        viewer_count = self.runtime_state.viewer_count
        if viewer_count == 0:
            return  # No viewers to serve

        self._recovery_attempts += 1
        if self._recovery_attempts > self._RECOVERY_MAX_ATTEMPTS:
            self._logger.error(
                "INV-CHANNEL-LIVENESS-RECOVERY-001: Channel %s: "
                "max recovery attempts (%d) exceeded; entering error state",
                self.channel_id, self._RECOVERY_MAX_ATTEMPTS,
            )
            return

        # Idempotent: cancel any existing recovery timer
        if self._recovery_timer is not None:
            self._recovery_timer.cancel()
            self._recovery_timer = None

        delay = min(
            self._RECOVERY_BASE_DELAY_S * (2 ** (self._recovery_attempts - 1)),
            30.0,
        )
        self._logger.warning(
            "INV-CHANNEL-LIVENESS-RECOVERY-001: Channel %s: "
            "scheduling recovery attempt %d/%d in %.1fs "
            "(reason=%s, viewers=%d)",
            self.channel_id, self._recovery_attempts,
            self._RECOVERY_MAX_ATTEMPTS, delay, reason, viewer_count,
        )

        self._recovery_timer = threading.Timer(delay, self._attempt_recovery)
        self._recovery_timer.daemon = True
        self._recovery_timer.start()

    def _attempt_recovery(self) -> None:
        """INV-CHANNEL-LIVENESS-RECOVERY-001: Execute deferred recovery."""
        self._recovery_timer = None  # Timer fired, clear reference

        if self.runtime_state.viewer_count == 0:
            self._recovery_attempts = 0
            return  # Viewers left during backoff

        # INV-HLS-RESTART-DISCONTINUITY-001: Reset segmenter before producer restart
        self._update_hls_segment_counter()
        self._reset_hls_segmenter_for_restart()

        try:
            self._ensure_producer_running()
        except Exception as e:
            self._logger.error(
                "INV-CHANNEL-LIVENESS-RECOVERY-001: Channel %s: "
                "recovery attempt %d failed: %s",
                self.channel_id, self._recovery_attempts, e,
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
        self._logger.debug(
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
        activated_fields: dict[str, object] = {
            "mode": required_mode,
            "viewer_count": self.runtime_state.viewer_count,
            "jip_offset_ms": jip_offset_ms,
        }
        trigger_sid = getattr(self, "_trigger_session_id", None)
        if trigger_sid is not None:
            activated_fields["trigger_session_id"] = trigger_sid
        self._emit_lifecycle_event(
            "channel_activated",
            event_scope="channel",
            **activated_fields,
        )
        self.runtime_state.producer_status = "running"
        self.runtime_state.producer_started_at = station_time
        self.runtime_state.stream_endpoint = self.active_producer.get_stream_endpoint()

        # INV-CHANNEL-LIVENESS-RECOVERY-001: Reset recovery budget on successful start
        self._recovery_attempts = 0

        # P12-CORE-010 INV-SESSION-CREATION-UNGATED-001: Session created for viewer.
        self._logger.debug(
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
                self._logger.debug(
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
        # Keep upstream (AIR) running even with zero viewers so VLC reconnect does not restart AIR.
        viewer_count = len(self.viewer_sessions)
        self.runtime_state.viewer_count = viewer_count
        if viewer_count == 0 and self._linger_handle is None:
            # Do NOT stop producer when 0 viewers; upstream stays connected for reconnect.
            if self._channel_state == "STOPPED":
                return
            self._check_teardown_completion()
            if self.active_producer is None:
                return
            # Fall through to update producer health (keep channel RUNNING)
        if self._channel_state == "STOPPED":
            return
        self._check_teardown_completion()

        # Snapshot to avoid TOCTOU race — another thread may clear active_producer
        # between the None check and the method calls.
        producer = self.active_producer
        if producer is None:
            self.runtime_state.producer_status = "stopped"
            self.runtime_state.last_health = "stopped"
            return

        health_status = producer.health()
        producer_state: ProducerState = producer.get_state()

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
            self._logger.debug(
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

        # INV-TEARDOWN-AIR-REAP-001: Always stop the producer before dropping
        # the reference, regardless of graceful vs timeout completion.
        # Without this, the AIR subprocess is orphaned as a zombie.
        if producer:
            producer.stop(reason=getattr(self, "_stop_reason", None) or reason or "channel_stop")

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
        self._logger.debug(
            "Channel %s: Building BlockPlanProducer (mode=%s)",
            self.channel_id, mode,
        )
        producer = BlockPlanProducer(
            channel_id=self.channel_id,
            configuration={},
            channel_config=self._get_channel_config(),
            schedule_service=self.schedule_service,
            clock=self.clock,
            evidence_endpoint=self._evidence_endpoint,
            on_producer_failure=self._on_producer_session_end,
        )
        # Wire HLS segmenter for BlockPlan timebase updates
        producer._hls_segmenter_ref = self._hls_segmenter
        return producer

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


class TracedSocket:
    """Diagnostic proxy: intercepts close/shutdown with stack traces.

    Wraps an accepted ``socket.socket`` so that every close/shutdown is
    logged with the full Python stack trace.  Also installs a weak-reference
    callback on the underlying socket to detect unexpected GC collection
    (which would silently close the fd and cause an EPIPE on the AIR side).

    All other attribute access is delegated transparently via ``__getattr__``.
    """

    def __init__(
        self,
        sock: socket.socket,
        channel_id: str,
        accept_generation: int,
        logger: logging.Logger,
    ):
        self._sock = sock
        self._fd = sock.fileno()
        self._channel_id = channel_id
        self._generation = accept_generation
        self._logger = logger
        # Weak-ref finalizer fires when the real socket is GC'd without an
        # explicit close() call — indicates an unexpected socket lifecycle.
        # Stored so close() can cancel it: an explicit close is expected and
        # must not trigger the GC warning.
        self._finalizer = weakref.finalize(sock, self._on_gc)

    def _on_gc(self) -> None:
        self._logger.warning(
            "INV-UDS-GC: channel=%s fd=%d gen=%d socket GC'd",
            self._channel_id,
            self._fd,
            self._generation,
        )

    def close(self) -> None:
        # Cancel the GC finalizer — an explicit close is expected, not a leak.
        self._finalizer.detach()
        self._logger.debug(
            "INV-UDS-CLOSE-TRACE: channel=%s fd=%d gen=%d",
            self._channel_id,
            self._fd,
            self._generation,
        )
        self._sock.close()

    def shutdown(self, how: int) -> None:
        self._logger.debug(
            "INV-UDS-SHUTDOWN-TRACE: channel=%s fd=%d gen=%d how=%s",
            self._channel_id,
            self._fd,
            self._generation,
            how,
        )
        self._sock.shutdown(how)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._sock, name)


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
        on_producer_failure: "Callable[[str], None] | None" = None,
    ):
        super().__init__(channel_id, ProducerMode.NORMAL, configuration or {})
        self.channel_config = channel_config if channel_config is not None else MOCK_CHANNEL_CONFIG
        self.schedule_service = schedule_service
        self.clock = clock
        self._evidence_endpoint = evidence_endpoint
        self._on_producer_failure = on_producer_failure

        # PlayoutSession instance (created on start, destroyed on stop)
        self._session: "PlayoutSession | None" = None

        # HLS segmenter reference (set by ChannelManager._build_producer)
        self._hls_segmenter_ref: Any | None = None

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
        # Authoritative metadata for in-flight blocks (start/end wallclock)
        self._in_flight_block_meta: dict[str, tuple[int, int]] = {}

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
        self._accept_generation: int = 0

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
            self._logger.debug(
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
                        self._accept_generation += 1
                        traced = TracedSocket(
                            conn, self.channel_id,
                            self._accept_generation, self._logger,
                        )
                        self._reader_socket_queue.put(traced)
                        self._logger.debug(
                            "FIRST-ON-AIR: Channel %s: AIR connected to UDS socket "
                            "(fd=%d, gen=%d)",
                            self.channel_id, conn.fileno(),
                            self._accept_generation,
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
                    clock=self.clock,
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
                self._in_flight_block_meta.clear()

                # Generate and seed initial 2 blocks
                # INV-JIP-BP-005/006: Only block_a carries JIP offset
                block_a = self._generate_next_block(
                    current_entry, jip_offset_ms=jip_offset_ms,
                    now_utc_ms=join_utc_ms,
                )
                self._advance_cursor(block_a)

                next_entry = self._resolve_plan_for_block()
                if not next_entry:
                    raise RuntimeError("No next block data from schedule service")
                block_b = self._generate_next_block(next_entry)
                self._advance_cursor(block_b)

                if not self._session.seed(block_a, block_b,
                                         join_utc_ms=join_utc_ms,
                                         max_queue_depth=self._queue_depth):
                    raise RuntimeError("PlayoutSession.seed() failed")

                # INV-EXEC-NO-STRUCTURE-001: Canary proof — every session start
                # emits one unambiguous line proving timing came from schedule.
                self._logger.debug(
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
                self._in_flight_block_meta[block_a.block_id] = (block_a.start_utc_ms, block_a.end_utc_ms)
                self._in_flight_block_meta[block_b.block_id] = (block_b.start_utc_ms, block_b.end_utc_ms)

                # INV-HLS-SEGMENT-WALLCLOCK-001: Supply editorial timebase to HLS segmenter
                if self._hls_segmenter_ref is not None:
                    try:
                        self._hls_segmenter_ref.set_blockplan_timebase(
                            start_utc_ms=block_a.start_utc_ms,
                            active_block_start_utc_ms=block_a.start_utc_ms,
                            active_block_end_utc_ms=block_b.end_utc_ms,
                        )
                    except Exception as exc:
                        self._logger.warning(
                            "HLS timebase init failed for channel %s: %s",
                            self.channel_id, exc,
                        )

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

                self._logger.debug(
                    "Channel %s: BlockPlan execution started, seeded 2 blocks",
                    self.channel_id
                )

                # =============================================================
                # ARCHITECTURAL TELEMETRY: One-time per-session declaration
                # =============================================================
                self._logger.debug(
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

    def stop(self, reason: str | None = None) -> bool:
        """
        Stop BlockPlan execution.

        Called by ChannelManager when viewer count goes 1→0 or on explicit channel stop.
        Stops PlayoutSession, terminates AIR, cleans up resources.
        reason is passed to AIR StopBlockPlanSession for accurate logging (e.g. "last_viewer_left"
        only when stop was due to viewer leave; "channel_stop" for admin/explicit stop).

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
            self._stop_reason = reason or getattr(self, "_stop_reason", None) or "channel_stop"
            self._logger.debug(
                "INV-VIEWER-LIFECYCLE-002: Channel %s stopping BlockPlan execution "
                "(stop_count=%d reason=%s)",
                self.channel_id, self._stop_count, self._stop_reason
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
                session_reason = getattr(self, "_stop_reason", None) or "channel_stop"
                self._session.stop(reason=session_reason)
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
        self._in_flight_block_ids.clear()
        self._in_flight_block_meta.clear()
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
            # INV-LOUDNESS-NORMALIZED-001: propagate per-asset loudness gain
            if seg.gain_db != 0.0:
                d["gain_db"] = seg.gain_db
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
        self._logger.debug(
            "INV-EXEC-NO-STRUCTURE-001: block=%s dur=%d start=%d end=%d "
            "segs=%d jip_offset=%d (timing from schedule service)",
            block.block_id, effective_dur, start_ms, end_ms,
            len(plan_segments), jip_offset_ms,
        )

        # INV-BLOCK-SEGMENT-CONSERVATION-001: Stage 5 (feed time) check.
        # Segment ms sum must equal block duration within frame tolerance.
        block_dur_ms = block.end_utc_ms - block.start_utc_ms
        seg_sum_ms = sum(s["segment_duration_ms"] for s in plan_segments)
        frame_delta_ms = seg_sum_ms - block_dur_ms
        if abs(frame_delta_ms) > 40:  # FRAME_TOLERANCE_MS
            self._logger.error(
                "INV-BLOCK-SEGMENT-CONSERVATION-001 VIOLATION block_id=%s "
                "block_duration_ms=%d sum_segment_ms=%d delta_ms=%d "
                "segment_count=%d stage=feed",
                block.block_id, block_dur_ms, seg_sum_ms,
                frame_delta_ms, len(plan_segments),
            )
        else:
            self._logger.debug(
                "INV-BLOCK-SEGMENT-CONSERVATION-001 OK block_id=%s "
                "block_duration_ms=%d sum_segment_ms=%d delta_ms=%d",
                block.block_id, block_dur_ms, seg_sum_ms, frame_delta_ms,
            )

        return block

    def _advance_cursor(self, block: "BlockPlan"):
        """
        Advance block generation cursor after a successful feed.

        INV-FEED-QUEUE-001: Cursor advances ONLY after feed() returns True.
        """
        self._block_index += 1
        self._next_block_start_ms = block.end_utc_ms

    def _try_feed_block(self, block: "BlockPlan") -> FeedResult:
        """
        Attempt to feed a block to AIR.

        INV-FEED-QUEUE-001: Cursor advances only on ACCEPTED.
        INV-FEED-QUEUE-002: Rejected block stored in _pending_block.
        INV-FEED-CREDIT-001: Credits decremented on ACCEPTED, zeroed on QUEUE_FULL.
        """
        if not self._session:
            return FeedResult.ERROR

        result = self._session.feed(block)

        if result == FeedResult.ACCEPTED:
            self._advance_cursor(block)
            self._pending_block = None
            self._feed_credits = max(0, self._feed_credits - 1)
            # INV-AIR-SEGMENT-ID-001: As-run enrichment uses AIR-authoritative
            # fields from the evidence proto (segment_type_name, asset_uri,
            # segment_title).  The DB segment cache (prepopulate_block_segment_cache)
            # is no longer consulted at runtime — removed per cleanup of dead
            # enrichment fallback path.
            # INV-WALLCLOCK-FENCE-002: Track fed block as active
            self._in_flight_block_ids.add(block.block_id)
            self._in_flight_block_meta[block.block_id] = (block.start_utc_ms, block.end_utc_ms)
            # INV-HLS-SEGMENT-WALLCLOCK-001: Update HLS segmenter timebase on block feed
            if self._hls_segmenter_ref is not None:
                try:
                    self._hls_segmenter_ref.set_blockplan_timebase(
                        start_utc_ms=block.start_utc_ms,
                        active_block_start_utc_ms=block.start_utc_ms,
                        active_block_end_utc_ms=block.end_utc_ms,
                    )
                except Exception:
                    pass
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

        now_utc_ms = int(self.clock.now_utc().timestamp() * 1000)

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

            self._logger.debug(
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
        current_utc_ms = int(self.clock.now_utc().timestamp() * 1000)
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
            timestamp_utc_ms=int(self.clock.now_utc().timestamp() * 1000),
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

        INV-CALLBACK-EXCEPTION-SAFETY-001: Exceptions in _feed_ahead MUST NOT
        propagate to the event loop.  Credit bookkeeping completes before the
        feed attempt so the session remains viable even on transient failures.
        """
        with self._lock:
            if self._session_ended or not self._started:
                return

            # Mark that AIR supports BlockStarted events
            self._block_started_supported = True

            # BlockStarted = queue slot consumed → credit += 1
            self._feed_credits = min(self._feed_credits + 1, self._queue_depth)

            # INV-HLS-TIMEBASE-AUTHORITY-001: Advance HLS timebase from
            # authoritative runtime activation (BlockStarted), not feed-only signals.
            if self._hls_segmenter_ref is not None:
                block_meta = self._in_flight_block_meta.get(block_id)
                if block_meta is not None:
                    try:
                        start_utc_ms, end_utc_ms = block_meta
                        self._hls_segmenter_ref.set_blockplan_timebase(
                            start_utc_ms=start_utc_ms,
                            active_block_start_utc_ms=start_utc_ms,
                            active_block_end_utc_ms=end_utc_ms,
                        )
                    except Exception:
                        pass

            # State transition: SEEDED → RUNNING on first BlockStarted
            if self._feed_state == _FeedState.SEEDED:
                self._feed_state = _FeedState.RUNNING
                self._logger.debug(
                    "FEED-AHEAD: SEEDED->RUNNING on BlockStarted(%s) "
                    "runway=%dms",
                    block_id, self._compute_runway_ms(),
                )

            try:
                self._feed_ahead()
            except Exception as exc:
                self._logger.error(
                    "INV-CALLBACK-EXCEPTION-SAFETY-001: _feed_ahead failed "
                    "in on_block_started(%s): %s — credits preserved, "
                    "retry on next tick/event",
                    block_id, exc,
                )

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
            self._in_flight_block_meta.pop(block_id, None)

            self._logger.debug(
                "Channel %s: Block %s completed, feeding next",
                self.channel_id, block_id
            )

            # State transition: SEEDED → RUNNING on first BlockCompleted
            # (fallback if BlockStarted wasn't received first)
            if self._feed_state == _FeedState.SEEDED:
                self._feed_state = _FeedState.RUNNING
                self._logger.debug(
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
            try:
                self._feed_ahead()
            except Exception as exc:
                self._logger.error(
                    "INV-CALLBACK-EXCEPTION-SAFETY-001: _feed_ahead failed "
                    "in on_block_complete(%s): %s — credits preserved, "
                    "retry on next tick/event",
                    block_id, exc,
                )

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

        self._logger.debug(
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

        # INV-CHANNEL-LIVENESS-RECOVERY-001: Signal failure to ChannelManager
        if self._on_producer_failure is not None:
            self._on_producer_failure(reason)

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

