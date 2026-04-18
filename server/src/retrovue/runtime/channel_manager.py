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

from .clock import AuthoritativeClock
from .schedule_types import ScheduledBlock, ScheduledSegment
from .producer.base import Producer, ProducerMode, ProducerStatus, ContentSegment, ProducerState
from .channel_stream import ChannelStream, SocketTsSource, generate_ts_stream
from .air_bridge import AirBridge
from .supply_controller import SupplyController
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
# PLAYOUT AUTHORITY: BlockPlan startup/feed only
# =============================================================================
# The only runtime playout path is BlockPlanProducer driving AIR through
# StartBlockPlanSession + FeedBlockPlan in retrovue.usecases.channel_manager_launch.
# Legacy startup/tune-in choreography (LoadPreview + SwitchToLive) is forbidden.
# =============================================================================
PLAYOUT_AUTHORITY: str = "blockplan"

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

# ----------------------------------------------------------------------
# Protocols — canonical definitions live in retrovue/runtime/protocols.py
# Re-exported here for backward compatibility.
# ----------------------------------------------------------------------
from .protocols import ExecutionRuntimeReader, ProgramDirectorProtocol as ProgramDirector  # noqa: F401


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
    Raised if execution data is missing for "right now".

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
    - Ask ExecutionRuntimeReader what should be airing 'right now', using AuthoritativeClock for authoritative time
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
        clock: AuthoritativeClock,
        execution_reader: ExecutionRuntimeReader | None,
        program_director: ProgramDirector,
        *,
        event_loop: asyncio.AbstractEventLoop | None = None,
        evidence_endpoint: str = "",
        resolved_config: Any = None,
    ):
        """
        Initialize the ChannelManager for a specific channel.

        Args:
            channel_id: Channel this manager controls
            clock: AuthoritativeClock for authoritative time
            execution_reader: ExecutionRuntimeReader for read-only access to execution data
            program_director: ProgramDirector for global policy/mode
            event_loop: Optional event loop for P11F-005; when set, switch issuance uses call_later instead of threading.Timer
            evidence_endpoint: host:port for evidence gRPC, empty = disabled
            resolved_config: Frozen resolved config from config resolver (REQUIRED)

        Phase 8 Step 4: the linger timer lives on ProgramDirector. This
        constructor no longer accepts a linger-seconds value or a
        linger-expired callback; PD owns both.
        """
        if resolved_config is None:
            raise RuntimeError(
                "resolved_config is required for ChannelManager — "
                "fallback defaults are no longer supported"
            )
        self.channel_id = channel_id
        self.clock = clock
        assert self.clock is not None, "ChannelManager requires an AuthoritativeClock"
        self.execution_reader = execution_reader
        self.program_director = program_director
        self._loop: asyncio.AbstractEventLoop | None = event_loop
        self._evidence_endpoint = evidence_endpoint
        # P11F-005: asyncio handle when using event loop (cancel on teardown)
        self._switch_handle: asyncio.TimerHandle | None = None

        # Track active tuning sessions (viewer_id -> session data)
        self.viewer_sessions: dict[str, dict[str, Any]] = {}

        # At most one active producer for this channel.
        # Phase 5C.2: no longer holds a BlockPlanProducer; holds ``self`` while
        # the CM-owned producer is running, ``None`` otherwise
        # (INV-BPP-RETIRED-001). External ``if cm.active_producer:`` guards
        # continue to work; ``cm.is_producer_active()`` is the preferred check.
        self.active_producer = None

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

        # Mock grid configuration (when using mock grid schedule)
        self._mock_grid_block_minutes = _ch["mock_grid_block_minutes"]
        self._mock_grid_program_asset_path: str | None = None  # Set from daemon config
        self._mock_grid_filler_asset_path: str | None = None  # Set from daemon config
        self._mock_grid_filler_epoch: datetime | None = None  # Epoch for filler offset calculation

        # Channel lifecycle: RUNNING (on-air or idle with viewers) or STOPPED (last viewer left).
        # When STOPPED, health/reconnect logic does nothing; ProgramDirector calls stop_channel on last viewer.
        self._channel_state: str = "RUNNING"  # "RUNNING" | "STOPPED"
        # Reason for stop_channel; passed to Producer.stop(reason=...) for accurate teardown logging.
        self._stop_reason: str = "channel_stop"

        # Phase 8 Step 4: linger timer and its deadline moved to
        # ProgramDirector; ChannelManager no longer holds any linger state.
        # Phase 8 Step 5: recovery policy (retry budget, backoff, max
        # attempts) moved to ProgramDirector as well. CM no longer reads
        # the recovery section of resolved_config.

        # INV-VIEWER-LIFECYCLE: Thread-safe viewer count transitions
        self._viewer_lock: threading.Lock = threading.Lock()
        # INV-LIFECYCLE-OBSERVABILITY-001: session that triggered current channel activation
        self._trigger_session_id: str | None = None
        # Phase 8 Step 5: recovery state (attempts counter, retry timer)
        # is owned by ProgramDirector. ChannelManager holds none of it.

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
                clock=self.clock,
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

        reason: Passed to Producer.stop(reason=...) for accurate teardown logging. Use
        "last_viewer_left" only when stopping due to viewer count 1→0; use
        "channel_stop" for admin/explicit stop.
        """
        self._emit_lifecycle_event("teardown", event_scope="channel", reason=reason, viewer_count=self.runtime_state.viewer_count)
        self._logger.debug(
            "[teardown] stopping producer for channel %s (reason=%s)", self.channel_id, reason
        )
        self._stop_reason = reason
        # Phase 8 Step 4: PD cancels the linger timer before this method runs.
        # Phase 8 Step 5: PD also cancels any pending recovery timer in
        # ``_stop_channel_internal`` — CM no longer holds recovery state.
        self._channel_state = "STOPPED"
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

    def viewer_join(
        self, session_id: str, session_info: dict[str, Any]
    ) -> tuple[int, int]:
        """
        Record a viewer starting to watch this channel, and return the
        transition as ``(old_count, new_count)``.

        Phase 8 Step 2: this method is a *pure state update*. It must not
        autonomously dispatch ``on_first_viewer``; ProgramDirector observes
        the returned transition (via ``tune_in`` → ``observe_viewer_transition``)
        and is the sole caller of the lifecycle callback.

        INV-VIEWER-LIFECYCLE-001: Thread-safe viewer count transitions.
        Concurrent viewer joins are serialized via ``_viewer_lock``.

        Linger-state maintenance (cancel an in-flight linger timer and flip
        channel_state back to RUNNING on 0→1) stays inline under the lock in
        this step. Phase 8 Step 4 moves the linger timer itself to PD, at
        which point these lines become PD's responsibility too.
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

            if old_count == 0 and self.runtime_state.viewer_count == 1:
                # Re-enter RUNNING so the producer can restart. Any pending
                # grace-period timer is cancelled by PD (Phase 8 Step 4)
                # before it invokes start_producer.
                self._channel_state = "RUNNING"

            if getattr(self, "_producer_started", False):
                self.runtime_state.stream_endpoint = f"/channel/{self.channel_id}.ts"

            return (old_count, self.runtime_state.viewer_count)

    def viewer_leave(self, session_id: str) -> tuple[int, int]:
        """
        Record a viewer stopping watching, and return the transition as
        ``(old_count, new_count)``.

        Phase 8 Step 2: pure state update. PD observes the transition (via
        ``tune_out``) and dispatches ``on_last_viewer`` if needed.

        INV-VIEWER-LIFECYCLE-002: Thread-safe viewer count transitions.
        """
        with self._viewer_lock:
            if session_id in self.viewer_sessions:
                del self.viewer_sessions[session_id]

            old_count = self.runtime_state.viewer_count
            self.runtime_state.viewer_count = len(self.viewer_sessions)
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

            return (old_count, self.runtime_state.viewer_count)

    # Phase 0 Contract Methods — external entry points.
    # Phase 8 Step 2: tune_in/tune_out update viewer state and then ask
    # ProgramDirector to observe the transition. PD is the sole place that
    # decides whether the transition warrants on_first_viewer / on_last_viewer.
    def tune_in(self, session_id: str, session_info: dict[str, Any] | None = None) -> None:
        """External entry point: a viewer tunes in to this channel."""
        if session_info is None:
            session_info = {}
        old_count, new_count = self.viewer_join(session_id, session_info)
        self.program_director.observe_viewer_transition(
            self, session_id, old_count, new_count
        )

    def tune_out(self, session_id: str) -> None:
        """External entry point: a viewer tunes out from this channel."""
        old_count, new_count = self.viewer_leave(session_id)
        self.program_director.observe_viewer_transition(
            self, session_id, old_count, new_count
        )

    # ------------------------------------------------------------------
    # Phase 8 Step 3 — explicit command surface.
    # ChannelManager is a command executor. ProgramDirector is the sole
    # caller of these commands from viewer-transition dispatch. The old
    # lifecycle-callback names are gone: on_first_viewer was inlined into
    # start_producer (Phase 8 Step 3); the transitional 1→0 method was
    # deleted in Phase 8 Step 4 when the linger timer moved to PD.
    # ------------------------------------------------------------------

    def start_producer(self, *, trigger_session_id: str | None = None) -> None:
        """Idempotent command: ensure the producer is running for this channel.

        Phase 8 Step 3: explicit public command surface, called by
        ProgramDirector on a 0→1 viewer transition (via
        ``observe_viewer_transition``). Reuses the existing
        ``_ensure_producer_running`` body; that method is already idempotent
        (it returns early if the active producer is healthy in the required
        mode).

        If the viewer count is zero (e.g. a race where a viewer_leave fired
        between the transition and this call), skip the start — there is
        nothing to deliver.
        """
        if self.runtime_state.viewer_count == 0:
            return
        self._trigger_session_id = trigger_session_id
        self._ensure_producer_running()

    def stop_producer(self, *, reason: str = "stop_producer_command") -> None:
        """Command: stop the producer for this channel.

        Phase 8 Step 3: thin wrapper over the existing ``stop_channel`` path.
        This is the named command surface ProgramDirector uses for teardown;
        Phase 8 Step 4 routes the linger-expired stop through this method
        (replacing the earlier callback-inversion path on ChannelManager).
        """
        self.stop_channel(reason=reason)

    def clear_active_producer(self) -> None:
        """Command: null the ``active_producer`` reference.

        Phase 9 Step 2: ChannelManager is the sole writer of
        ``active_producer``. ProgramDirector formerly did
        ``manager.active_producer = None`` directly; with this command
        the field stays private to CM. Behavior-preserving: the method
        does only what the bare assignment did.
        """
        self.active_producer = None

    def mark_idle(self) -> None:
        """Command: transition ``_channel_state`` from STOPPED to IDLE.

        Phase 9 Step 3: ChannelManager is the sole writer of
        ``_channel_state``. ProgramDirector formerly flipped the field
        directly under a ``state == "STOPPED"`` guard; the guard moves
        inside this method, so PD calls it unconditionally. Any other
        current state is a silent no-op — preserving the pre-Phase-9
        behavior where PD simply did nothing on non-STOPPED states.
        """
        if self._channel_state == "STOPPED":
            self._channel_state = "IDLE"

    # Phase 8 Step 4: linger scheduling, cancellation, and expiry are all
    # owned by ProgramDirector. See ProgramDirector.observe_viewer_transition
    # and the PD-side timer helpers. On expiry, PD invokes
    # manager.stop_producer(reason="last_viewer_left").

    # Phase 8 Step 5: producer recovery (retry budget, backoff, decision
    # to give up) is ProgramDirector's responsibility. BlockPlanProducer
    # notifies PD directly via the on_producer_failure hook wired at
    # construction time in _build_producer_for_mode — see that method.

    def _ensure_producer_running(self) -> None:
        """Enforce 'channel goes on-air' (BlockPlan path only)."""
        required_mode = self._get_current_mode()

        # If a producer is already running (and healthy), we're done. Mode is
        # implicit (BlockPlan only) after Phase 5C.2.
        if getattr(self, "_producer_started", False) and self._producer_health() == "running":
            return

        # Otherwise we need to (re)start. On restart we also reset the
        # HLS segmenter so the next segment carries discontinuity
        # (INV-HLS-RESTART-DISCONTINUITY-001). Pre-Phase-8-Step-5 this
        # reset was done in the CM-side recovery path; we keep it inline
        # so PD-driven restarts via start_producer preserve the marker.
        if getattr(self, "_producer_started", False):
            self._producer_stop()
            self.active_producer = None
            self._update_hls_segment_counter()
            self._reset_hls_segmenter_for_restart()

        # Phase 5C.2: construct CM's per-channel helpers (AirBridge,
        # SupplyController) and producer-lifecycle state. No BlockPlanProducer
        # instance is created (INV-BPP-RETIRED-001).
        self._build_producer_for_mode(required_mode)

        # Get authoritative station time.
        station_time = self.clock.now_utc()

        # INV-EXEC-NO-BOUNDARY-001: No grid math here.
        # INV-EXEC-NO-STRUCTURE-001: Block timing from execution reader.
        now_utc_ms = int(station_time.timestamp() * 1000)
        if self.execution_reader is None:
            self.runtime_state.producer_status = "error"
            self.active_producer = None
            raise RuntimeError(
                f"ExecutionRuntimeReader not configured for channel {self.channel_id}"
            )

        current_block = self.execution_reader.get_current_execution_block(
            self.channel_id, now_utc_ms
        )
        if not current_block:
            self.runtime_state.producer_status = "error"
            self.active_producer = None
            raise RuntimeError(
                f"Missing current execution block for channel {self.channel_id} at {now_utc_ms}"
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

        # Phase 5C.1: CM owns orchestration start
        # (INV-CM-ORCHESTRATION-SOLE-OWNER-001).
        started_ok = self._producer_start(
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
        self.runtime_state.stream_endpoint = f"/channel/{self.channel_id}.ts"

        # Phase 8 Step 5: recovery-attempt bookkeeping lives on PD. When
        # PD's retry timer fires ``manager.start_producer()`` and this
        # path completes successfully, PD resets its own attempts counter.

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
        return self._producer_started and self.runtime_state.producer_status == "running"

    def is_producer_active(self) -> bool:
        """Post-BPP truthy check replacing ``if manager.active_producer:``.

        Returns True while the CM-owned producer is running
        (INV-BPP-RETIRED-001).
        """
        return getattr(self, "_producer_started", False)

    @property
    def reader_socket_queue(self):
        """Expose the active AirBridge's reader_socket_queue.

        Post-ADR-004 Phase 5C.2, ``active_producer = self`` (CM). The
        TsConsumptionAdapter factory resolves the per-channel UDS reader
        queue via ``active_producer.reader_socket_queue``; this property
        makes CM answer that call by forwarding to the composed AirBridge.
        Returns ``None`` when no producer has been built yet
        (INV-CM-READER-SOCKET-QUEUE-PROXY-001).
        """
        bridge = getattr(self, "_air_bridge", None)
        if bridge is None:
            return None
        return bridge.reader_socket_queue

    def tick(self) -> None:
        """Clock-driven health/state update. CM-as-producer owns startup and
        boundary-driven feeding; tick surfaces any pending fatal error and
        returns early when the channel is stopped."""
        if self._pending_fatal is not None:
            e = self._pending_fatal
            self._pending_fatal = None
            raise e
        if self._channel_state == "STOPPED" or self.active_producer is None:
            return

    def _stop_producer_if_idle(self) -> None:
        """Stop the producer if there are no active viewers.

        Post-ADR-004 Phase 5C.2: teardown is synchronous. ``_producer_stop``
        terminates AIR, joins the driver thread, resets supply state, and
        clears ``active_producer`` in one call. There is no cooperative
        two-phase protocol (INV-CM-TEARDOWN-SYNCHRONOUS-001).
        """
        if self.runtime_state.viewer_count != 0:
            return

        if self.is_producer_active():
            self._producer_stop(
                reason=getattr(self, "_stop_reason", None) or "viewer_inactive",
            )

        self.runtime_state.producer_status = "stopped"
        self.runtime_state.stream_endpoint = None

    def check_health(self) -> None:
        """Poll Producer health and update runtime_state. Includes segment supervisor loop for Phase 0."""
        # Keep upstream (AIR) running even with zero viewers so VLC reconnect does not restart AIR.
        viewer_count = len(self.viewer_sessions)
        self.runtime_state.viewer_count = viewer_count
        if viewer_count == 0 and not self.program_director.is_channel_in_linger(self.channel_id):
            # Do NOT stop producer when 0 viewers; upstream stays connected for reconnect.
            if self._channel_state == "STOPPED":
                return
            if self.active_producer is None:
                return
            # Fall through to update producer health (keep channel RUNNING)
        if self._channel_state == "STOPPED":
            return

        # Phase 5C.2: CM reads its own state; BPP.get_state() retired.
        if not self._producer_started:
            self.runtime_state.producer_status = "stopped"
            self.runtime_state.last_health = "stopped"
            return

        health_status = self._producer_health()
        self.runtime_state.last_health = health_status
        # producer_status / stream_endpoint / producer_started_at are owned
        # by _producer_start / _producer_stop / _producer_fail transitions.
        
    def attach_metrics_publisher(self, publisher: "MetricsPublisher") -> None:
        """Register the metrics publisher responsible for this channel."""
        self._metrics_publisher = publisher

    def get_channel_metrics(self) -> "ChannelMetricsSample | None":
        """Return the latest metrics sample, if publishing is configured."""
        if not self._metrics_publisher:
            return None
        return self._metrics_publisher.get_latest_sample()

    def populate_metrics_sample(self, sample: "ChannelMetricsSample") -> None:
        """Populate the provided sample with the most recent channel state.

        Post-ADR-004 Phase 5C.2, ``active_producer`` is ``self`` (CM).
        Metrics derive from CM-local state, not from BPP-era producer
        methods (INV-CM-METRICS-SAMPLE-CM-SHAPE-001). Segment-progress and
        frame counters were BPP-owned; CM does not track them today, so
        they report as ``None`` / ``0.0`` until a replacement pathway is
        wired through AIR telemetry.
        """
        viewer_count = len(self.viewer_sessions)
        producer_state = self.runtime_state.producer_status or "stopped"
        active = viewer_count > 0 or producer_state == ProducerStatus.RUNNING.value

        sample.channel_state = "active" if active else "idle"
        sample.viewer_count = viewer_count
        sample.producer_state = producer_state
        sample.segment_id = None
        sample.segment_position = 0.0
        sample.dropped_frames = None
        sample.queued_frames = None

    def _station_now(self) -> float:
        """Get current station time as float timestamp."""
        current_time = self.clock.now_utc()
        if hasattr(current_time, "timestamp"):
            return current_time.timestamp()
        return float(current_time)

    def _build_producer_for_mode(self, mode: str) -> None:
        """Construct CM-held per-channel helpers and initialize producer-
        lifecycle state.

        Phase 5C.2 of ADR-004: BlockPlanProducer is retired
        (INV-BPP-RETIRED-001). This method now only sets up the CM-internal
        structures needed by ``_producer_start``:

          * AirBridge  (INV-CM-OWNS-AIR-BRIDGE-001)
          * SupplyController  (INV-CM-OWNS-SUPPLY-CONTROLLER-001)
          * producer-lifecycle state (``_producer_lock``, ``_producer_stop_event``,
            ``_producer_driver_thread``, ``_producer_started``)

        Returns ``None`` — there is no producer object to return.
        """
        if not self._blockplan_mode:
            self._logger.error(
                "Channel %s: _blockplan_mode is False. BlockPlan is the only path.",
                self.channel_id,
            )
            raise RuntimeError(
                f"Channel {self.channel_id}: BlockPlan is the only supported mode. "
                "Call set_blockplan_mode(True) before starting the channel."
            )
        self._logger.debug(
            "Channel %s: Building CM-owned producer helpers (mode=%s)",
            self.channel_id, mode,
        )

        channel_config = self._get_channel_config()
        # Failure callback: reported to PD for recovery-policy decisions.
        on_failure = lambda reason, _cid=self.channel_id: (
            self.program_director.on_producer_failure(_cid, reason)
        )

        self._air_bridge = AirBridge(
            channel_id=self.channel_id,
            channel_config=channel_config,
            logger=self._logger,
        )
        self._supply = SupplyController(
            channel_id=self.channel_id,
            execution_reader=self.execution_reader,
            on_failure=on_failure,
            logger=self._logger,
        )
        self._producer_lock = threading.RLock()
        self._producer_stop_event = threading.Event()
        self._producer_driver_thread = None
        self._producer_started = False

    # ------------------------------------------------------------------
    # Phase 5C.1: CM-owned runtime orchestration
    # (INV-CM-ORCHESTRATION-SOLE-OWNER-001)
    # ------------------------------------------------------------------

    def _producer_start(
        self,
        start_at_station_time,
        *,
        jip_offset_ms: int = 0,
    ) -> bool:
        """Launch AIR via CM's own orchestration path.

        Replaces the prior ``self.active_producer.start(...)`` delegation.
        Uses the CM-held AirBridge + SupplyController directly. Mirrors key
        Producer-base fields onto ``self.active_producer`` so ``get_state()``
        consumers (check_health, is_live) continue to see correct state
        during the Phase 5C.1 transition window.
        """
        with self._producer_lock:
            if self._producer_started:
                return True

            now_utc_ms = int(start_at_station_time.timestamp() * 1000)
            current_block = self._supply.resolve_current(now_utc_ms)
            if current_block is None or not current_block.segments:
                self._logger.error(
                    "Channel %s: cannot start — no current block at %d",
                    self.channel_id, now_utc_ms,
                )
                self.runtime_state.producer_status = "error"
                return False

            if jip_offset_ms < 0:
                self._logger.error(
                    "Channel %s: cannot start — invalid jip_offset_ms=%d",
                    self.channel_id, jip_offset_ms,
                )
                self.runtime_state.producer_status = "error"
                return False

            next_block = self._supply.resolve_next(current_block.end_utc_ms)
            if next_block is None:
                self._logger.error(
                    "Channel %s: cannot start — no next block after %s",
                    self.channel_id, current_block.block_id,
                )
                self.runtime_state.producer_status = "error"
                return False

            if int(current_block.end_utc_ms) != int(next_block.start_utc_ms):
                self._logger.error(
                    "Channel %s: cannot start — non-contiguous startup blocks "
                    "current=%s next=%s",
                    self.channel_id, current_block.block_id, next_block.block_id,
                )
                self.runtime_state.producer_status = "error"
                return False

            active_seg_idx, offset_into_segment_ms = _resolve_jip_position(
                current_block, max(0, int(jip_offset_ms)),
            )

            # INV-HLS-SEGMENT-WALLCLOCK-001: seed the HLS segmenter timebase.
            self._producer_push_hls_timebase(current_block)

            playout_request = {
                "channel_id": self.channel_id,
                "join_utc_ms": now_utc_ms,
                "current_block": current_block,
                "next_block": next_block,
                "evidence_endpoint": self._evidence_endpoint,
            }

            if not self._air_bridge.spawn(playout_request):
                self.runtime_state.producer_status = "error"
                return False

            self._supply.seed(current_block, next_block)

            self._producer_started = True
            self.runtime_state.producer_status = "running"
            self.runtime_state.producer_started_at = start_at_station_time
            self.runtime_state.stream_endpoint = f"/channel/{self.channel_id}.ts"

            # Phase 5C.2: active_producer is set to self (CM) as a truthy
            # marker for legacy ``if cm.active_producer:`` callers
            # (INV-BPP-RETIRED-001). No BlockPlanProducer instance exists.
            self.active_producer = self

            self._producer_stop_event.clear()
            self._producer_driver_thread = threading.Thread(
                target=self._producer_driver_loop,
                name=f"cm-driver-{self.channel_id}",
                daemon=True,
            )
            self._producer_driver_thread.start()

            self._logger.debug(
                "Channel %s: CM producer started | current_block=%s next_block=%s "
                "join_utc_ms=%d grpc_addr=%s socket_path=%s active_seg=%d "
                "offset_into_segment_ms=%d",
                self.channel_id, current_block.block_id, next_block.block_id,
                now_utc_ms, self._air_bridge.grpc_addr,
                self._air_bridge.socket_path, active_seg_idx,
                offset_into_segment_ms,
            )
            return True

    def _producer_stop(self, reason: str | None = None) -> bool:
        """Terminate AIR + stop driver thread; idempotent if not started."""
        if not hasattr(self, "_producer_lock"):
            return True  # Never built — nothing to stop.

        with self._producer_lock:
            if not self._producer_started:
                return True
            self._producer_stop_event.set()
            driver = self._producer_driver_thread

        # Terminate outside the lock so the driver can take the lock to exit.
        self._air_bridge.terminate()

        if driver is not None and driver.is_alive():
            driver.join(timeout=5.0)

        with self._producer_lock:
            self._producer_driver_thread = None
            self._supply.reset()
            self._producer_started = False
            self.runtime_state.producer_status = "stopped"
            self.runtime_state.stream_endpoint = None
            # Phase 5C.2: clear the active_producer marker.
            self.active_producer = None

        self._logger.debug(
            "Channel %s: CM producer stopped (reason=%s)", self.channel_id, reason,
        )
        return True

    def _producer_health(self) -> str:
        """Health projection: 'stopped' | 'running' | 'degraded'."""
        if not hasattr(self, "_producer_lock"):
            return "stopped"
        with self._producer_lock:
            if not self._producer_started:
                return "stopped"
            if self.runtime_state.producer_status == "error":
                return "degraded"
        if not self._air_bridge.is_alive:
            return "degraded"
        return "running"

    def _producer_driver_loop(self) -> None:
        """Subscribe to AIR block events and feed the next scheduled block."""
        try:
            with self._producer_lock:
                started = self._producer_started
            if not started or self._air_bridge.grpc_addr is None:
                return

            for event in self._air_bridge.iter_events():
                if self._producer_stop_event.is_set():
                    return

                which = event.WhichOneof("event")
                if which == "block_started":
                    self._logger.debug(
                        "Channel %s: AIR block started %s",
                        self.channel_id, event.block_started.block_id,
                    )
                    continue

                if which == "session_ended":
                    self._logger.error(
                        "Channel %s: AIR session ended reason=%s",
                        self.channel_id, event.session_ended.reason,
                    )
                    self._producer_fail("session_ended")
                    return

                if which != "block_completed":
                    continue

                completed = event.block_completed
                next_block = self._supply.resolve_next(
                    int(completed.block_end_utc_ms),
                )
                if next_block is None:
                    self._producer_fail("lookahead_exhausted")
                    return

                if self._supply.is_duplicate_feed(next_block):
                    continue

                try:
                    self._air_bridge.feed(next_block)
                except Exception as exc:
                    self._logger.error(
                        "Channel %s: FeedBlockPlan failed after %s: %s",
                        self.channel_id, completed.block_id, exc,
                    )
                    self._producer_fail("feed_block_error")
                    return

                self._supply.mark_fed(next_block)
                with self._producer_lock:
                    self._producer_push_hls_timebase(next_block)

        except Exception as exc:  # pragma: no cover — defensive
            self._logger.error(
                "Channel %s: driver thread crashed: %s", self.channel_id, exc,
            )
            self._producer_fail("driver_crash")

    def _producer_fail(self, reason: str) -> None:
        """Mark the producer failed; delegate log + callback to SupplyController."""
        self.runtime_state.producer_status = "error"
        self._supply.fail(reason)

    def _producer_push_hls_timebase(self, block) -> None:
        """INV-HLS-SEGMENT-WALLCLOCK-001: feed editorial timebase to HLS."""
        ref = self._hls_segmenter
        if ref is None:
            return
        try:
            ref.set_blockplan_timebase(
                start_utc_ms=block.start_utc_ms,
                active_block_start_utc_ms=block.start_utc_ms,
                active_block_end_utc_ms=block.end_utc_ms,
            )
        except Exception:
            # HLS timebase is observability — a failure here must not stop playback.
            pass

    # ------------------------------------------------------------------
    # Phase 5C.1 public narrow API — replaces PD's
    # ``manager.active_producer.stop(...)`` pattern
    # (INV-CM-ORCHESTRATION-SOLE-OWNER-001).
    # ------------------------------------------------------------------

    def halt_producer(self, *, reason: str | None = None) -> None:
        """Halt the AIR subprocess without triggering channel-wide teardown.

        Narrow counterpart to ``stop_producer`` (which goes through
        ``stop_channel`` for full teardown). PD uses this in its shutdown
        paths that own the channel teardown sequence themselves.
        """
        self._producer_stop(reason=reason)

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


# INV-PLAYOUT-MODULE-EXTRACTION-001: Helper classes extracted to cm_helpers.py.
# Re-exported here for backward compatibility.
from .cm_helpers import _FeedState, _AsRunAnnotation, TracedSocket  # noqa: F401


# Phase 5C.2: BlockPlanProducer module retired (INV-BPP-RETIRED-001).
# ``_resolve_jip_position`` is defined below as a module-level helper; its
# former home (block_plan_producer.py) is deleted.


def _resolve_jip_position(block, jip_offset_ms: int) -> tuple[int, int]:
    """Return ``(active_seg_idx, offset_into_segment_ms)`` for a JIP join.

    Walks the segments, skipping fully elapsed ones. Clamps to the last
    segment if ``jip_offset_ms`` exceeds the block.
    """
    remaining = max(0, int(jip_offset_ms))
    for i, seg in enumerate(block.segments):
        dur = int(seg.segment_duration_ms)
        if remaining < dur:
            return (i, remaining)
        remaining -= dur
    # jip past end of block — clamp to last segment
    last = len(block.segments) - 1
    return (last, 0)
