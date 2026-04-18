"""AirBridge — sole owner of one channel's AIR subprocess lifecycle.

Introduced in Phase 1 of the ADR-004 migration (BlockPlanProducer retirement).

AirBridge encapsulates the mechanics of talking to one AIR subprocess:
``launch_air`` to spawn, ``terminate_air`` to stop, and the ``(ProcessHandle,
socket_path, reader_socket_queue, grpc_addr)`` quadruple returned by
``launch_air``. It holds no scheduling, viewer, or HLS state — those belong to
the broker layer above it.

During the migration, ``BlockPlanProducer`` delegates to a per-channel
``AirBridge`` rather than holding the ``ProcessHandle`` itself. In later phases,
the broker role migrates into ``ChannelManager`` directly and BPP retires.
"""

from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path
from typing import Any

from ..usecases.channel_manager_launch import (
    ProcessHandle,
    feed_blockplan,
    iter_blockplan_events,
    launch_air,
    terminate_air,
)
from .config import ChannelConfig
from .schedule_types import ScheduledBlock


class AirBridge:
    """Per-channel owner of the AIR subprocess handle and UDS/gRPC glue.

    Lifecycle:
      - ``spawn(playout_request)`` invokes ``launch_air`` and stores the
        returned handle, socket path, and gRPC address. Idempotent: a second
        call while already spawned returns ``True`` without side effects.
      - ``terminate()`` calls ``terminate_air`` on the stored handle and
        resets internal state. Idempotent: safe to call when not spawned.

    Read-only properties expose ``socket_path``, ``reader_socket_queue``,
    ``grpc_addr``, and ``is_alive`` for downstream components (notably
    ChannelStream's fanout wiring and the BPP driver thread's gRPC event
    subscription).
    """

    def __init__(
        self,
        channel_id: str,
        channel_config: ChannelConfig,
        logger: logging.Logger | None = None,
    ) -> None:
        self.channel_id = channel_id
        self.channel_config = channel_config
        self._logger = logger or logging.getLogger(__name__)

        self._lock = threading.RLock()
        self._process: ProcessHandle | None = None
        self._socket_path: Path | None = None
        self._grpc_addr: str | None = None
        # Pre-allocated so a pre-wired ChannelStream reader can poll the same
        # queue object across spawn/terminate cycles (preserves INV-EARLY-DRAIN).
        self._reader_socket_queue: queue.Queue[Any] = queue.Queue()
        self._spawned = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def spawn(self, playout_request: dict[str, Any]) -> bool:
        """Launch AIR with the given playout request. Returns True on success.

        Reuses the caller-accessible ``reader_socket_queue`` so any pre-wired
        reader is already polling the queue that ``launch_air``'s accept thread
        will post the AIR UDS socket into.
        """
        with self._lock:
            if self._spawned:
                return True

            pre_queue = self._reader_socket_queue
            try:
                proc, socket_path, reader_queue, grpc_addr = launch_air(
                    playout_request=playout_request,
                    channel_config=self.channel_config,
                    reader_socket_queue=pre_queue,
                )
            except Exception as exc:
                self._logger.error(
                    "Channel %s: AirBridge.spawn failed: %s", self.channel_id, exc,
                )
                return False

            # Identity guard preserves INV-EARLY-DRAIN: the queue the caller
            # wired up MUST be the same queue the accept thread posts into.
            assert reader_queue is pre_queue, (
                "launch_air must reuse caller-supplied reader_socket_queue"
            )

            self._process = proc
            self._socket_path = socket_path
            self._grpc_addr = grpc_addr
            self._spawned = True
            self._logger.debug(
                "Channel %s: AirBridge spawned | grpc_addr=%s socket_path=%s",
                self.channel_id, grpc_addr, socket_path,
            )
            return True

    def terminate(self) -> None:
        """Terminate the AIR subprocess and reset state. Idempotent."""
        with self._lock:
            proc = self._process
            was_spawned = self._spawned

        if proc is not None:
            try:
                terminate_air(proc)
            except Exception as exc:
                self._logger.warning(
                    "Channel %s: AirBridge.terminate error: %s",
                    self.channel_id, exc,
                )

        with self._lock:
            self._process = None
            self._socket_path = None
            self._grpc_addr = None
            # Reset the queue so a subsequent spawn starts fresh.
            self._reader_socket_queue = queue.Queue()
            self._spawned = False

        if was_spawned:
            self._logger.debug(
                "Channel %s: AirBridge terminated", self.channel_id,
            )

    # ------------------------------------------------------------------
    # Read-only state
    # ------------------------------------------------------------------

    @property
    def socket_path(self) -> Path | None:
        with self._lock:
            return self._socket_path

    @property
    def reader_socket_queue(self) -> queue.Queue[Any]:
        # Queue itself is thread-safe; return direct reference so downstream
        # readers can poll without reacquiring the bridge's lock.
        return self._reader_socket_queue

    @property
    def grpc_addr(self) -> str | None:
        with self._lock:
            return self._grpc_addr

    @property
    def process(self) -> ProcessHandle | None:
        with self._lock:
            return self._process

    @property
    def is_alive(self) -> bool:
        with self._lock:
            proc = self._process
        if proc is None:
            return False
        return proc.poll() is None

    @property
    def spawned(self) -> bool:
        with self._lock:
            return self._spawned

    # ------------------------------------------------------------------
    # gRPC surface (INV-CM-AIR-GRPC-SOLE-OWNER-001)
    # ------------------------------------------------------------------

    def iter_events(self):
        """Subscribe to the AIR BlockPlan event stream for this channel.

        Yields the events produced by ``iter_blockplan_events``; the caller
        handles each ``BlockStarted`` / ``BlockCompleted`` / ``SessionEnded``.
        Returns without yielding when the bridge is not spawned.
        """
        grpc_addr = self.grpc_addr
        if grpc_addr is None:
            return
        yield from iter_blockplan_events(
            grpc_addr,
            channel_id_int=self.channel_config.channel_id_int,
        )

    def feed(self, block: ScheduledBlock) -> None:
        """Issue a FeedBlockPlan RPC to AIR for ``block``.

        Raises whatever ``feed_blockplan`` raises; the caller is responsible
        for classifying the failure (credit accounting, retry policy, fatal
        surfacing). AirBridge is a pure transport here — no policy.
        """
        grpc_addr = self.grpc_addr
        if grpc_addr is None:
            raise RuntimeError(
                f"AirBridge.feed called on unspawned bridge for {self.channel_id}"
            )
        feed_blockplan(
            grpc_addr,
            channel_id_int=self.channel_config.channel_id_int,
            block=block,
        )
