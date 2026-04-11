"""BlockPlanProducer extracted from channel_manager.py.

INV-PLAYOUT-MODULE-EXTRACTION-001: This class is importable from this
dedicated module. Backward-compatible re-export exists in channel_manager.py.
"""

from __future__ import annotations

import logging
import math
import json
import queue
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

from .clock import MasterClock
from .schedule_types import ScheduledBlock, ScheduledSegment
from .producer.base import Producer, ProducerMode, ProducerStatus, ContentSegment, ProducerState
from .config import (
    ChannelConfig,
    ChannelConfigProvider,
    MOCK_CHANNEL_CONFIG,
)
from .protocols import ScheduleService
from .playout_session import FeedResult
from .cm_helpers import _FeedState, _AsRunAnnotation, TracedSocket
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

if TYPE_CHECKING:
    from .playout_session import PlayoutSession, BlockPlan

# Playout authority constant (canonical source: channel_manager.py, duplicated
# here to avoid circular import between block_plan_producer ↔ channel_manager).
PLAYOUT_AUTHORITY: str = "blockplan"


class BlockPlanProducer(Producer):
    """
    Producer that uses BlockPlan-based execution via PlayoutSession.

    This producer implements the on-demand playout model:
    - AIR starts on first viewer (0 -> 1 transition)
    - AIR stops on last viewer (1 -> 0 transition)
    - No viewer can start/stop AIR directly
    - BlockPlan execution is autonomous (no mid-block Core<->AIR traffic)

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

        Called by ChannelManager.on_first_viewer() when viewer count goes 0->1.
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

        Called by ChannelManager when viewer count goes 1->0 or on explicit channel stop.
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
            from .channel_manager import _apply_jip_to_segments
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
          1. Do NOT reorder blocks -- sequence is sacred (INV-FEED-SEQUENCE).
          2. Do NOT swap to emergency filler -- no reactive substitution.
          3. Continue feeding ahead as normal -- loop proceeds unchanged.
          4. Allow AIR to output black+silence (PADDED_GAP) -- Core does not fight it.
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

        # Credit gate: no slots available -> return immediately.
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
                        "INV-BLOCKPLAN-HORIZON-MISS: No block at %d for channel=%s -- "
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
                # No trigger met -- nothing to feed yet
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
            # DECISION -- the block was prepared on time but delivered
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

            # Block accepted -- reset first-due tracker for next block.
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

        BlockStarted = queue slot consumed -> credit += 1.
        This is the preferred credit signal; BlockCompleted is fallback.
        Also triggers SEEDED->RUNNING transition (earlier than BlockCompleted).

        INV-CALLBACK-EXCEPTION-SAFETY-001: Exceptions in _feed_ahead MUST NOT
        propagate to the event loop.  Credit bookkeeping completes before the
        feed attempt so the session remains viable even on transient failures.
        """
        with self._lock:
            if self._session_ended or not self._started:
                return

            # Mark that AIR supports BlockStarted events
            self._block_started_supported = True

            # BlockStarted = queue slot consumed -> credit += 1
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

            # State transition: SEEDED -> RUNNING on first BlockStarted
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
                    "in on_block_started(%s): %s -- credits preserved, "
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

            # State transition: SEEDED -> RUNNING on first BlockCompleted
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
                    "in on_block_complete(%s): %s -- credits preserved, "
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
