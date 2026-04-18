"""SupplyController — sole owner of per-channel supply bookkeeping.

Introduced in Phase 3A of the ADR-004 migration (BlockPlanProducer retirement).

SupplyController owns the supply cursor (``current_block``) and
feed-deduplication state (``last_fed_block_id``). It holds no scheduling,
viewer, or AIR-transport state. Block resolution via ``ExecutionRuntimeReader``
and failure surfacing remain outside SupplyController; those move in Phase 3B.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

from .protocols import ExecutionRuntimeReader
from .schedule_types import ScheduledBlock


class SupplyController:
    """Per-channel supply-state owner.

    Tracks the block currently airing and the last block fed to AIR.
    Provides a duplicate-feed guard to prevent the same ``block_id`` being
    fed twice within one session. Resolves the current / next blocks via
    the injected ``ExecutionRuntimeReader`` and routes failure surfacing
    through the injected ``on_failure`` callback.

    Scope (after Phase 3B):
      - OWNS: ``current_block`` cursor, ``last_fed_block_id`` dedup state,
        block resolution via ``ExecutionRuntimeReader``, failure logging
        and ``on_producer_failure`` callback dispatch.
      - DOES NOT OWN: AIR transport (lives on AirBridge), ``ProducerStatus``
        transitions (stay on BlockPlanProducer as part of the Producer
        base-class contract), credit accounting (future).
    """

    def __init__(
        self,
        channel_id: str,
        execution_reader: ExecutionRuntimeReader | None = None,
        on_failure: Callable[[str], None] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.channel_id = channel_id
        self._execution_reader = execution_reader
        self._on_failure = on_failure
        self._logger = logger or logging.getLogger(__name__)
        self._lock = threading.RLock()
        self._current_block: ScheduledBlock | None = None
        self._last_fed_block_id: str | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def seed(
        self,
        current_block: ScheduledBlock,
        next_block: ScheduledBlock,
    ) -> None:
        """Record the seed pair at session start.

        The ``current_block`` is what AIR is now airing; the ``next_block``
        has already been fed to AIR as part of the startup session RPC, so
        it becomes the ``last_fed_block_id``.
        """
        with self._lock:
            self._current_block = current_block
            self._last_fed_block_id = next_block.block_id

    def mark_fed(self, block: ScheduledBlock) -> None:
        """Advance the cursor: ``block`` is now the latest fed block."""
        with self._lock:
            self._current_block = block
            self._last_fed_block_id = block.block_id

    def is_duplicate_feed(self, block: ScheduledBlock) -> bool:
        """True if ``block.block_id`` was the last block fed.

        Used by the driver loop to skip a ``BlockCompleted`` → resolve-next
        round-trip when AIR's reported next block matches what Core already
        sent (prevents double-feed).
        """
        with self._lock:
            return self._last_fed_block_id == block.block_id

    def reset(self) -> None:
        """Clear supply state. Called on session teardown."""
        with self._lock:
            self._current_block = None
            self._last_fed_block_id = None

    # ------------------------------------------------------------------
    # Read-only state
    # ------------------------------------------------------------------

    @property
    def current_block(self) -> ScheduledBlock | None:
        with self._lock:
            return self._current_block

    @property
    def last_fed_block_id(self) -> str | None:
        with self._lock:
            return self._last_fed_block_id

    @property
    def execution_reader(self) -> ExecutionRuntimeReader | None:
        return self._execution_reader

    # ------------------------------------------------------------------
    # Scheduling resolution (INV-CM-SUPPLY-RESOLUTION-SOLE-OWNER-001)
    # ------------------------------------------------------------------

    def resolve_current(self, now_utc_ms: int) -> ScheduledBlock | None:
        """Resolve the block covering ``now_utc_ms`` for this channel.

        Returns ``None`` if no ``ExecutionRuntimeReader`` was injected or
        the reader has no block covering the requested time.
        """
        if self._execution_reader is None:
            return None
        return self._execution_reader.get_current_execution_block(
            self.channel_id, now_utc_ms,
        )

    def resolve_next(self, after_utc_ms: int) -> ScheduledBlock | None:
        """Resolve the next block starting at or after ``after_utc_ms``.

        Returns ``None`` if no reader was injected or the reader has no
        subsequent block (horizon exhausted).
        """
        if self._execution_reader is None:
            return None
        return self._execution_reader.get_next_execution_block(
            self.channel_id, after_utc_ms,
        )

    # ------------------------------------------------------------------
    # Failure surfacing (INV-CM-SUPPLY-RESOLUTION-SOLE-OWNER-001)
    # ------------------------------------------------------------------

    def fail(self, reason: str) -> None:
        """Log the failure and dispatch the ``on_failure`` callback.

        Does not mutate ``ProducerStatus`` — that remains the producer's
        own responsibility as part of the Producer base-class contract.
        """
        self._logger.error(
            "Channel %s: producer failure reason=%s", self.channel_id, reason,
        )
        cb = self._on_failure
        if cb is None:
            return
        try:
            cb(reason)
        except Exception as exc:  # pragma: no cover — defensive
            self._logger.warning(
                "Channel %s: on_failure callback raised: %s",
                self.channel_id, exc,
            )
