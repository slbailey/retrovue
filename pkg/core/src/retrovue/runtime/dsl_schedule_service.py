"""
DSL-backed ScheduleService.

Compiles a Programming DSL file into a rolling multi-day playout log,
resolves asset URIs to local file paths, and serves ScheduledBlocks
to ChannelManager on demand.

Rolling horizon: compiles HORIZON_DAYS days ahead. When the remaining
pre-built blocks shrink below RECOMPILE_THRESHOLD_HOURS, appends the
next day automatically. Thread-safe for concurrent reads during recompile.

Implements the ScheduleService protocol (get_block_at, get_playout_plan_now).
"""

from __future__ import annotations

import logging
import subprocess
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures.thread import _worker, _threads_queues
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Any

from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment
from retrovue.runtime.schedule_compiler import compile_schedule, parse_dsl
from retrovue.runtime.playout_log_expander import expand_program_block


class _DaemonThreadPoolExecutor(ThreadPoolExecutor):
    """ThreadPoolExecutor whose worker threads are daemon threads.

    Prevents in-flight background tasks (e.g. loudness measurement) from
    blocking process exit on Ctrl-C.
    """

    def _adjust_thread_count(self):
        if self._idle_semaphore.acquire(timeout=0):
            return

        def weakref_cb(_, q=self._work_queue):
            q.put(None)

        num_threads = len(self._threads)
        if num_threads < self._max_workers:
            thread_name = '%s_%d' % (self._thread_name_prefix or self,
                                     num_threads)
            t = threading.Thread(name=thread_name, target=_worker,
                                 args=(weakref.ref(self, weakref_cb),
                                       self._work_queue,
                                       self._initializer,
                                       self._initargs))
            t.daemon = True
            t.start()
            self._threads.add(t)
            _threads_queues[t] = self._work_queue
from retrovue.runtime.traffic_manager import fill_ad_blocks
from retrovue.runtime.catalog_resolver import CatalogAssetResolver
from retrovue.adapters.enrichers.loudness_enricher import needs_loudness_measurement
from retrovue.infra.uow import session

import hashlib
import json as json_mod
from datetime import date as date_type

logger = logging.getLogger(__name__)

# How many days ahead to compile on initial load
HORIZON_DAYS = 3

# When remaining schedule falls below this many hours, compile the next day
RECOMPILE_THRESHOLD_HOURS = 6


def _serialize_scheduled_block(block: "ScheduledBlock") -> dict:
    """Serialize a ScheduledBlock to a JSON-safe dict for DB storage.

    INV-SCHEDULE-HORIZON-001: Round-trip serialization preserves all
    segment fields including transitions.
    """
    segments = []
    for s in block.segments:
        d = {
            "segment_type": s.segment_type,
            "asset_uri": s.asset_uri,
            "asset_start_offset_ms": s.asset_start_offset_ms,
            "segment_duration_ms": s.segment_duration_ms,
            "transition_in": s.transition_in,
            "transition_in_duration_ms": s.transition_in_duration_ms,
            "transition_out": s.transition_out,
            "transition_out_duration_ms": s.transition_out_duration_ms,
        }
        # INV-LOUDNESS-NORMALIZED-001: persist gain_db when non-zero
        if s.gain_db != 0.0:
            d["gain_db"] = s.gain_db
        # INV-MOVIE-PRIMARY-ATOMIC: persist is_primary when True
        if s.is_primary:
            d["is_primary"] = True
        segments.append(d)
    d = {
        "block_id": block.block_id,
        "start_utc_ms": block.start_utc_ms,
        "end_utc_ms": block.end_utc_ms,
        "segments": segments,
    }
    if block.traffic_profile:
        d["traffic_profile"] = block.traffic_profile
    return d


# INV-BLOCK-SEGMENT-CONSERVATION-001: 1 frame at 29.97fps, rounded up.
FRAME_TOLERANCE_MS = 40


def _deserialize_scheduled_block(d: dict) -> "ScheduledBlock":
    """Deserialize a dict back into a ScheduledBlock.

    INV-SCHEDULE-HORIZON-001: Used by Tier 2 (Playlog Horizon Daemon)
    and _hydrate_schedule to reconstruct blocks from DB cache.

    INV-BLOCK-SEGMENT-CONSERVATION-001: Rejects blocks where segment
    durations violate conservation (delta > FRAME_TOLERANCE_MS or any
    segment has non-positive duration).
    """
    from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment

    segments = tuple(
        ScheduledSegment(
            segment_type=s["segment_type"],
            asset_uri=s.get("asset_uri", ""),
            asset_start_offset_ms=int(s.get("asset_start_offset_ms", 0)),
            segment_duration_ms=int(s.get("segment_duration_ms", 0)),
            transition_in=s.get("transition_in", "TRANSITION_NONE"),
            transition_in_duration_ms=int(s.get("transition_in_duration_ms", 0)),
            transition_out=s.get("transition_out", "TRANSITION_NONE"),
            transition_out_duration_ms=int(s.get("transition_out_duration_ms", 0)),
            gain_db=s.get("gain_db", 0.0),
            is_primary=s.get("is_primary", False),
        )
        for s in d["segments"]
    )

    # INV-BLOCK-SEGMENT-CONSERVATION-001: Reject negative segment durations.
    for seg in segments:
        if seg.segment_duration_ms < 1:
            raise ValueError(
                f"INV-BLOCK-SEGMENT-CONSERVATION-001: Negative or zero "
                f"segment duration — block={d['block_id']} "
                f"segment_type={seg.segment_type} "
                f"duration_ms={seg.segment_duration_ms}"
            )

    block = ScheduledBlock(
        block_id=d["block_id"],
        start_utc_ms=d["start_utc_ms"],
        end_utc_ms=d["end_utc_ms"],
        segments=segments,
        traffic_profile=d.get("traffic_profile"),
    )

    # INV-BLOCK-SEGMENT-CONSERVATION-001: Reject overstuffed/understuffed
    # blocks beyond frame tolerance.
    block_duration_ms = block.end_utc_ms - block.start_utc_ms
    sum_segment_ms = sum(s.segment_duration_ms for s in block.segments)
    delta_ms = sum_segment_ms - block_duration_ms
    if abs(delta_ms) > FRAME_TOLERANCE_MS:
        raise ValueError(
            f"INV-BLOCK-SEGMENT-CONSERVATION-001: Stale Tier 2 data — "
            f"block={block.block_id} sum={sum_segment_ms}ms "
            f"duration={block_duration_ms}ms delta={delta_ms}ms "
            f"segment_count={len(block.segments)} stage=deserialization"
        )

    return block


class DslScheduleService:
    """
    Schedule service backed by the Programming DSL compiler pipeline.

    On load, compiles HORIZON_DAYS days of schedule.
    On get_block_at, checks horizon and extends if needed.
    Serves pre-built ScheduledBlocks by wall-clock time.
    """

    def __init__(
        self,
        dsl_path: str,
        filler_path: str,
        filler_duration_ms: int,
        broadcast_day: str | None = None,
        programming_day_start_hour: int = 6,
        channel_slug: str | None = None,
        channel_type: str = "network",
    ) -> None:
        self._dsl_path = dsl_path
        self._filler_path = filler_path
        self._filler_duration_ms = filler_duration_ms
        self._day_start_hour = programming_day_start_hour
        self._broadcast_day_override = broadcast_day
        self._channel_slug = channel_slug
        self._channel_type = channel_type

        # Pre-built blocks indexed by start_utc_ms
        self._blocks: list[ScheduledBlock] = []
        self._lock = threading.Lock()
        self._uri_cache: dict[str, str] = {}

        # Track which broadcast days have been compiled (set of "YYYY-MM-DD")
        self._compiled_days: set[str] = set()


        # Recompile guard: prevent concurrent horizon extensions
        self._extending = False

        # INV-SCHEDULE-RETENTION-001: throttle DB purge to at most once/hour
        self._last_tier1_purge_utc_ms: int = 0

        # Cached CatalogAssetResolver (Part 2B: avoid per-compile reload)
        # TTL-based: resolver is rebuilt if catalog may have changed.
        self._resolver: CatalogAssetResolver | None = None
        self._resolver_built_at: float = 0.0
        self._resolver_ttl_s: float = 60.0  # 60-second TTL

        # Cached channel timezone from DSL parse (avoids re-reading DSL file
        # on every Tier 2 miss in ensure_block_compiled).
        self._channel_tz = None

        # Cached parsed channel DSL for traffic policy resolution.
        self._channel_dsl: dict | None = None

        # INV-LOUDNESS-NORMALIZED-001: Background loudness measurement
        # Lazy backfill: unmeasured assets enqueue a background job on first encounter.
        # _loudness_pending prevents duplicate enqueues.
        self._loudness_pending: set[str] = set()
        self._loudness_lock = threading.Lock()
        self._loudness_executor: ThreadPoolExecutor | None = None

    def shutdown(self) -> None:
        """Shut down background resources (loudness executor).

        Called by ProgramDirector.stop() to ensure the process can exit
        without waiting for in-flight loudness measurements to complete.
        """
        with self._loudness_lock:
            if self._loudness_executor is not None:
                self._loudness_executor.shutdown(wait=False, cancel_futures=True)
                self._loudness_executor = None

    def _enqueue_loudness_measurement(self, asset_id: str, file_path: str) -> None:
        """INV-LOUDNESS-NORMALIZED-001 Rule 5: Enqueue background loudness measurement.

        Deduplicates by asset_id. The background job runs ffmpeg ebur128,
        computes gain_db, and persists to AssetProbed.
        """
        with self._loudness_lock:
            if asset_id in self._loudness_pending:
                return  # Already in-flight
            self._loudness_pending.add(asset_id)
            if self._loudness_executor is None:
                self._loudness_executor = _DaemonThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="loudness-measure",
                )

        self._loudness_executor.submit(self._run_loudness_measurement, asset_id, file_path)
        logger.info(
            "INV-LOUDNESS-NORMALIZED-001: Enqueued background loudness measurement "
            "for asset=%s path=%s",
            asset_id, file_path,
        )

    def _run_loudness_measurement(self, asset_id: str, file_path: str) -> None:
        """Background task: measure loudness and persist to AssetProbed."""
        try:
            import os
            if not os.path.isfile(file_path):
                self._demote_missing_asset(asset_id, file_path)
                return

            from retrovue.adapters.enrichers.loudness_enricher import LoudnessEnricher
            enricher = LoudnessEnricher()
            # measure_loudness returns {"integrated_lufs", "gain_db", "target_lufs"}
            loudness_data = enricher.measure_loudness(file_path)

            # Persist to AssetProbed
            import uuid as uuid_mod
            from retrovue.domain.entities import AssetProbed
            with session() as db:
                probed = db.query(AssetProbed).filter(
                    AssetProbed.asset_uuid == uuid_mod.UUID(asset_id),
                ).first()
                if probed is None:
                    probed = AssetProbed(
                        asset_uuid=uuid_mod.UUID(asset_id),
                        payload={"loudness": loudness_data},
                    )
                    db.add(probed)
                else:
                    payload = dict(probed.payload) if probed.payload else {}
                    payload["loudness"] = loudness_data
                    probed.payload = payload
                db.commit()

            logger.info(
                "INV-LOUDNESS-NORMALIZED-001: Background measurement complete "
                "asset=%s integrated_lufs=%.1f gain_db=%.1f",
                asset_id,
                loudness_data["integrated_lufs"],
                loudness_data["gain_db"],
            )

            # Update in-place instead of invalidating: avoids full resolver
            # rebuild (12k+ assets) which causes UPSTREAM_LOOP spikes on the
            # event thread via GIL contention.
            resolver = self._resolver
            if resolver is not None:
                resolver.update_asset_loudness(asset_id, loudness_data["gain_db"])

        except subprocess.TimeoutExpired:
            logger.warning(
                "INV-LOUDNESS-NORMALIZED-001: Background loudness measurement "
                "timed out for asset=%s path=%s — will retry on next compile",
                asset_id, file_path,
            )
        except Exception:
            logger.exception(
                "INV-LOUDNESS-NORMALIZED-001: Background loudness measurement "
                "error for asset=%s",
                asset_id,
            )
        finally:
            with self._loudness_lock:
                self._loudness_pending.discard(asset_id)

    def _demote_missing_asset(self, asset_id: str, file_path: str) -> None:
        """Demote an asset whose source file is missing from disk to 'new'."""
        import uuid as uuid_mod
        from retrovue.domain.entities import Asset

        with session() as db:
            asset = db.query(Asset).filter(
                Asset.uuid == uuid_mod.UUID(asset_id),
            ).first()
            if asset is not None and asset.state == "ready":
                asset.state = "new"
                asset.approved_for_broadcast = False
                db.commit()
                logger.warning(
                    "Asset %s demoted ready → new: source file missing: %s",
                    asset_id, file_path,
                )

    def _get_resolver(self) -> CatalogAssetResolver:
        """Return a cached CatalogAssetResolver, rebuilding if TTL expired.

        TTL=60s balances freshness vs cost. The catalog (12k+ assets) changes
        rarely (ingest events), so a 60s window is safe. The resolver is
        read-only after construction — safe to share across threads.
        """
        import time
        now = time.monotonic()
        if self._resolver is not None and (now - self._resolver_built_at) < self._resolver_ttl_s:
            return self._resolver
        with session() as db:
            resolver = CatalogAssetResolver(db)
        self._resolver = resolver
        self._resolver_built_at = now
        logger.debug(
            "CatalogAssetResolver rebuilt (TTL=%.0fs, channel=%s)",
            self._resolver_ttl_s, self._channel_slug,
        )
        return resolver

    def load_schedule(self, channel_id: str) -> tuple[bool, str | None]:
        """Compile DSL and build the initial multi-day playout log."""
        try:
            self._build_initial(channel_id)
            return (True, None)
        except Exception as e:
            logger.error(f"Failed to load DSL schedule: {e}", exc_info=True)
            return (False, str(e))

    def get_block_at(self, channel_id: str, utc_ms: int) -> ScheduledBlock | None:
        """Return the ScheduledBlock covering the given wall-clock time.

        INV-TIER2-COMPILATION-CONSISTENCY-001: Time resolution uses the current
        in-memory compilation exclusively. PlaylistEvent is queried by block_id
        only — never by time range.

        INV-CHANNEL-NO-COMPILE-001: If Tier 2 has no row for this block, compiles
        it synchronously via ensure_block_compiled().

        Also checks if the horizon needs extending.
        """
        # Check horizon before lookup
        self._maybe_extend_horizon(channel_id, utc_ms)

        # Step 1: In-memory time resolution (current compilation)
        # INV-TIER2-COMPILATION-CONSISTENCY-001: Time-to-block mapping is
        # a pure in-memory concern — always uses the current compilation.
        block = self._find_in_memory_block(utc_ms)
        if block is None:
            logger.warning(
                "No DSL block covers utc_ms=%d for channel=%s", utc_ms, channel_id
            )
            return None

        # Step 2: Check PlaylistEvent for filled version BY BLOCK_ID
        filled = self._get_filled_block_by_id(block.block_id)
        if filled is not None:
            return filled

        # Step 3: Fill synchronously
        # INV-TIER2-AUTHORITY-001: Compilation is synchronous at ownership time.
        return self.ensure_block_compiled(channel_id, block)

    def ensure_block_compiled(self, channel_id: str, block: ScheduledBlock) -> ScheduledBlock:
        """Ensure a single block has a Tier 2 (PlaylistEvent) entry.

        INV-TIER2-AUTHORITY-001: Synchronous, idempotent Tier 2 compilation.

        Properties:
          - If block already compiled in PlaylistEvent → returns compiled version (no-op)
          - If not compiled → fills ads synchronously, writes to PlaylistEvent, returns filled block
          - Safe to call concurrently: uses INSERT ... ON CONFLICT DO NOTHING pattern
          - Does NOT trigger full schedule recompilation
          - Does NOT invalidate existing compiled blocks

        This is the authority path. The PlaylistBuilderDaemon is a preheater
        that reduces how often this synchronous path is hit, but correctness
        does not depend on the daemon.
        """
        from retrovue.domain.entities import PlaylistEvent
        from retrovue.runtime.traffic_manager import fill_ad_blocks

        # Check if already compiled (idempotent fast path)
        try:
            with session() as db:
                row = db.query(PlaylistEvent).filter(
                    PlaylistEvent.block_id == block.block_id,
                ).first()
                if row is not None:
                    # Already compiled — deserialize and return
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
                            gain_db=s.get("gain_db", 0.0),
                        ))
                    cached = ScheduledBlock(
                        block_id=row.block_id,
                        start_utc_ms=row.start_utc_ms,
                        end_utc_ms=row.end_utc_ms,
                        segments=tuple(segments),
                    )

                    # INV-BLOCK-SEGMENT-CONSERVATION-001: Reject stale row.
                    cached_dur = cached.end_utc_ms - cached.start_utc_ms
                    cached_sum = sum(
                        s.segment_duration_ms for s in cached.segments
                    )
                    if abs(cached_sum - cached_dur) > FRAME_TOLERANCE_MS:
                        logger.warning(
                            "INV-BLOCK-SEGMENT-CONSERVATION-001: Stale Tier 2 "
                            "row in ensure_block_compiled — block=%s sum=%dms "
                            "duration=%dms delta=%dms segment_count=%d "
                            "stage=deserialization. Deleting to recompile.",
                            block.block_id, cached_sum, cached_dur,
                            cached_sum - cached_dur, len(cached.segments),
                        )
                        db.delete(row)
                        db.commit()
                        # Fall through to recompile below
                    else:
                        logger.debug(
                            "INV-TIER2-AUTHORITY-001: block %s already compiled (channel=%s)",
                            block.block_id, channel_id,
                        )
                        return cached
        except Exception as e:
            logger.warning(
                "INV-TIER2-AUTHORITY-001: DB check failed for block=%s: %s — compiling anyway",
                block.block_id, e,
            )

        # Not compiled — fill ads synchronously
        logger.info(
            "INV-TIER2-AUTHORITY-001: Synchronous compile for block=%s channel=%s "
            "(Tier 2 miss at ownership boundary)",
            block.block_id, channel_id,
        )

        asset_lib = None
        try:
            from retrovue.catalog.db_asset_library import DatabaseAssetLibrary
            with session() as db:
                asset_lib = DatabaseAssetLibrary(db, channel_slug=channel_id)
        except Exception as e:
            logger.warning(
                "INV-TIER2-AUTHORITY-001: Could not create asset library for %s: %s",
                channel_id, e,
            )

        # Resolve traffic policy and break config from channel DSL.
        # Uses block.traffic_profile when present (block-level override),
        # otherwise falls back to channel default_profile.
        # Channels without a traffic section get policy=None → filler fallback.
        traffic_policy = None
        break_config = None
        if self._channel_dsl and "traffic" in self._channel_dsl:
            try:
                from retrovue.runtime.traffic_dsl import (
                    resolve_break_config,
                    resolve_traffic_policy,
                )
                block_dict = {}
                if block.traffic_profile:
                    block_dict = {"traffic_profile": block.traffic_profile}
                traffic_policy = resolve_traffic_policy(self._channel_dsl, block_dict)
                break_config = resolve_break_config(self._channel_dsl)
            except Exception as e:
                logger.warning(
                    "Could not resolve traffic config for %s: %s",
                    channel_id, e,
                )

        filled_block = fill_ad_blocks(
            block,
            filler_uri=self._filler_path,
            filler_duration_ms=self._filler_duration_ms,
            asset_library=asset_lib,
            policy=traffic_policy,
            break_config=break_config,
        )

        # Write to PlaylistEvent (idempotent via merge)
        try:
            segments_data = []
            for i, seg in enumerate(filled_block.segments):
                d = {
                    "segment_index": i,
                    "segment_type": seg.segment_type,
                    "asset_uri": seg.asset_uri,
                    "asset_start_offset_ms": seg.asset_start_offset_ms,
                    "segment_duration_ms": seg.segment_duration_ms,
                }
                if seg.transition_in != "TRANSITION_NONE":
                    d["transition_in"] = seg.transition_in
                    d["transition_in_duration_ms"] = seg.transition_in_duration_ms
                if seg.transition_out != "TRANSITION_NONE":
                    d["transition_out"] = seg.transition_out
                    d["transition_out_duration_ms"] = seg.transition_out_duration_ms
                # INV-LOUDNESS-NORMALIZED-001: persist gain_db when non-zero
                if seg.gain_db != 0.0:
                    d["gain_db"] = seg.gain_db
                segments_data.append(d)

            from datetime import date as date_type
            block_dt = datetime.fromtimestamp(block.start_utc_ms / 1000.0, tz=timezone.utc)
            # Use cached channel tz (populated by _build_initial) for broadcast day
            tz = self._channel_tz or timezone.utc
            local_dt = block_dt.astimezone(tz)
            if local_dt.hour < self._day_start_hour:
                broadcast_day = (local_dt - timedelta(days=1)).date()
            else:
                broadcast_day = local_dt.date()

            with session() as db:
                row = PlaylistEvent(
                    block_id=filled_block.block_id,
                    channel_slug=channel_id,
                    broadcast_day=broadcast_day,
                    start_utc_ms=filled_block.start_utc_ms,
                    end_utc_ms=filled_block.end_utc_ms,
                    segments=segments_data,
                )
                db.merge(row)

            logger.info(
                "INV-TIER2-AUTHORITY-001: Compiled and persisted block=%s channel=%s (%d segs)",
                filled_block.block_id, channel_id, len(filled_block.segments),
            )
        except Exception as e:
            logger.error(
                "INV-TIER2-AUTHORITY-001: Failed to persist block=%s: %s — returning filled block anyway",
                filled_block.block_id, e,
            )

        return filled_block

    def _find_in_memory_block(self, utc_ms: int) -> ScheduledBlock | None:
        """Pure in-memory time-range lookup on the current compilation.

        INV-TIER2-COMPILATION-CONSISTENCY-001: Time resolution is an in-memory
        concern. This method is the sole authority for mapping utc_ms to a block.
        """
        with self._lock:
            for block in self._blocks:
                if block.start_utc_ms <= utc_ms < block.end_utc_ms:
                    return block
        return None

    def _get_filled_block_by_id(self, block_id: str) -> ScheduledBlock | None:
        """Look up a pre-filled block from PlaylistEvent by block_id.

        INV-TIER2-COMPILATION-CONSISTENCY-001: PlaylistEvent is queried by
        block_id only — never by time range. Its role is to answer: "Do we
        have a filled version of this block_id?"

        INV-CHANNEL-NO-COMPILE-001 / INV-PLAYLOG-PREFILL-001:
        Returns a ScheduledBlock with real ad URIs if the Playlog Horizon
        Daemon has already filled this block. Returns None otherwise.
        """
        try:
            from retrovue.infra.uow import session as db_session_factory
            from retrovue.domain.entities import PlaylistEvent

            with db_session_factory() as db:
                row = db.query(PlaylistEvent).filter(
                    PlaylistEvent.block_id == block_id,
                ).first()

                if row is None:
                    return None

                # Deserialize TX log segments into ScheduledBlock
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
                        gain_db=s.get("gain_db", 0.0),
                    ))

                filled = ScheduledBlock(
                    block_id=row.block_id,
                    start_utc_ms=row.start_utc_ms,
                    end_utc_ms=row.end_utc_ms,
                    segments=tuple(segments),
                )

                # INV-BLOCK-SEGMENT-CONSERVATION-001: Reject stale row and
                # delete it so ensure_block_compiled recompiles correctly.
                block_dur = filled.end_utc_ms - filled.start_utc_ms
                seg_sum = sum(
                    s.segment_duration_ms for s in filled.segments
                )
                if abs(seg_sum - block_dur) > FRAME_TOLERANCE_MS:
                    logger.warning(
                        "INV-BLOCK-SEGMENT-CONSERVATION-001: Stale Tier 2 "
                        "row invalidated — block=%s sum=%dms duration=%dms "
                        "delta=%dms segment_count=%d stage=deserialization. "
                        "Deleting to force recompile.",
                        block_id, seg_sum, block_dur, seg_sum - block_dur,
                        len(filled.segments),
                    )
                    db.delete(row)
                    db.commit()
                    return None

                logger.debug(
                    "INV-CHANNEL-NO-COMPILE-001: Tier 2 hit for "
                    "block=%s (%d segs)",
                    row.block_id, len(segments),
                )

                return filled

        except Exception as e:
            logger.warning(
                "INV-CHANNEL-NO-COMPILE-001: Tier 2 lookup failed for "
                "block_id=%s: %s — falling back to unfilled",
                block_id, e,
            )
            return None

    def get_playout_plan_now(
        self,
        channel_id: str,
        at_station_time: datetime,
    ) -> list[dict[str, Any]]:
        """Return playout plan segments for the block covering at_station_time."""
        if at_station_time.tzinfo is None:
            at_station_time = at_station_time.replace(tzinfo=timezone.utc)
        utc_ms = int(at_station_time.timestamp() * 1000)

        block = self.get_block_at(channel_id, utc_ms)
        if block is None:
            return []

        now_ms = utc_ms
        result: list[dict[str, Any]] = []
        cursor_ms = block.start_utc_ms

        for seg in block.segments:
            seg_end_ms = cursor_ms + seg.segment_duration_ms

            if seg.segment_type == "pad":
                cursor_ms = seg_end_ms
                continue

            if seg_end_ms <= now_ms:
                cursor_ms = seg_end_ms
                continue

            # Compute join offset for mid-segment join
            if now_ms > cursor_ms:
                elapsed_ms = now_ms - cursor_ms
                effective_offset_ms = seg.asset_start_offset_ms + elapsed_ms
            else:
                effective_offset_ms = seg.asset_start_offset_ms

            seg_start_utc = datetime.fromtimestamp(cursor_ms / 1000, tz=timezone.utc)
            seg_end_utc = datetime.fromtimestamp(seg_end_ms / 1000, tz=timezone.utc)

            result.append({
                "asset_path": seg.asset_uri,
                "start_pts": effective_offset_ms,
                "segment_type": seg.segment_type,
                "start_time_utc": seg_start_utc.isoformat(),
                "end_time_utc": seg_end_utc.isoformat(),
                "duration_seconds": seg.segment_duration_ms / 1000,
                "frame_count": int(seg.segment_duration_ms / 1000 * 30),
            })

            cursor_ms = seg_end_ms

        return result

    # ── Rolling horizon ───────────────────────────────────────────────

    def _maybe_extend_horizon(self, channel_id: str, now_utc_ms: int) -> None:
        """If remaining schedule is thin, compile the next day in-band."""
        with self._lock:
            if self._extending:
                return  # another call is already extending
            if not self._blocks:
                return
            last_end_ms = self._blocks[-1].end_utc_ms
            remaining_ms = last_end_ms - now_utc_ms
            threshold_ms = RECOMPILE_THRESHOLD_HOURS * 3600 * 1000
            if remaining_ms > threshold_ms:
                return
            self._extending = True

        # Outside lock: compile next day
        try:
            last_end = datetime.fromtimestamp(last_end_ms / 1000, tz=timezone.utc)
            next_day = last_end.date()
            day_str = next_day.strftime("%Y-%m-%d")

            if day_str in self._compiled_days:
                # Already compiled; try the day after
                next_day = next_day + timedelta(days=1)
                day_str = next_day.strftime("%Y-%m-%d")
                if day_str in self._compiled_days:
                    return

            logger.info(
                "Extending DSL horizon: compiling %s for channel=%s "
                "(remaining=%d min)",
                day_str, channel_id, remaining_ms // 60000,
            )
            new_blocks = self._compile_day(channel_id, day_str)
            if new_blocks:
                with self._lock:
                    self._blocks.extend(new_blocks)
                    self._blocks.sort(key=lambda b: b.start_utc_ms)
                    self._compiled_days.add(day_str)
                logger.info(
                    "Horizon extended: +%d blocks for %s (total=%d)",
                    len(new_blocks), day_str, len(self._blocks),
                )

            # Prune old blocks (>24h in the past) to save memory
            self._prune_old_blocks(now_utc_ms)

            # INV-SCHEDULE-RETENTION-001: purge expired Tier 1 DB rows
            self._purge_expired_tier1(now_utc_ms)

        except Exception as e:
            logger.error(
                "Failed to extend DSL horizon for channel=%s: %s",
                channel_id, e, exc_info=True,
            )
        finally:
            with self._lock:
                self._extending = False

    def _prune_old_blocks(self, now_utc_ms: int) -> None:
        """Remove blocks that ended more than 24h ago."""
        cutoff = now_utc_ms - (24 * 3600 * 1000)
        with self._lock:
            before = len(self._blocks)
            self._blocks = [b for b in self._blocks if b.end_utc_ms > cutoff]
            pruned = before - len(self._blocks)
            if pruned > 0:
                logger.info("Pruned %d old blocks (>24h past)", pruned)

    def _purge_expired_tier1(self, now_utc_ms: int = 0) -> int:
        """Delete ProgramLogDay rows with broadcast_day < today - 1.

        INV-SCHEDULE-RETENTION-001: Tier 1 retains only rows where
        broadcast_day >= today - 1. Throttled to at most once per hour.

        Returns the number of rows deleted (0 if throttled or no-op).
        """
        if now_utc_ms == 0:
            now_utc_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        # Hourly throttle
        if (now_utc_ms - self._last_tier1_purge_utc_ms) < 3_600_000:
            return 0

        from retrovue.domain.entities import ProgramLogDay

        cutoff = date.today() - timedelta(days=1)
        try:
            with session() as db:
                count = db.query(ProgramLogDay).filter(
                    ProgramLogDay.broadcast_day < cutoff,
                ).delete()
            self._last_tier1_purge_utc_ms = now_utc_ms
            if count > 0:
                logger.info(
                    "INV-SCHEDULE-RETENTION-001: Purged %d expired Tier 1 rows "
                    "(broadcast_day < %s)",
                    count, cutoff.isoformat(),
                )
            return count
        except Exception as e:
            logger.warning(
                "INV-SCHEDULE-RETENTION-001: Tier 1 purge failed: %s", e,
            )
            return 0

    # ── Build / compile ───────────────────────────────────────────────

    def _build_initial(self, channel_id: str) -> None:
        """Compile DSL for today + HORIZON_DAYS-1 additional days.

        INV-CHANNEL-STARTUP-NONBLOCKING-001: Idempotent — if blocks are already
        loaded, return immediately without recompilation.
        """
        with self._lock:
            if self._blocks:
                return

        now = datetime.now(timezone.utc)

        if self._broadcast_day_override:
            start_date = date.fromisoformat(self._broadcast_day_override)
        else:
            # Programming day starts at day_start_hour; if before that, use yesterday
            from zoneinfo import ZoneInfo
            # Read timezone from DSL
            dsl_text = Path(self._dsl_path).read_text()
            dsl = parse_dsl(dsl_text)
            self._channel_dsl = dsl  # cache for traffic policy resolution
            tz_name = dsl.get("timezone", "UTC")
            try:
                tz = ZoneInfo(tz_name)
            except Exception:
                tz = timezone.utc
            self._channel_tz = tz  # cache for ensure_block_compiled()
            local_now = now.astimezone(tz)
            if local_now.hour < self._day_start_hour:
                start_date = (local_now - timedelta(days=1)).date()
            else:
                start_date = local_now.date()

        all_blocks: list[ScheduledBlock] = []
        for day_offset in range(HORIZON_DAYS):
            day = start_date + timedelta(days=day_offset)
            day_str = day.strftime("%Y-%m-%d")
            try:
                blocks = self._compile_day(channel_id, day_str)
                all_blocks.extend(blocks)
                self._compiled_days.add(day_str)
                logger.debug(
                    "Compiled day %s: %d blocks for channel=%s",
                    day_str, len(blocks), channel_id,
                )
            except Exception as e:
                logger.error(
                    "Failed to compile day %s for channel=%s: %s",
                    day_str, channel_id, e, exc_info=True,
                )

        all_blocks.sort(key=lambda b: b.start_utc_ms)
        with self._lock:
            self._blocks = all_blocks

        logger.info(
            "DSL schedule built: %d blocks across %d days for channel=%s",
            len(all_blocks), len(self._compiled_days), channel_id,
        )

    @staticmethod
    def _count_slots_in_dsl(dsl: dict) -> int:
        """Count total episode slots per broadcast day.

        NOTE: INV-SCHEDULE-SEQUENTIAL-ADVANCE-001 is RETIRED. This method
        is retained for non-sequential use cases. Handles three block formats:
          - slot-style:  block_def["slots"] list
          - block-style: block_def["block"] with duration/start/end
          - movie_marathon: block_def["movie_marathon"] with start/end
        """
        from retrovue.runtime.schedule_compiler import (
            NETWORK_GRID_MINUTES,
            BROADCAST_DAY_START_HOUR,
        )

        grid_minutes = NETWORK_GRID_MINUTES

        def _parse_duration(dur_str: str) -> timedelta:
            import re
            dur_str = dur_str.strip().lower()
            hours = 0
            minutes = 0
            h_match = re.search(r'(\d+)\s*h', dur_str)
            m_match = re.search(r'(\d+)\s*m', dur_str)
            if h_match:
                hours = int(h_match.group(1))
            if m_match:
                minutes = int(m_match.group(1))
            if not h_match and not m_match:
                try:
                    hours = int(dur_str)
                except ValueError:
                    raise ValueError(f"Cannot parse duration: {dur_str!r}")
            return timedelta(hours=hours, minutes=minutes)

        def _block_slots(block_def: dict) -> int:
            """Estimate episode slots for a single schedule entry."""
            # Slot-style: integer count or explicit slots list
            slots = block_def.get("slots")
            if slots is not None:
                return slots if isinstance(slots, int) else len(slots)

            # Block-style: block with duration or start/end
            bb = block_def.get("block") or block_def.get("movie_marathon")
            if bb and isinstance(bb, dict):
                duration_str = bb.get("duration", "")
                start_str = bb.get("start", "")
                end_str = bb.get("end", "")

                if duration_str:
                    td = _parse_duration(duration_str)
                    total_min = int(td.total_seconds() // 60)
                elif start_str and end_str:
                    s_parts = start_str.split(":")
                    e_parts = end_str.split(":")
                    s_min = int(s_parts[0]) * 60 + (int(s_parts[1]) if len(s_parts) > 1 else 0)
                    e_min = int(e_parts[0]) * 60 + (int(e_parts[1]) if len(e_parts) > 1 else 0)
                    # Handle overnight wrap (e.g. 22:00 → 06:00)
                    if e_min <= s_min:
                        e_min += 24 * 60
                    total_min = e_min - s_min
                else:
                    # No duration or end — default full 24h
                    total_min = 24 * 60

                return max(1, total_min // grid_minutes)

            return 0

        count = 0
        schedule = dsl.get("schedule", {})
        for day_key, day_value in schedule.items():
            if isinstance(day_value, list):
                for block_def in day_value:
                    if isinstance(block_def, dict):
                        count += _block_slots(block_def)
            elif isinstance(day_value, dict):
                count += _block_slots(day_value)
        return count

    def _get_cached_schedule(self, channel_id: str, broadcast_day: str) -> dict | None:
        """Deprecated ProgramLogDay cache path (Stage 4).

        Schedule authority now lives in ScheduleRevision + ScheduleItems.
        Keep compile behavior deterministic by treating this as cache-miss.
        """
        return None

    def _save_compiled_schedule(self, channel_id: str, broadcast_day: str, schedule: dict, dsl_hash: str) -> None:
        """Persist compiled schedule to relational Tier-1 authority only.

        Stage 4: ProgramLogDay schedule storage is deprecated.
        """
        from retrovue.runtime.schedule_revision_writer import (
            write_active_revision_from_compiled_schedule,
        )
        try:
            bd = date_type.fromisoformat(broadcast_day)
            with session() as db:
                write_active_revision_from_compiled_schedule(
                    db,
                    channel_slug=channel_id,
                    broadcast_day=bd,
                    schedule=schedule,
                    created_by="dsl_schedule_service",
                )
        except Exception as e:
            logger.warning("Failed to save compiled schedule to DB: %s", e)

    @staticmethod
    def _hash_dsl(dsl_text: str) -> str:
        return hashlib.sha256(dsl_text.encode("utf-8")).hexdigest()

    @staticmethod
    def get_canonical_epg(channel_id: str, window_start: datetime, window_end: datetime) -> list[dict] | None:
        """Read canonical EPG from active ScheduleRevision + ScheduleItems.

        Ordering is authoritative by slot_index ASC.
        """
        from retrovue.domain.entities import Channel, ChannelActiveRevision, ScheduleItem, ScheduleRevision
        try:
            with session() as db:
                channel = db.query(Channel).filter(Channel.slug == channel_id).first()
                if channel is None:
                    return None

                pointers = db.query(ChannelActiveRevision).filter(
                    ChannelActiveRevision.channel_id == channel.id,
                    ChannelActiveRevision.broadcast_day >= window_start.date() - timedelta(days=1),
                    ChannelActiveRevision.broadcast_day <= window_end.date() + timedelta(days=1),
                ).order_by(ChannelActiveRevision.broadcast_day.asc()).all()

                revisions = []
                if pointers:
                    rev_ids = [ptr.schedule_revision_id for ptr in pointers]
                    rev_rows = db.query(ScheduleRevision).filter(
                        ScheduleRevision.id.in_(rev_ids)
                    ).all()
                    rev_map = {r.id: r for r in rev_rows}
                    revisions = [rev_map[rid] for rid in rev_ids if rid in rev_map]

                if not revisions:
                    revisions = db.query(ScheduleRevision).filter(
                        ScheduleRevision.channel_id == channel.id,
                        ScheduleRevision.status == "active",
                        ScheduleRevision.broadcast_day >= window_start.date() - timedelta(days=1),
                        ScheduleRevision.broadcast_day <= window_end.date() + timedelta(days=1),
                    ).order_by(ScheduleRevision.broadcast_day.asc()).all()

                if not revisions:
                    return None

                out=[]
                for rev in revisions:
                    items = (
                        db.query(ScheduleItem)
                        .filter(ScheduleItem.schedule_revision_id == rev.id)
                        .order_by(ScheduleItem.slot_index.asc())
                        .all()
                    )
                    for it in items:
                        block_start = it.start_time
                        block_end = block_start + timedelta(seconds=it.duration_sec)
                        if block_end <= window_start or block_start >= window_end:
                            continue
                        meta = it.metadata_ or {}
                        out.append({
                            "start_at": block_start.isoformat(),
                            "slot_duration_sec": int(it.duration_sec),
                            "asset_id": meta.get("asset_id_raw") or (str(it.asset_id) if it.asset_id else ""),
                            "collection": meta.get("collection_raw") or (str(it.collection_id) if it.collection_id else None),
                            "content_type": it.content_type,
                        })

                return out if out else None
        except Exception as e:
            logger.warning("Failed to read canonical EPG for %s/%s: %s", channel_id, window_start, e)
        return None

    def _compile_day(self, channel_id: str, broadcast_day: str) -> list[ScheduledBlock]:
        """Compile a single broadcast day into filled ScheduledBlocks.
        
        DB-first: checks for a locked cached schedule before compiling.
        Uses deterministic sequential counters based on day offset from epoch,
        so episodes are consistent regardless of compilation order.
        """
        # DB-first: check cache
        cached = self._get_cached_schedule(channel_id, broadcast_day)
        if cached is not None:
            logger.debug("Using cached schedule for %s/%s", channel_id, broadcast_day)
            return self._hydrate_schedule(cached, channel_id, broadcast_day)

        dsl_text = Path(self._dsl_path).read_text()
        dsl = parse_dsl(dsl_text)
        self._channel_dsl = dsl  # cache for traffic policy resolution
        dsl["broadcast_day"] = broadcast_day

        # Use cached resolver (Part 2B: avoid per-compile reload)
        resolver = self._get_resolver()

        # INV-SCHEDULE-SEED-DAY-VARIANCE-001: day-varying deterministic seed
        from retrovue.runtime.schedule_compiler import compilation_seed
        _seed = compilation_seed(channel_id, broadcast_day)

        # Compile program schedule.  Sequential episode progression uses the
        # canonical calendar-based resolver (docs/contracts/episode_progression.md)
        # with persistent ProgressionRun records.
        from retrovue.runtime.progression_run_store import DbProgressionRunStore
        with session() as run_db:
            run_store = DbProgressionRunStore(run_db)
            schedule = compile_schedule(dsl, resolver=resolver, dsl_path=self._dsl_path,
                                         seed=_seed, run_store=run_store)

        # Resolve all plex:// URIs to local file paths
        self._resolve_uris(resolver, schedule)

        # Expand each program block into segmented blocks
        # (content segments + empty filler placeholders)
        blocks = self._expand_schedule_to_blocks(schedule, resolver)

        # INV-SCHEDULE-HORIZON-001: Persist segmented blocks alongside
        # program metadata so Tier 2 (Playlog Horizon Daemon) can consume
        # pre-segmented data without re-expanding.
        schedule["segmented_blocks"] = [
            _serialize_scheduled_block(b) for b in blocks
        ]

        # Save to DB cache (now includes segmented_blocks)
        dsl_hash = self._hash_dsl(dsl_text)
        self._save_compiled_schedule(channel_id, broadcast_day, schedule, dsl_hash)

        return blocks

    def _hydrate_schedule(self, schedule: dict, channel_id: str, broadcast_day: str) -> list[ScheduledBlock]:
        """Hydrate a cached schedule dict into ScheduledBlocks.

        INV-SCHEDULE-HORIZON-001: If segmented_blocks are present in the
        cached schedule, deserialize directly (no re-expansion needed).
        Falls back to expand_program_block if segmented_blocks are absent
        (backward compatibility with pre-Tier-1 cached schedules).
        """
        # Fast path: segmented blocks already cached
        if "segmented_blocks" in schedule and schedule["segmented_blocks"]:
            logger.debug(
                "INV-SCHEDULE-HORIZON-001: Using cached segmented_blocks "
                "for %s/%s (%d blocks)",
                channel_id, broadcast_day, len(schedule["segmented_blocks"]),
            )
            return [_deserialize_scheduled_block(b) for b in schedule["segmented_blocks"]]

        # Slow path: re-expand from program metadata (backward compat)
        logger.info(
            "INV-SCHEDULE-HORIZON-001: No cached segmented_blocks for %s/%s, "
            "falling back to expand",
            channel_id, broadcast_day,
        )
        dsl_text = Path(self._dsl_path).read_text()
        dsl = parse_dsl(dsl_text)
        self._channel_dsl = dsl  # cache for traffic policy resolution
        dsl["broadcast_day"] = broadcast_day

        # Use cached resolver (Part 2B: avoid per-compile reload)
        resolver = self._get_resolver()

        # Register pools
        pools = dsl.get("pools", {})
        if pools and hasattr(resolver, "register_pools"):
            resolver.register_pools(pools)

        # Resolve URIs
        self._resolve_uris(resolver, schedule)

        blocks = self._expand_schedule_to_blocks(schedule, resolver)

        # INV-SCHEDULE-RETENTION-001: Backfill segmented_blocks into the
        # cached Tier 1 row so PlaylistBuilderDaemon can consume them.
        # Without this, stale rows (pre-segmented_blocks) stay stale and
        # the daemon can't pre-fill Tier 2, causing synchronous compiles
        # on the viewer-join path.
        try:
            schedule["segmented_blocks"] = [
                _serialize_scheduled_block(b) for b in blocks
            ]
            dsl_hash = self._hash_dsl(dsl_text)
            self._save_compiled_schedule(channel_id, broadcast_day, schedule, dsl_hash)
            logger.info(
                "INV-SCHEDULE-RETENTION-001: Backfilled segmented_blocks for "
                "%s/%s (%d blocks)",
                channel_id, broadcast_day, len(blocks),
            )
        except Exception as e:
            logger.warning(
                "INV-SCHEDULE-RETENTION-001: Failed to backfill segmented_blocks "
                "for %s/%s: %s",
                channel_id, broadcast_day, e,
            )

        return blocks

    def _expand_schedule_to_blocks(self, schedule: dict, resolver: CatalogAssetResolver) -> list[ScheduledBlock]:
        """Expand compiled program blocks into ScheduledBlocks with empty filler placeholders.

        Produces Tier 1 data: content segments + empty filler placeholders
        (break opportunities). Ad fill happens at Tier 2 (PlaylistBuilderDaemon),
        not here.

        INV-TRAFFIC-LATE-BIND-001: RETIRED — replaced by INV-PLAYLOG-PREFILL-001.
        Ad fill now happens at Tier 2 generation time (2-3h ahead), not at
        feed time. See: docs/architecture/two-tier-horizon.md
        """
        return self._expand_blocks_inner(schedule, resolver)

    def _expand_blocks_inner(self, schedule: dict, resolver: CatalogAssetResolver) -> list[ScheduledBlock]:
        """Inner expand loop -- produces Tier 1 blocks with EMPTY filler placeholders.

        Filler placeholders (segment_type=filler, asset_uri="") are filled by
        PlaylistBuilderDaemon at Tier 2 generation time and written to
        PlaylistEvent. ChannelManager reads filled blocks from PlaylistEvent.

        INV-PLAYLOG-PREFILL-001: Ad selection at Tier 2, not compile time or feed time.
        INV-PRESENTATION-PRECEDES-PRIMARY-001: When compiled_segments contains
        presentation entries, they are hydrated and prepended to the expanded block.
        """
        blocks: list[ScheduledBlock] = []
        for block_def in schedule["program_blocks"]:
            asset_id = block_def["asset_id"]
            meta = resolver.lookup(asset_id)

            dt = datetime.fromisoformat(block_def["start_at"])
            start_utc_ms = int(dt.timestamp() * 1000)

            # Get chapter markers, filter out 0
            chapter_ms = None
            if meta.chapter_markers_sec:
                chapter_ms = tuple(
                    int(c * 1000) for c in meta.chapter_markers_sec if c > 0
                )

            # Resolve asset URI to local path
            asset_uri = self._resolve_uri(meta.file_uri)

            # INV-LOUDNESS-NORMALIZED-001: propagate per-asset loudness gain
            gain_db = meta.loudness_gain_db
            # Rule 5: enqueue background measurement for unmeasured assets
            # Only measure locally-accessible files (absolute paths).
            if (
                gain_db == 0.0
                and asset_uri.startswith("/")
                and resolver.asset_needs_loudness_measurement(asset_id)
            ):
                self._enqueue_loudness_measurement(asset_id, asset_uri)

            # INV-PRESENTATION-PRECEDES-PRIMARY-001: Hydrate presentation segments
            # from compiled_segments and prepend them to the expanded block.
            presentation_segs: list[ScheduledSegment] = []
            compiled_segments = block_def.get("compiled_segments")
            if compiled_segments:
                for cs in compiled_segments:
                    if cs.get("segment_type") == "presentation":
                        pres_id = cs.get("asset_id", "")
                        pres_meta = resolver.lookup(pres_id)
                        pres_uri = self._resolve_uri(pres_meta.file_uri)
                        presentation_segs.append(ScheduledSegment(
                            segment_type="presentation",
                            asset_uri=pres_uri,
                            asset_start_offset_ms=0,
                            segment_duration_ms=int(cs["duration_ms"]),
                        ))

            # INV-BLOCK-SEGMENT-CONSERVATION-001: Presentation segments consume
            # block time.  Subtract their total from the slot budget so
            # content + filler + presentation sums to exactly block_duration_ms.
            full_slot_ms = int(block_def["slot_duration_sec"] * 1000)
            presentation_total_ms = sum(
                s.segment_duration_ms for s in presentation_segs
            )
            content_slot_ms = full_slot_ms - presentation_total_ms

            # Expand into acts + ad breaks (empty filler placeholders — Tier 1 data).
            # INV-PLAYLOG-PREFILL-001: Ad fill happens at Tier 2 (PlaylistBuilderDaemon),
            # not here at compile time and not at feed time.
            expanded = expand_program_block(
                asset_id=asset_id,
                asset_uri=asset_uri,
                start_utc_ms=start_utc_ms,
                slot_duration_ms=content_slot_ms,
                episode_duration_ms=int(block_def["episode_duration_sec"] * 1000),
                chapter_markers_ms=chapter_ms,
                channel_type=self._channel_type,
                gain_db=gain_db,
            )

            # Prepend presentation segments and restore full block duration.
            if presentation_segs:
                from dataclasses import replace
                expanded = replace(
                    expanded,
                    segments=tuple(presentation_segs) + expanded.segments,
                    end_utc_ms=start_utc_ms + full_slot_ms,
                )

            # Carry block-level traffic_profile from DSL through to ScheduledBlock
            tp = block_def.get("traffic_profile")
            if tp:
                from dataclasses import replace
                expanded = replace(expanded, traffic_profile=tp)

            # INV-BLOCK-SEGMENT-CONSERVATION-001: Verify segment sum == block duration.
            block_duration_ms = expanded.end_utc_ms - expanded.start_utc_ms
            sum_segment_ms = sum(
                s.segment_duration_ms for s in expanded.segments
            )
            delta_ms = sum_segment_ms - block_duration_ms
            if delta_ms != 0:
                logger.error(
                    "INV-BLOCK-SEGMENT-CONSERVATION-001 VIOLATION: "
                    "block_id=%s sum_segment_ms=%d block_duration_ms=%d "
                    "delta_ms=%d presentation_ms=%d",
                    expanded.block_id, sum_segment_ms, block_duration_ms,
                    delta_ms, presentation_total_ms,
                )
            else:
                logger.debug(
                    "BLOCK_PLAN_INVARIANT_CHECK block_id=%s "
                    "sum_segment_ms=%d block_duration_ms=%d delta_ms=0",
                    expanded.block_id, sum_segment_ms, block_duration_ms,
                )

            blocks.append(expanded)

        return blocks

    # _get_asset_library removed: ad fill now handled by PlaylistBuilderDaemon (Tier 2).
    # See: INV-PLAYLOG-PREFILL-001, docs/architecture/two-tier-horizon.md

    def _resolve_uris(self, resolver: CatalogAssetResolver, schedule: dict) -> None:
        """Pre-resolve source file paths to local paths using PathMappings.

        No external API calls — all data comes from the database.
        Assets store source file paths in canonical_uri (set during ingest).
        PathMappings translate source prefixes to local prefixes.
        """
        from retrovue.domain.entities import Asset, Collection, PathMapping

        with session() as db:
            # Load all path mappings keyed by collection
            path_mappings: dict[str, list[tuple[str, str]]] = {}
            for col in db.query(Collection).all():
                col_uuid = str(col.uuid)
                pms = db.query(PathMapping).filter(
                    PathMapping.collection_uuid == col.uuid
                ).all()
                if pms:
                    path_mappings[col_uuid] = [(pm.plex_path, pm.local_path) for pm in pms]

            # Resolve each scheduled asset
            for block_def in schedule["program_blocks"]:
                asset_id = block_def["asset_id"]
                meta = resolver.lookup(asset_id)
                uri = meta.file_uri

                if uri in self._uri_cache:
                    continue

                # Normalise file:// prefix
                source_path = uri.replace("file://", "") if uri.startswith("file://") else uri

                # For plex:// URIs that weren't migrated yet, look up canonical_uri
                if uri.startswith("plex://"):
                    asset = db.query(Asset).filter(Asset.uuid == asset_id).first()
                    if asset and asset.canonical_uri and not asset.canonical_uri.startswith("plex://"):
                        source_path = asset.canonical_uri
                    else:
                        logger.warning(
                            "Asset %s has no source file path in canonical_uri; "
                            "re-ingest to populate. URI: %s", asset_id, uri
                        )
                        continue

                # Apply PathMappings: longest-prefix match
                asset_obj = db.query(Asset).filter(Asset.uuid == asset_id).first()
                mapped = False
                if asset_obj:
                    col_uuid = str(asset_obj.collection_uuid)
                    pms = path_mappings.get(col_uuid, [])
                    # Sort by prefix length descending for longest match
                    for plex_prefix, local_prefix in sorted(pms, key=lambda x: len(x[0]), reverse=True):
                        if source_path.startswith(plex_prefix):
                            local_path = local_prefix + source_path[len(plex_prefix):]
                            self._uri_cache[uri] = local_path
                            mapped = True
                            break

                if not mapped:
                    # No mapping matched — use source_path as-is (may already be local)
                    self._uri_cache[uri] = source_path

    def _resolve_uri(self, uri: str) -> str:
        """Resolve a single URI, returning local path or original URI."""
        return self._uri_cache.get(uri, uri)
