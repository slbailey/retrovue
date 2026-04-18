"""
Test Playout Endpoint - Deterministic on-demand block playback.

Implements INV-TEST-BLOCK-* invariants.
Provides the /test/block/{block_id}.ts endpoint.

Architecture:
  - SingleBlockExecutionReader: serves exactly one execution block (re-timed to NOW),
    followed by a short silence pad so the driver has a subsequent block to advance
    into before lookahead_exhausted fires.
  - EphemeralTestSession: thin wrapper that owns BlockPlanProducer + ChannelStream
    for a single test request; fully torn down on disconnect.

DO NOT modify production code paths. This module only adds alongside them.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from retrovue.runtime.clock import AuthoritativeClock

logger = logging.getLogger(__name__)

# ── Pad block constants ───────────────────────────────────────────────────────
# After the content block ends, we feed a short pad so AIR has block_b.
# AIR will output black+silence (PAD) for this segment.
_PAD_DURATION_MS: int = 10_000   # 10 seconds


# ── INV-TEST-BLOCK-001: execution reader for test sessions ────────────────────

class SingleBlockExecutionReader:
    """Execution reader that presents a single block starting at a given wall-clock time.

    INV-TEST-BLOCK-001: Block timing is re-timed to start_utc_ms (now at session start).
    INV-TEST-BLOCK-002: Original segments are replayed verbatim (asset_uri, offsets).
    INV-TEST-BLOCK-003: A trailing pad block is served so the driver has a next block to advance into.
    INV-TEST-BLOCK-004: lookup returns None past pad end, causing lookahead_exhausted.
    """

    def __init__(
        self,
        block: "ScheduledBlock",
        start_utc_ms: int,
    ):
        from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment

        original_duration_ms = block.end_utc_ms - block.start_utc_ms

        # Re-time the block to start now (preserve segments verbatim)
        self._content_block = ScheduledBlock(
            block_id=block.block_id,
            start_utc_ms=start_utc_ms,
            end_utc_ms=start_utc_ms + original_duration_ms,
            segments=block.segments,
        )

        pad_start_ms = start_utc_ms + original_duration_ms
        pad_end_ms = pad_start_ms + _PAD_DURATION_MS

        # Pad block: single PAD segment with no asset_uri
        pad_segment = ScheduledSegment(
            segment_type="pad",
            asset_uri="",
            asset_start_offset_ms=0,
            segment_duration_ms=_PAD_DURATION_MS,
        )
        self._pad_block = ScheduledBlock(
            block_id=f"{block.block_id}__pad",
            start_utc_ms=pad_start_ms,
            end_utc_ms=pad_end_ms,
            segments=(pad_segment,),
        )

        self._start_utc_ms = start_utc_ms
        self._pad_end_utc_ms = pad_end_ms

    @property
    def content_block(self) -> "ScheduledBlock":
        return self._content_block

    def _lookup_execution_block(self, utc_ms: int) -> "ScheduledBlock | None":
        """Return content block if utc_ms is within content range, pad block if in pad range."""
        cb = self._content_block
        if cb.start_utc_ms <= utc_ms < cb.end_utc_ms:
            return cb
        if self._pad_block.start_utc_ms <= utc_ms < self._pad_block.end_utc_ms:
            return self._pad_block
        # Past end → None → triggers lookahead_exhausted in BlockPlanProducer
        return None

    def get_current_execution_block(self, channel_id: str, now_ms: int) -> "ScheduledBlock | None":
        return self._lookup_execution_block(now_ms)

    def get_next_execution_block(self, channel_id: str, after_utc_ms: int) -> "ScheduledBlock | None":
        return self._lookup_execution_block(after_utc_ms)

    def get_execution_depth_ms(self, channel_id: str, now_ms: int) -> int:
        return max(0, self._pad_end_utc_ms - now_ms)

    def get_playlist_event_by_block_id(self, channel_id: str, block_id: str) -> "ScheduledBlock | None":
        if self._content_block.block_id == block_id:
            return self._content_block
        if self._pad_block.block_id == block_id:
            return self._pad_block
        return None

# ── EphemeralTestSession ───────────────────────────────────────────────────────

class EphemeralTestSession:
    """Owns one BlockPlanProducer + ChannelStream for a single test request.

    INV-TEST-BLOCK-005: Session uses the same BlockPlanProducer and AIR binary as production.
    INV-TEST-BLOCK-006: Session is fully torn down on disconnect or error.
    INV-TEST-BLOCK-007: Session ID is unique per request; no state shared between requests.
    """

    def __init__(self, block_id: str, session_id: str, clock: AuthoritativeClock):
        self.block_id = block_id
        self.session_id = session_id
        self._channel_id = f"test__{session_id[:8]}"
        self._producer: Any = None
        self._fanout: Any = None
        self._clock = clock
        self._started = False
        self._lock = threading.Lock()

    def start(self, channel_config: Any) -> str:
        """
        Start the ephemeral test session.

        1. Looks up block from DB (PlaylistEvent)
        2. Creates SingleBlockExecutionReader
        3. Creates BlockPlanProducer
        4. Starts it (launch_air + per-segment LoadPreview/SwitchToLive driver)
        5. Creates ChannelStream

        Returns the channel_id for stream subscription.

        Raises RuntimeError on failure.
        """
        from retrovue.runtime.channel_manager import BlockPlanProducer
        from retrovue.runtime.channel_stream import ChannelStream
        from retrovue.runtime.config import ChannelConfig, ProgramFormat

        with self._lock:
            if self._started:
                raise RuntimeError("EphemeralTestSession already started")

            # 1. Look up block
            block = _load_block_from_db(self.block_id)
            if block is None:
                raise RuntimeError(f"Block not found: {self.block_id}")

            # 2. Build execution reader re-timed to now
            now_utc_ms = self._clock.now_utc_ms()
            execution_reader = SingleBlockExecutionReader(block, now_utc_ms)

            # 3. Build producer
            self._producer = BlockPlanProducer(
                channel_id=self._channel_id,
                clock=self._clock,
                configuration={},
                channel_config=channel_config,
                execution_reader=execution_reader,
                evidence_endpoint="",
                on_producer_failure=self._on_failure,
            )

            # 4. Start producer
            start_time = self._clock.now_utc()
            ok = self._producer.start(start_time, jip_offset_ms=0)
            if not ok:
                raise RuntimeError(f"BlockPlanProducer.start() failed for block {self.block_id}")

            # 5. Create ChannelStream backed by producer's reader_socket_queue
            channel_id = self._channel_id
            producer_ref = self._producer

            def ts_source_factory(stop_event=None) -> Any:
                from retrovue.runtime.channel_stream import SocketTsSource
                reader_queue = getattr(producer_ref, "reader_socket_queue", None)
                if reader_queue is None:
                    raise RuntimeError("No reader_socket_queue on producer")
                try:
                    sock = reader_queue.get(timeout=15.0)
                    return SocketTsSource(sock)
                except Exception as e:
                    raise RuntimeError(f"Timed out waiting for AIR socket: {e}") from e

            self._fanout = ChannelStream(
                channel_id=channel_id,
                ts_source_factory=ts_source_factory,
                clock=self._clock,
            )

            self._started = True
            logger.info(
                "EphemeralTestSession started: session=%s block=%s channel=%s start_utc_ms=%d",
                self.session_id, self.block_id, self._channel_id, now_utc_ms,
            )
            return channel_id

    def subscribe(self, viewer_id: str) -> Any:
        """Subscribe viewer to the ChannelStream's output queue."""
        if not self._fanout:
            raise RuntimeError("Session not started")
        return self._fanout.subscribe(viewer_id)

    def unsubscribe(self, viewer_id: str) -> None:
        if self._fanout:
            try:
                self._fanout.unsubscribe(viewer_id, reason="disconnect")
            except Exception:
                pass

    def stop(self) -> None:
        """Stop AIR and tear down all resources."""
        with self._lock:
            if not self._started:
                return
            self._started = False

        logger.info(
            "EphemeralTestSession stopping: session=%s block=%s",
            self.session_id, self.block_id,
        )

        if self._fanout:
            try:
                self._fanout.stop()
            except Exception as e:
                logger.debug("Fanout stop error: %s", e)
            self._fanout = None

        if self._producer:
            try:
                self._producer.stop(reason="test_session_end")
            except Exception as e:
                logger.debug("Producer stop error: %s", e)
            self._producer = None

    def _on_failure(self, reason: str) -> None:
        logger.info(
            "EphemeralTestSession: producer failure: session=%s reason=%s",
            self.session_id, reason,
        )


# ── DB lookup ──────────────────────────────────────────────────────────────────

def load_channel_slug_for_block(block_id: str) -> "Optional[str]":
    """Return the channel_slug for the given block_id, or None if not found.

    PlaylistEvent.channel_slug is the direct join key back to the channel
    that owns this block — no need to walk ScheduleRevision.
    """
    try:
        from retrovue.infra.uow import session as db_session_factory
        from retrovue.domain.entities import PlaylistEvent

        with db_session_factory() as db:
            row = db.query(PlaylistEvent.channel_slug).filter(
                PlaylistEvent.block_id == block_id,
            ).first()
            return row.channel_slug if row else None
    except Exception as e:
        logger.error("channel_slug lookup failed for block %s: %s", block_id, e)
        return None


def _load_block_from_db(block_id: str) -> "Optional[ScheduledBlock]":
    """Load a ScheduledBlock from PlaylistEvent by block_id.

    Returns None if not found.
    """
    try:
        from retrovue.infra.uow import session as db_session_factory
        from retrovue.domain.entities import PlaylistEvent
        from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment

        with db_session_factory() as db:
            row = db.query(PlaylistEvent).filter(
                PlaylistEvent.block_id == block_id,
            ).first()

            if row is None:
                logger.warning("Block not found in PlaylistEvent: %s", block_id)
                return None

            segments = []
            for s in row.segments:
                segments.append(ScheduledSegment(
                    segment_type=s.get("segment_type", "content"),
                    asset_uri=s.get("asset_uri", ""),
                    asset_start_offset_ms=int(s.get("asset_start_offset_ms", 0)),
                    segment_duration_ms=int(s.get("segment_duration_ms", 0)),
                    transition_in=s.get("transition_in", "TRANSITION_NONE"),
                    transition_in_duration_ms=int(s.get("transition_in_duration_ms", 0)),
                    transition_out=s.get("transition_out", "TRANSITION_NONE"),
                    transition_out_duration_ms=int(s.get("transition_out_duration_ms", 0)),
                    gain_db=float(s.get("gain_db", 0.0)),
                ))

            return ScheduledBlock(
                block_id=row.block_id,
                start_utc_ms=row.start_utc_ms,
                end_utc_ms=row.end_utc_ms,
                segments=tuple(segments),
            )

    except Exception as e:
        logger.error("DB lookup failed for block %s: %s", block_id, e)
        return None


# ── Default test channel config ────────────────────────────────────────────────

def _make_test_channel_config(base_config: Any = None) -> Any:
    """Build a ChannelConfig suitable for an ephemeral test session.

    Uses base_config if provided (to match a real channel's program_format).
    Falls back to MOCK_CHANNEL_CONFIG.
    """
    from retrovue.runtime.config import MOCK_CHANNEL_CONFIG, ChannelConfig
    if base_config is not None:
        return ChannelConfig(
            channel_id=base_config.channel_id + "__test",
            number=base_config.number,
            channel_id_int=base_config.channel_id_int,
            name=base_config.name + " (test)",
            program_format=base_config.program_format,
            schedule_source="dsl",
            schedule_config={},
        )
    return MOCK_CHANNEL_CONFIG
