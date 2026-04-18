"""
Boundary and transitional adapters for runtime execution readers.

This module defines the interface and implementation for reading channel execution state in the RetroVue runtime.
Its purpose is to provide a strict, auditable, and documented bridge between the execution state managed by downstream
components (such as the DSL schedule service or persisted PlaylistEvent records) and any code that needs to observe 
what is "playing now" for a given channel.

Key responsibilities:
- Implements a boundary abstraction (ExecutionRuntimeReader) to enforce contracts around read-only runtime execution access.
- Serves as an in-memory and database-backed adapter to expose a current, stable view of per-channel playout blocks
  (scheduled content segments, past/present/future).
- Restricts the reader to read-only "observer" duties—no schedule building, writing, filling, repair, or editorial mutation logic lives here.
- Bridges evolving internal backing stores (transitioning from pure DSL in-memory state to persisted records) with a consistent external API.
- Guarantees callers can safely query runtime execution state without risk of mutating it or crossing improper authority boundaries.

Do not use this module for:
- Schedule compilation or mutation
- Horizon planning or editorial decisions
- Timeline repair or "fixup" logic

All read operations here must maintain the integrity of system boundaries as described in CLAUDE.md and contracts.

"""

from __future__ import annotations

from dataclasses import replace as dc_replace
import logging
from typing import Any

import sqlalchemy as sa

from retrovue.domain.entities import PlaylistEvent
from retrovue.infra.uow import session as db_session_factory
from retrovue.runtime.dsl_schedule_service import _deserialize_scheduled_block
from retrovue.runtime.protocols import ExecutionRuntimeReader
from retrovue.runtime.schedule_types import ScheduledBlock

logger = logging.getLogger(__name__)


class DslExecutionRuntimeReader(ExecutionRuntimeReader):
    """Transitional execution reader over precomputed DSL-backed execution data.

    Allowed data sources:
    - precomputed in-memory block index (`DslScheduleService._blocks`)
    - persisted `PlaylistEvent` rows

    Forbidden:
    - compile
    - fill
    - horizon extension
    - repair
    """

    def __init__(self, channel_id: str, dsl_schedule_service: Any) -> None:
        self._channel_id = channel_id
        self._dsl_schedule_service = dsl_schedule_service

    def _channel_matches(self, channel_id: str) -> bool:
        return channel_id == self._channel_id

    def _list_blocks(self) -> list[ScheduledBlock]:
        # The backing schedule service keeps a mutable in-memory block index.
        # Read under its lock when available so runtime reads see a stable snapshot.
        lock = getattr(self._dsl_schedule_service, "_lock", None)
        if lock is None:
            return list(getattr(self._dsl_schedule_service, "_blocks", ()))
        with lock:
            return list(getattr(self._dsl_schedule_service, "_blocks", ()))

    def _frame_tolerance_ms(self) -> int:
        return max(1, int(getattr(self._dsl_schedule_service, "_frame_tolerance_ms", 1)))

    def _find_current_block_in_index(self, utc_ms: int) -> ScheduledBlock | None:
        blocks = self._list_blocks()
        for block in blocks:
            if block.start_utc_ms <= utc_ms < block.end_utc_ms:
                return block

        extension_ms = self._frame_tolerance_ms()
        for idx, block in enumerate(blocks):
            if utc_ms != block.end_utc_ms:
                continue
            # If we are exactly on a block boundary and there is no successor
            # starting at that same instant, extend the previous block by a tiny
            # tolerance to avoid a false "gap" due to frame/timestamp rounding.
            has_successor_at_boundary = (
                idx + 1 < len(blocks) and blocks[idx + 1].start_utc_ms == utc_ms
            )
            if has_successor_at_boundary:
                continue
            return dc_replace(block, end_utc_ms=block.end_utc_ms + extension_ms)
        return None

    def _find_next_block_in_index(self, after_utc_ms: int) -> ScheduledBlock | None:
        blocks = self._list_blocks()
        for block in blocks:
            if block.start_utc_ms >= after_utc_ms:
                return block
        return None

    def get_playlist_event_by_block_id(
        self,
        channel_id: str,
        block_id: str,
    ) -> ScheduledBlock | None:
        if not self._channel_matches(channel_id):
            return None

        try:
            with db_session_factory() as db:
                # The DB row is the filled execution truth for the block. The
                # in-memory index only tells us which block should be active.
                row = db.query(PlaylistEvent).filter(
                    PlaylistEvent.block_id == block_id,
                    PlaylistEvent.channel_slug == channel_id,
                ).first()
                if row is None:
                    return None
                return _deserialize_scheduled_block(
                    {
                        "block_id": row.block_id,
                        "start_utc_ms": row.start_utc_ms,
                        "end_utc_ms": row.end_utc_ms,
                        "segments": row.segments,
                    },
                    frame_tolerance_ms=self._frame_tolerance_ms(),
                )
        except Exception as exc:
            logger.debug(
                "ExecutionRuntimeReader[%s]: playlist event lookup failed for block=%s: %s",
                channel_id,
                block_id,
                exc,
            )
            return None

    def get_current_execution_block(
        self,
        channel_id: str,
        now_ms: int,
    ) -> ScheduledBlock | None:
        if not self._channel_matches(channel_id):
            return None

        block = self._find_current_block_in_index(now_ms)
        if block is None:
            return None

        # First locate the current slot in the precomputed index, then hydrate
        # it from persisted playlist data so callers get the real filled block.
        filled = self.get_playlist_event_by_block_id(channel_id, block.block_id)
        if filled is None:
            return None

        # Keep the timing from the live index if it was boundary-adjusted above.
        if filled.start_utc_ms != block.start_utc_ms or filled.end_utc_ms != block.end_utc_ms:
            filled = dc_replace(
                filled,
                start_utc_ms=block.start_utc_ms,
                end_utc_ms=block.end_utc_ms,
            )
        return filled

    def get_next_execution_block(
        self,
        channel_id: str,
        after_utc_ms: int,
    ) -> ScheduledBlock | None:
        if not self._channel_matches(channel_id):
            return None

        block = self._find_next_block_in_index(after_utc_ms)
        if block is None:
            return None

        # "Next" uses the same two-step read path: locate from the in-memory
        # index, then fetch the persisted filled block for that block id.
        filled = self.get_playlist_event_by_block_id(channel_id, block.block_id)
        if filled is None:
            return None

        if filled.start_utc_ms != block.start_utc_ms or filled.end_utc_ms != block.end_utc_ms:
            filled = dc_replace(
                filled,
                start_utc_ms=block.start_utc_ms,
                end_utc_ms=block.end_utc_ms,
            )
        return filled

    def get_execution_depth_ms(
        self,
        channel_id: str,
        now_ms: int,
    ) -> int:
        if not self._channel_matches(channel_id):
            return 0

        try:
            with db_session_factory() as db:
                # Depth is "how far execution data is available past now" rather
                # than "how many blocks exist in memory".
                farthest_end_utc_ms = db.query(sa.func.max(PlaylistEvent.end_utc_ms)).filter(
                    PlaylistEvent.channel_slug == channel_id,
                ).scalar() or 0
        except Exception as exc:
            logger.debug(
                "ExecutionRuntimeReader[%s]: depth query failed: %s",
                channel_id,
                exc,
            )
            return 0

        return max(0, int(farthest_end_utc_ms) - int(now_ms))
