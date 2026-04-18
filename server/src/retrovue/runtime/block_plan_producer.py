"""BlockPlanProducer — deterministic Core→AIR contract driver.

Launches AIR with the current and next scheduled blocks via
`StartBlockPlanSession`, then feeds additional blocks with `FeedBlockPlan`
when AIR emits boundary events. Core owns the schedule and join epoch;
AIR owns execution, fences, cadence, and fallback.
"""

from __future__ import annotations

import logging
import queue
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .clock import AuthoritativeClock
from .schedule_types import ScheduledBlock
from .producer.base import Producer, ProducerMode, ProducerStatus
from .config import ChannelConfig, MOCK_CHANNEL_CONFIG
from .protocols import ExecutionRuntimeReader
from ..usecases.channel_manager_launch import (
    launch_air,
    feed_blockplan,
    iter_blockplan_events,
    terminate_air,
    ProcessHandle,
)

# Legacy constant kept for INV-PLAYOUT-AUTHORITY log lines elsewhere.
PLAYOUT_AUTHORITY: str = "blockplan"

class BlockPlanProducer(Producer):
    """Per-channel producer that drives AIR through BlockPlan RPCs.

    Lifecycle:
      - ``start(station_time, jip_offset_ms=)`` launches AIR via
        ``launch_air`` with ``join_utc_ms`` plus the current/next scheduled
        blocks. AIR begins execution from that authoritative payload.
      - The driver thread subscribes to AIR block events; on each
        ``BlockCompleted`` it resolves the next block from the execution
        reader and sends exactly one ``FeedBlockPlan``.
      - ``stop(reason=)`` signals the driver to exit, joins it, and calls
        ``terminate_air(process)``.

    Compatibility surface preserved for ChannelManager:
      - ``socket_path`` / ``reader_socket_queue`` properties for
        ChannelStream fanout wiring.
      - ``_hls_segmenter_ref`` attribute for INV-HLS-SEGMENT-WALLCLOCK-001
        timebase updates (set by ChannelManager._build_producer_for_mode).
      - ``get_stream_endpoint`` / ``health`` / ``status`` / ``mode`` /
        ``on_paced_tick`` from the ``Producer`` base contract.
    """

    def __init__(
        self,
        channel_id: str,
        clock: AuthoritativeClock,
        configuration: dict[str, Any] | None = None,
        channel_config: ChannelConfig | None = None,
        execution_reader: ExecutionRuntimeReader | None = None,
        evidence_endpoint: str = "",
        on_producer_failure: Callable[[str], None] | None = None,
    ):
        super().__init__(channel_id, ProducerMode.NORMAL, configuration or {})
        self.channel_config = channel_config or MOCK_CHANNEL_CONFIG
        self.execution_reader = execution_reader
        self.clock = clock
        self._evidence_endpoint = evidence_endpoint  # preserved for ctor compat
        self._on_producer_failure = on_producer_failure

        # HLS segmenter reference (wired by ChannelManager after construction).
        self._hls_segmenter_ref: Any | None = None

        self._lock = threading.RLock()
        self._started = False
        self._stop_event = threading.Event()

        # AIR handles (populated by launch_air in start()).
        self._air_process: ProcessHandle | None = None
        self._air_socket_path: Path | None = None
        self._reader_socket_queue: queue.Queue[Any] = queue.Queue()
        self._air_grpc_addr: str | None = None

        # Driver thread + block cursor.
        self._driver_thread: threading.Thread | None = None
        self._current_block: ScheduledBlock | None = None
        self._last_fed_block_id: str | None = None

        self._stream_endpoint = f"/channel/{channel_id}.ts"

    # ------------------------------------------------------------------
    # Producer contract
    # ------------------------------------------------------------------

    def start(
        self,
        start_at_station_time: datetime,
        *,
        jip_offset_ms: int = 0,
    ) -> bool:
        """Launch AIR with current/next blocks, then begin boundary-driven feeding."""
        with self._lock:
            if self._started:
                return True  # idempotent

            if self.execution_reader is None:
                self._logger.error(
                    "Channel %s: cannot start — no execution_reader", self.channel_id,
                )
                self.status = ProducerStatus.ERROR
                return False

            now_utc_ms = int(start_at_station_time.timestamp() * 1000)
            current_block = self.execution_reader.get_current_execution_block(
                self.channel_id, now_utc_ms,
            )
            if current_block is None or not current_block.segments:
                self._logger.error(
                    "Channel %s: cannot start — no current block at %d",
                    self.channel_id, now_utc_ms,
                )
                self.status = ProducerStatus.ERROR
                return False

            if jip_offset_ms < 0:
                self._logger.error(
                    "Channel %s: cannot start — invalid jip_offset_ms=%d",
                    self.channel_id, jip_offset_ms,
                )
                self.status = ProducerStatus.ERROR
                return False

            next_block = self._resolve_next_block(current_block.end_utc_ms)
            if next_block is None:
                self._logger.error(
                    "Channel %s: cannot start — no next block after %s",
                    self.channel_id, current_block.block_id,
                )
                self.status = ProducerStatus.ERROR
                return False

            if int(current_block.end_utc_ms) != int(next_block.start_utc_ms):
                self._logger.error(
                    "Channel %s: cannot start — non-contiguous startup blocks current=%s next=%s",
                    self.channel_id, current_block.block_id, next_block.block_id,
                )
                self.status = ProducerStatus.ERROR
                return False

            active_seg_idx, offset_into_segment_ms = _resolve_jip_position(
                current_block, max(0, int(jip_offset_ms)),
            )

            # INV-HLS-SEGMENT-WALLCLOCK-001: seed the HLS segmenter timebase.
            self._push_hls_timebase(current_block)

            playout_request: dict[str, Any] = {
                "channel_id": self.channel_id,
                "join_utc_ms": now_utc_ms,
                "current_block": current_block,
                "next_block": next_block,
                "evidence_endpoint": self._evidence_endpoint,
            }

            # INV-EARLY-DRAIN: pass our own reader_socket_queue into
            # launch_air so the queue object the pre-wired ChannelStream
            # reader is already polling (via
            # ``manager.active_producer.reader_socket_queue``) is the *same*
            # queue the accept thread lands the AIR UDS socket in.  Without
            # this, launch_air would create a fresh queue internally and
            # BPP would only swap it in *after* launch_air returns — by
            # which time AIR's SocketSink may already have overflowed before
            # the pre-wired reader begins draining the attached stream.
            pre_queue = self._reader_socket_queue
            try:
                proc, socket_path, reader_queue, grpc_addr = launch_air(
                    playout_request=playout_request,
                    channel_config=self.channel_config,
                    reader_socket_queue=pre_queue,
                )
            except Exception as exc:
                self._logger.error(
                    "Channel %s: launch_air failed: %s", self.channel_id, exc,
                )
                self.status = ProducerStatus.ERROR
                return False

            self._air_process = proc
            self._air_socket_path = socket_path
            # reader_queue is guaranteed to be `pre_queue` (same object) —
            # assert the identity invariant so a refactor cannot silently
            # reintroduce the two-queue split that caused the orphan window.
            assert reader_queue is pre_queue, (
                "launch_air must reuse the caller-supplied reader_socket_queue "
                "to preserve INV-EARLY-DRAIN"
            )
            self._reader_socket_queue = reader_queue
            self._air_grpc_addr = grpc_addr
            self._current_block = current_block
            self._last_fed_block_id = next_block.block_id

            self._started = True
            self.status = ProducerStatus.RUNNING
            self.started_at = start_at_station_time
            self.output_url = self._stream_endpoint

            self._stop_event.clear()
            self._driver_thread = threading.Thread(
                target=self._driver_loop,
                name=f"bpp-driver-{self.channel_id}",
                daemon=True,
            )
            self._driver_thread.start()

            self._logger.debug(
                "Channel %s: BPP started | current_block=%s next_block=%s "
                "join_utc_ms=%d grpc_addr=%s socket_path=%s active_seg=%d "
                "offset_into_segment_ms=%d",
                self.channel_id, current_block.block_id, next_block.block_id,
                now_utc_ms, grpc_addr, socket_path, active_seg_idx,
                offset_into_segment_ms,
            )
            return True

    def stop(self, reason: str | None = None) -> bool:
        """Signal the driver to exit, terminate AIR, clear all state."""
        with self._lock:
            if not self._started:
                return True  # idempotent

            self._stop_event.set()
            driver = self._driver_thread
            proc = self._air_process

        if proc is not None:
            try:
                terminate_air(proc)
            except Exception as exc:
                self._logger.warning(
                    "Channel %s: terminate_air error: %s", self.channel_id, exc,
                )

        # Join outside the lock so the driver can take the lock to exit.
        if driver is not None and driver.is_alive():
            driver.join(timeout=5.0)

        with self._lock:
            self._air_process = None
            self._air_socket_path = None
            self._air_grpc_addr = None
            self._reader_socket_queue = queue.Queue()
            self._driver_thread = None
            self._current_block = None
            self._last_fed_block_id = None

            self._started = False
            self.status = ProducerStatus.STOPPED
            self.output_url = None
            self._teardown_cleanup()
            self._logger.debug(
                "Channel %s: BPP stopped (reason=%s)", self.channel_id, reason,
            )
            return True

    def health(self) -> str:
        with self._lock:
            if not self._started:
                return "stopped"
            if self.status == ProducerStatus.ERROR:
                return "degraded"
            proc = self._air_process
            if proc is None or proc.poll() is not None:
                return "degraded"
            return "running"

    def get_producer_id(self) -> str:
        return f"blockplan_{self.channel_id}"

    def get_stream_endpoint(self) -> str | None:
        return self.output_url

    def on_paced_tick(self, t_now: float, dt: float) -> None:
        # Playback timing lives in the driver thread; the paced tick only
        # advances graceful teardown bookkeeping from the base class.
        self._advance_teardown(dt)

    # ------------------------------------------------------------------
    # Fanout-wiring compatibility (ChannelStream / PD registry)
    # ------------------------------------------------------------------

    def get_socket_path(self) -> Path | None:
        with self._lock:
            return self._air_socket_path

    @property
    def socket_path(self) -> Path | None:
        return self._air_socket_path

    @property
    def reader_socket_queue(self) -> queue.Queue[Any]:
        return self._reader_socket_queue

    # ------------------------------------------------------------------
    # Driver thread
    # ------------------------------------------------------------------

    def _driver_loop(self) -> None:
        """Subscribe to AIR block events and feed the next scheduled block."""
        try:
            with self._lock:
                grpc_addr = self._air_grpc_addr
                started = self._started
            if not started or grpc_addr is None:
                return

            channel_id_int = self.channel_config.channel_id_int
            for event in iter_blockplan_events(
                grpc_addr,
                channel_id_int=channel_id_int,
            ):
                if self._stop_event.is_set():
                    return

                which = event.WhichOneof("event")
                if which == "block_started":
                    started_block = event.block_started
                    self._logger.debug(
                        "Channel %s: AIR block started %s",
                        self.channel_id, started_block.block_id,
                    )
                    continue

                if which == "session_ended":
                    self._logger.error(
                        "Channel %s: AIR session ended reason=%s",
                        self.channel_id, event.session_ended.reason,
                    )
                    self._fail("session_ended")
                    return

                if which != "block_completed":
                    continue

                completed = event.block_completed
                next_block = self._resolve_next_block(int(completed.block_end_utc_ms))
                if next_block is None:
                    self._fail("lookahead_exhausted")
                    return

                last_fed = self._last_fed_block_id
                if last_fed == next_block.block_id:
                    continue

                try:
                    feed_blockplan(
                        grpc_addr,
                        channel_id_int=channel_id_int,
                        block=next_block,
                    )
                except Exception as exc:
                    self._logger.error(
                        "Channel %s: FeedBlockPlan failed after %s: %s",
                        self.channel_id, completed.block_id, exc,
                    )
                    self._fail("feed_block_error")
                    return

                with self._lock:
                    self._current_block = next_block
                    self._last_fed_block_id = next_block.block_id
                    self._push_hls_timebase(next_block)

        except Exception as exc:  # pragma: no cover — defensive
            self._logger.error(
                "Channel %s: driver thread crashed: %s", self.channel_id, exc,
            )
            self._fail("driver_crash")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_next_block(self, after_utc_ms: int) -> ScheduledBlock | None:
        if self.execution_reader is None:
            return None
        return self.execution_reader.get_next_execution_block(
            self.channel_id, after_utc_ms,
        )

    def _push_hls_timebase(self, block: ScheduledBlock) -> None:
        """INV-HLS-SEGMENT-WALLCLOCK-001: feed editorial timebase to HLS."""
        ref = self._hls_segmenter_ref
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

    def _fail(self, reason: str) -> None:
        """Mark the producer failed and notify PD."""
        self._logger.error(
            "Channel %s: producer failure reason=%s", self.channel_id, reason,
        )
        self.status = ProducerStatus.ERROR
        cb = self._on_producer_failure
        if cb is not None:
            try:
                cb(reason)
            except Exception as exc:  # pragma: no cover — defensive
                self._logger.warning(
                    "Channel %s: on_producer_failure raised: %s",
                    self.channel_id, exc,
                )


def _resolve_jip_position(
    block: ScheduledBlock, jip_offset_ms: int,
) -> tuple[int, int]:
    """Return ``(active_seg_idx, offset_into_segment_ms)`` for a JIP join.

    Walks the segments, skipping fully elapsed ones.  Clamps to the last
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
