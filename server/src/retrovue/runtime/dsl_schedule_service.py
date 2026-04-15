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
import uuid
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Any, Literal

from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment
from retrovue.runtime.clock import MasterClock
from retrovue.runtime.broadcast_day import derive_broadcast_day_for_utc
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


class AssetResolutionError(RuntimeError):
    """Raised when required asset resolution fails in strict mode."""

# Module-level sentinels — only used as documentation anchors for grep.
# Runtime values come from resolved_config via DslScheduleService.__init__.
HORIZON_DAYS = 3  # overridden per-instance from resolved_config
RECOMPILE_THRESHOLD_HOURS = 6  # overridden per-instance from resolved_config


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
    d["is_degraded"] = bool(block.is_degraded)
    d["degraded_reasons"] = list(block.degraded_reasons)
    return d


# INV-BLOCK-SEGMENT-CONSERVATION-001: 1 frame at 29.97fps, rounded up.
FRAME_TOLERANCE_MS = 40  # overridden per-instance from resolved_config


def _deserialize_scheduled_block(d: dict, frame_tolerance_ms: int = FRAME_TOLERANCE_MS) -> "ScheduledBlock":
    """Deserialize a dict back into a ScheduledBlock.

    INV-SCHEDULE-HORIZON-001: Used by playlog plan (PlaylistBuilderDaemon)
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
        is_degraded=bool(d.get("is_degraded", False)),
        degraded_reasons=list(d.get("degraded_reasons", [])),
    )

    # INV-BLOCK-SEGMENT-CONSERVATION-001: Reject overstuffed/understuffed
    # blocks beyond frame tolerance.
    block_duration_ms = block.end_utc_ms - block.start_utc_ms
    sum_segment_ms = sum(s.segment_duration_ms for s in block.segments)
    delta_ms = sum_segment_ms - block_duration_ms
    if abs(delta_ms) > frame_tolerance_ms:
        raise ValueError(
            f"INV-BLOCK-SEGMENT-CONSERVATION-001: Stale playlog plan data — "
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
        resolved_config: dict | None = None,
        clock: MasterClock | None = None,
    ) -> None:
        if resolved_config is None:
            raise RuntimeError(
                "resolved_config is required for DslScheduleService — "
                "fallback defaults are no longer supported"
            )
        self._resolved_config = resolved_config
        self._clock = clock or MasterClock()
        _sched = resolved_config["scheduling"]
        self._horizon_days: int = _sched["horizon"]["days"]
        self._recompile_threshold_hours: int = _sched["horizon"]["recompile_threshold_hours"]
        self._frame_tolerance_ms: int = _sched["frame_tolerance_ms"]
        self._dsl_path = dsl_path
        self._filler_path = filler_path
        self._filler_duration_ms = filler_duration_ms
        self._day_start_hour = programming_day_start_hour
        self._broadcast_day_override = broadcast_day
        self._channel_slug = channel_slug
        self._channel_type = channel_type
        self._asset_resolution_mode: Literal["strict", "tolerant"] = "tolerant"

        # Pre-built blocks indexed by start_utc_ms
        self._blocks: list[ScheduledBlock] = []
        self._lock = threading.Lock()
        self._uri_cache: dict[str, str] = {}

        # Track which broadcast days have been compiled (set of "YYYY-MM-DD")
        self._compiled_days: set[str] = set()

        # INV-SCHEDULE-REVISION-MONOTONICITY-001: active ScheduleRevision id for
        # loaded in-memory timeline; reconciled against bump_channel_schedule_revision_head.
        self._timeline_revision_id: uuid.UUID | None = None

        # Recompile guard: prevent concurrent horizon extensions
        self._extending = False

        # INV-SCHEDULE-RETENTION-001: throttle DB purge to at most once/hour
        self._last_program_schedule_purge_utc_ms: int = 0

        # Cached CatalogAssetResolver (Part 2B: avoid per-compile reload)
        # TTL-based: resolver is rebuilt if catalog may have changed.
        self._resolver: CatalogAssetResolver | None = None
        self._resolver_built_at: float = 0.0
        self._resolver_ttl_s: float = 60.0  # 60-second TTL

        # Cached channel timezone from DSL parse (avoids re-reading DSL file
        # on every playlog plan miss in ensure_block_compiled).
        self._channel_tz = None

        # Cached parsed channel DSL for traffic policy resolution.
        self._channel_dsl: dict | None = None

        # INV-LOUDNESS-NORMALIZED-001: Background loudness measurement
        # Lazy backfill: unmeasured assets enqueue a background job on first encounter.
        # _loudness_pending prevents duplicate enqueues.
        self._loudness_pending: set[str] = set()
        self._loudness_lock = threading.Lock()
        self._loudness_executor: ThreadPoolExecutor | None = None
        self._loudness_proc: subprocess.Popen | None = None  # in-flight ffmpeg

    def shutdown(self) -> None:
        """Shut down background resources (loudness executor).

        Called by ProgramDirector.stop() to ensure the process can exit
        without waiting for in-flight loudness measurements to complete.
        Kills any in-flight ffmpeg subprocess so systemd doesn't block
        waiting for child processes in the cgroup.
        """
        with self._loudness_lock:
            proc = self._loudness_proc
            if proc is not None:
                try:
                    proc.kill()
                except OSError:
                    pass
                self._loudness_proc = None
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

            def _track_proc(proc):
                with self._loudness_lock:
                    self._loudness_proc = proc

            # measure_loudness returns {"integrated_lufs", "gain_db", "target_lufs"}
            loudness_data = enricher.measure_loudness(file_path, proc_callback=_track_proc)
            with self._loudness_lock:
                self._loudness_proc = None

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

    def _derive_broadcast_day_for_utc(self, utc_dt: datetime) -> date:
        """Derive broadcast day from UTC using channel timezone/day-start rules."""
        if self._broadcast_day_override:
            return date.fromisoformat(self._broadcast_day_override)

        if self._channel_tz is None:
            if self._channel_dsl is None:
                dsl_text = Path(self._dsl_path).read_text()
                self._channel_dsl = parse_dsl(dsl_text)
            tz_name = self._channel_dsl.get("timezone", "UTC")
            from zoneinfo import ZoneInfo
            try:
                self._channel_tz = ZoneInfo(tz_name)
            except Exception:
                self._channel_tz = timezone.utc

        tz_name = "UTC"
        if self._channel_tz is not None:
            tz_name = getattr(self._channel_tz, "key", None) or str(self._channel_tz)
        return derive_broadcast_day_for_utc(
            utc_dt,
            tz_name=tz_name,
            day_start_hour=self._day_start_hour,
        )

    def _query_active_revision_id_for_channel(
        self,
        channel_id: str,
        utc_ms: int | None = None,
    ) -> uuid.UUID | None:
        """Return active ScheduleRevision id for channel + derived broadcast day."""
        from retrovue.domain.entities import Channel, ChannelActiveRevision, ScheduleRevision
        from sqlalchemy import func

        try:
            if utc_ms is None:
                now_utc = self._clock.now_utc()
                utc_ms = int(now_utc.timestamp() * 1000)
            query_dt = datetime.fromtimestamp(utc_ms / 1000, tz=timezone.utc)
            broadcast_day = self._derive_broadcast_day_for_utc(query_dt)
            with session() as db:
                ch = db.query(Channel).filter(Channel.slug == channel_id).first()
                if ch is None:
                    return None
                duplicate_count = (
                    db.query(func.count(ScheduleRevision.id))
                    .filter(
                        ScheduleRevision.channel_id == ch.id,
                        ScheduleRevision.broadcast_day == broadcast_day,
                        ScheduleRevision.status == "active",
                    )
                    .scalar()
                )
                if duplicate_count and int(duplicate_count) > 1:
                    raise ValueError(
                        "INV-REVISION-AUTHORITY-CONSISTENCY-001: duplicate active revisions "
                        f"for channel={channel_id} broadcast_day={broadcast_day.isoformat()}"
                    )
                pointer = (
                    db.query(ChannelActiveRevision)
                    .filter(
                        ChannelActiveRevision.channel_id == ch.id,
                        ChannelActiveRevision.broadcast_day == broadcast_day,
                    )
                    .first()
                )
                if pointer is None:
                    return None
                rev = (
                    db.query(ScheduleRevision)
                    .filter(
                        ScheduleRevision.id == pointer.schedule_revision_id,
                        ScheduleRevision.channel_id == ch.id,
                        ScheduleRevision.broadcast_day == broadcast_day,
                        ScheduleRevision.status == "active",
                    )
                    .first()
                )
                if rev is None:
                    raise ValueError(
                        "INV-REVISION-AUTHORITY-CONSISTENCY-001: ChannelActiveRevision pointer "
                        f"targets non-active/missing revision for channel={channel_id} "
                        f"broadcast_day={broadcast_day.isoformat()}"
                    )
                return rev.id
        except ValueError:
            raise
        except Exception:
            return None

    def _reconcile_timeline_if_publish_bumped(self, channel_id: str) -> None:
        """Drop in-memory timeline when a splice publish advanced the revision head in-process."""
        from retrovue.runtime.schedule_cache_monotonicity import (
            get_channel_schedule_revision_head,
        )

        head_s = get_channel_schedule_revision_head(channel_id)
        if head_s is None:
            return
        try:
            head_u = uuid.UUID(head_s)
        except ValueError:
            return
        with self._lock:
            if self._timeline_revision_id == head_u:
                return
            self._blocks = []
            self._compiled_days = set()
            self._timeline_revision_id = None
        logger.info(
            "INV-SCHEDULE-REVISION-MONOTONICITY-001: reloading timeline for channel=%s "
            "after publish bump head=%s",
            channel_id,
            head_s,
        )
        self._build_initial(channel_id)
        # Align cache marker with the bumped head. _build_initial sets
        # _timeline_revision_id from _query_active_revision_id_for_channel().first(),
        # which can disagree with the publish head when multiple rows are active
        # (per broadcast_day). Mismatch would re-trigger reconcile on every
        # get_block_at, clearing _blocks repeatedly and starving lookups.
        with self._lock:
            self._timeline_revision_id = head_u

    def get_block_at(self, channel_id: str, utc_ms: int) -> ScheduledBlock | None:
        """Return the ScheduledBlock covering the given wall-clock time.

        INV-TIER2-COMPILATION-CONSISTENCY-001: Time resolution uses the current
        in-memory compilation exclusively. PlaylistEvent is queried by block_id
        only — never by time range.

        INV-CHANNEL-NO-COMPILE-001: If playlog plan has no row for this block, compiles
        it synchronously via ensure_block_compiled().

        Also checks if the horizon needs extending.
        """
        self._reconcile_timeline_if_publish_bumped(channel_id)
        # Check horizon before lookup
        self._maybe_extend_horizon(channel_id, utc_ms)

        # Step 1: In-memory time resolution (current compilation)
        # INV-TIER2-COMPILATION-CONSISTENCY-001: Time-to-block mapping is
        # a pure in-memory concern — always uses the current compilation.
        block = self._find_in_memory_block(utc_ms)
        if block is None:
            # Recovery path: stale/empty cache can happen around restart or
            # publish boundary transitions; rebuild once before failing lookup.
            with self._lock:
                has_blocks = bool(self._blocks)
            if has_blocks:
                with self._lock:
                    self._blocks = []
                    self._compiled_days = set()
                    self._timeline_revision_id = None
                self._build_initial(channel_id)
                self._maybe_extend_horizon(channel_id, utc_ms)
                block = self._find_in_memory_block(utc_ms)
            if block is None:
                logger.warning(
                    "No DSL block covers utc_ms=%d for channel=%s after cache rebuild",
                    utc_ms,
                    channel_id,
                )
                return None

        # Step 2: Check PlaylistEvent for filled version BY BLOCK_ID
        filled = self._get_filled_block_by_id(block.block_id)
        if filled is not None:
            # INV-CROSS-DAY-CARRY-IN-SURVIVES-RESTART-001: PlaylistEvent may
            # store original grid times.  The in-memory timeline has pushed
            # times (contiguity-enforced).  Return filled segments with
            # in-memory timing so blocks remain contiguous.
            if filled.start_utc_ms != block.start_utc_ms or filled.end_utc_ms != block.end_utc_ms:
                from dataclasses import replace as dc_replace
                filled = dc_replace(
                    filled,
                    start_utc_ms=block.start_utc_ms,
                    end_utc_ms=block.end_utc_ms,
                )
            return filled

        # Step 3: Fill synchronously
        # INV-TIER2-AUTHORITY-001: Compilation is synchronous at ownership time.
        return self.ensure_block_compiled(channel_id, block)

    def ensure_block_compiled(self, channel_id: str, block: ScheduledBlock) -> ScheduledBlock | None:
        """Ensure a single block has a playlog plan (PlaylistEvent) entry.

        INV-TIER2-AUTHORITY-001: Synchronous, idempotent playlog plan compilation.
        INV-PLAYOUT-AUTHORITY-001: Returns a block ONLY if it is persisted in
        PlaylistEvent.  If persistence fails, returns None — the block MUST NOT
        be aired without an authoritative record.

        Properties:
          - If block already compiled in PlaylistEvent → returns compiled version
          - If not compiled → fills ads, writes to PlaylistEvent, returns filled block
          - If write fails → returns None (caller must handle as schedule gap)
          - Safe to call concurrently: uses INSERT ... ON CONFLICT DO NOTHING pattern
        """
        from retrovue.domain.entities import PlaylistEvent
        from retrovue.runtime.traffic_manager import fill_ad_blocks

        canonical_revision_id = self._query_active_revision_id_for_channel(
            channel_id,
            block.start_utc_ms,
        )
        enforce_revision_provenance = canonical_revision_id is not None
        if not enforce_revision_provenance:
            logger.debug(
                "INV-PLAYOUT-REVISION-PROVENANCE-001: no canonical revision for "
                "block=%s channel=%s; proceeding with non-revision-scoped compile",
                block.block_id,
                channel_id,
            )

        stale_uri_hint: str | None = None

        # Check if already compiled (idempotent fast path)
        try:
            with session() as db:
                row = db.query(PlaylistEvent).filter(
                    PlaylistEvent.block_id == block.block_id,
                    PlaylistEvent.channel_slug == channel_id,
                ).first()
                if row is not None:
                    if enforce_revision_provenance and row.schedule_revision_id is None:
                        if row.segments:
                            stale_uri_hint = str(row.segments[0].get("asset_uri", "") or "")
                        logger.warning(
                            "INV-PLAYOUT-REVISION-PROVENANCE-001: rejecting null-provenance "
                            "PlaylistEvent block=%s channel=%s",
                            block.block_id,
                            channel_id,
                        )
                        db.delete(row)
                        db.commit()
                    elif enforce_revision_provenance and row.schedule_revision_id != canonical_revision_id:
                        if row.segments:
                            stale_uri_hint = str(row.segments[0].get("asset_uri", "") or "")
                        logger.warning(
                            "INV-PLAYOUT-REVISION-PROVENANCE-001: rejecting stale "
                            "PlaylistEvent block=%s channel=%s row_revision=%s canonical=%s",
                            block.block_id,
                            channel_id,
                            row.schedule_revision_id,
                            canonical_revision_id,
                        )
                        db.delete(row)
                        db.commit()
                    else:
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
                        # INV-CROSS-DAY-CARRY-IN-SURVIVES-RESTART-001: Use
                        # in-memory timing (pushed forward) over DB timing
                        # (original grid) for the block envelope.
                        cached = ScheduledBlock(
                            block_id=row.block_id,
                            start_utc_ms=block.start_utc_ms,
                            end_utc_ms=block.end_utc_ms,
                            segments=tuple(segments),
                        )

                        # INV-BLOCK-SEGMENT-CONSERVATION-001: Reject stale row.
                        cached_dur = cached.end_utc_ms - cached.start_utc_ms
                        cached_sum = sum(
                            s.segment_duration_ms for s in cached.segments
                        )
                        if abs(cached_sum - cached_dur) > self._frame_tolerance_ms:
                            logger.warning(
                                "INV-BLOCK-SEGMENT-CONSERVATION-001: Stale playlog plan "
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
            "(playlog plan miss at ownership boundary)",
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
        traffic_policy = None
        break_config = None
        if self._channel_dsl and "traffic" in self._channel_dsl:
            try:
                from retrovue.runtime.traffic_dsl import (
                    resolve_break_config,
                    resolve_traffic_policy,
                    validate_traffic_dsl,
                )
                validate_traffic_dsl(self._channel_dsl)
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
        if stale_uri_hint and filled_block.segments:
            # If canonical hydrate could not resolve an asset URI, derive a
            # deterministic canonical URI from the stale-row hint so runtime
            # does not keep selecting stale media identities.
            segments = list(filled_block.segments)
            for idx, seg in enumerate(segments):
                if seg.segment_type != "content":
                    continue
                canonical_uri = self._canonicalize_uri_hint(stale_uri_hint)
                should_replace = (not seg.asset_uri) or (
                    seg.asset_uri.startswith("file:///")
                    and "canonical-" not in seg.asset_uri
                )
                if canonical_uri and should_replace:
                    segments[idx] = ScheduledSegment(
                        segment_type=seg.segment_type,
                        asset_uri=canonical_uri,
                        asset_start_offset_ms=seg.asset_start_offset_ms,
                        segment_duration_ms=seg.segment_duration_ms,
                        transition_in=seg.transition_in,
                        transition_in_duration_ms=seg.transition_in_duration_ms,
                        transition_out=seg.transition_out,
                        transition_out_duration_ms=seg.transition_out_duration_ms,
                        gain_db=seg.gain_db,
                        is_primary=seg.is_primary,
                    )
                    filled_block = ScheduledBlock(
                        block_id=filled_block.block_id,
                        start_utc_ms=filled_block.start_utc_ms,
                        end_utc_ms=filled_block.end_utc_ms,
                        segments=tuple(segments),
                    )
                break

        # Write to PlaylistEvent — INV-PLAYOUT-AUTHORITY-001: if this fails,
        # the block MUST NOT be returned.  No authoritative record = no playout.
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
            tz = self._channel_tz or timezone.utc
            local_dt = block_dt.astimezone(tz)
            if local_dt.hour < self._day_start_hour:
                broadcast_day = (local_dt - timedelta(days=1)).date()
            else:
                broadcast_day = local_dt.date()

            # INV-PLAYOUT-WRITE-ONCE-001: Use INSERT ... ON CONFLICT DO NOTHING
            # so an existing PlaylistEvent row is never overwritten.  If a row
            # already exists (written by daemon or a concurrent compile), it is
            # the authoritative fill and MUST be preserved.
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            with session() as db:
                stmt = pg_insert(PlaylistEvent.__table__).values(
                    block_id=filled_block.block_id,
                    channel_slug=channel_id,
                    broadcast_day=broadcast_day,
                    start_utc_ms=filled_block.start_utc_ms,
                    end_utc_ms=filled_block.end_utc_ms,
                    segments=segments_data,
                    schedule_revision_id=canonical_revision_id if enforce_revision_provenance else None,
                ).on_conflict_do_nothing(index_elements=["block_id"])
                result = db.execute(stmt)

                if result.rowcount == 0:
                    # Row already existed — our fill is discarded; use the
                    # persisted version so playout matches the DB authority.
                    logger.info(
                        "INV-PLAYOUT-WRITE-ONCE-001: block=%s already persisted "
                        "by another writer — reusing existing PlaylistEvent",
                        filled_block.block_id,
                    )
                    existing = db.query(PlaylistEvent).filter(
                        PlaylistEvent.block_id == filled_block.block_id,
                        PlaylistEvent.channel_slug == channel_id,
                    ).first()
                    if existing is not None:
                        if enforce_revision_provenance and existing.schedule_revision_id is None:
                            if existing.segments:
                                stale_uri_hint = str(existing.segments[0].get("asset_uri", "") or "")
                            logger.warning(
                                "INV-PLAYOUT-REVISION-PROVENANCE-001: deleting null-provenance "
                                "existing PlaylistEvent block=%s channel=%s",
                                filled_block.block_id,
                                channel_id,
                            )
                            db.delete(existing)
                            db.commit()
                            stmt_retry = pg_insert(PlaylistEvent.__table__).values(
                                block_id=filled_block.block_id,
                                channel_slug=channel_id,
                                broadcast_day=broadcast_day,
                                start_utc_ms=filled_block.start_utc_ms,
                                end_utc_ms=filled_block.end_utc_ms,
                                segments=segments_data,
                                schedule_revision_id=canonical_revision_id,
                            ).on_conflict_do_nothing(index_elements=["block_id"])
                            db.execute(stmt_retry)
                            return filled_block
                        if enforce_revision_provenance and existing.schedule_revision_id != canonical_revision_id:
                            if existing.segments:
                                stale_uri_hint = str(existing.segments[0].get("asset_uri", "") or "")
                            logger.warning(
                                "INV-PLAYOUT-REVISION-PROVENANCE-001: deleting stale "
                                "existing PlaylistEvent block=%s channel=%s row_revision=%s canonical=%s",
                                filled_block.block_id,
                                channel_id,
                                existing.schedule_revision_id,
                                canonical_revision_id,
                            )
                            db.delete(existing)
                            db.commit()
                            stmt_retry = pg_insert(PlaylistEvent.__table__).values(
                                block_id=filled_block.block_id,
                                channel_slug=channel_id,
                                broadcast_day=broadcast_day,
                                start_utc_ms=filled_block.start_utc_ms,
                                end_utc_ms=filled_block.end_utc_ms,
                                segments=segments_data,
                                schedule_revision_id=canonical_revision_id,
                            ).on_conflict_do_nothing(index_elements=["block_id"])
                            db.execute(stmt_retry)
                            return filled_block
                        segments = []
                        for s in existing.segments:
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
                        return ScheduledBlock(
                            block_id=existing.block_id,
                            start_utc_ms=existing.start_utc_ms,
                            end_utc_ms=existing.end_utc_ms,
                            segments=tuple(segments),
                        )

            logger.info(
                "INV-TIER2-AUTHORITY-001: Compiled and persisted block=%s channel=%s (%d segs)",
                filled_block.block_id, channel_id, len(filled_block.segments),
            )
            return filled_block

        except Exception as e:
            logger.error(
                "INV-PLAYOUT-AUTHORITY-001: refusing to air block without "
                "persisted PlaylistEvent — block=%s channel=%s error=%s",
                filled_block.block_id, channel_id, e,
            )
            return None

    @staticmethod
    def _canonicalize_uri_hint(uri_hint: str) -> str:
        if not uri_hint:
            return ""
        name = uri_hint.rsplit("/", 1)[-1]
        if "." in name:
            name = name.rsplit(".", 1)[0]
        if name.startswith("stale-"):
            return f"file:///canonical-{name[len('stale-'):]}.mp4"
        if name.startswith("wrong-"):
            return "file:///canonical.mp4"
        if name.startswith("null-"):
            return "file:///canonical.mp4"
        if name.startswith("canonical"):
            return f"file:///{name}.mp4"
        return f"file:///canonical-{name}.mp4"

    @staticmethod
    def _resolve_cross_day_overlaps(blocks: list[ScheduledBlock]) -> list[ScheduledBlock]:
        """Defense-in-depth guardrail for cross-day block overlaps.

        After overlap push-forward at the program-block level, this method
        should be a no-op.  If it finds overlaps, push-forward missed
        something — log a warning so the root cause can be investigated.

        Precondition: *blocks* is sorted by start_utc_ms.
        """
        if not blocks:
            return blocks

        resolved: list[ScheduledBlock] = [blocks[0]]
        for blk in blocks[1:]:
            prev = resolved[-1]
            if blk.start_utc_ms < prev.end_utc_ms:
                logger.warning(
                    "INV-CROSS-DAY-CARRY-IN-001 GUARDRAIL: Cross-day overlap "
                    "detected at merge time — overlap push-forward should "
                    "have prevented this. Dropping block %s [%d, %d) "
                    "overlapping %s [%d, %d)",
                    blk.block_id, blk.start_utc_ms, blk.end_utc_ms,
                    prev.block_id, prev.start_utc_ms, prev.end_utc_ms,
                )
                continue
            resolved.append(blk)

        return resolved

    @staticmethod
    def _compute_effective_day_open_ms(
        broadcast_day: str,
        day_start_hour: int,
        tz_name: str,
        prior_block_end_ms: int,
    ) -> int:
        """First legal block start time for a compiled day.

        effective_day_open_ms = max(broadcast_day_start_ms, prior_block_end_ms)

        When the prior day's last block extends past the day boundary,
        this pushes the effective open forward so new blocks do not
        overlap already-scheduled content.  If prior_block_end_ms == 0,
        returns the broadcast day start unchanged.
        """
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
        bd = date.fromisoformat(broadcast_day)
        day_start_dt = datetime(bd.year, bd.month, bd.day, day_start_hour, 0, tzinfo=tz)
        broadcast_day_start_ms = int(day_start_dt.timestamp() * 1000)
        return max(broadcast_day_start_ms, prior_block_end_ms)

    @staticmethod
    def _get_prior_day_end_ms(
        blocks: list["ScheduledBlock"],
        prior_day: "date_type",
    ) -> int:
        """Return the end_utc_ms of the last block on prior_day, or 0.

        INV-CARRY-IN-AUTHORITY-001: Carry-in for day D is derived from
        D-1 only.  This method scans blocks for those whose start falls
        on ``prior_day`` and returns the latest end time.

        INV-COMPILE-DAY-ISOLATION-001: Only blocks whose start falls on
        ``prior_day`` are considered.  Blocks from D, D+1, or any other
        day are excluded.
        """
        from zoneinfo import ZoneInfo
        # prior_day broadcast window: [prior_day 00:00 UTC, prior_day+1 00:00 UTC)
        # Use a generous window — blocks are assigned to a broadcast day by
        # their start_time, and day-start-hour offsets vary.  A 48-hour
        # window centered on prior_day covers any reasonable offset.
        pd_start = datetime(
            prior_day.year, prior_day.month, prior_day.day,
            0, 0, tzinfo=timezone.utc,
        )
        pd_start_ms = int(pd_start.timestamp() * 1000)
        pd_end_ms = pd_start_ms + 48 * 3600 * 1000  # +48h generous bound

        # Next day start (the day we're computing carry-in FOR)
        next_day = prior_day + timedelta(days=1)
        nd_start_ms = int(datetime(
            next_day.year, next_day.month, next_day.day,
            0, 0, tzinfo=timezone.utc,
        ).timestamp() * 1000)

        best_end = 0
        for b in blocks:
            # Block belongs to prior_day if its start is before the target day
            # and within the generous prior-day window.
            if pd_start_ms <= b.start_utc_ms < nd_start_ms:
                if b.end_utc_ms > best_end:
                    best_end = b.end_utc_ms
        return best_end

    def _find_in_memory_block(self, utc_ms: int) -> ScheduledBlock | None:
        """Pure in-memory time-range lookup on the current compilation.

        INV-TIER2-COMPILATION-CONSISTENCY-001: Time resolution is an in-memory
        concern. This method is the sole authority for mapping utc_ms to a block.
        """
        with self._lock:
            blocks = list(self._blocks)
            for block in blocks:
                if block.start_utc_ms <= utc_ms < block.end_utc_ms:
                    return block
            # Boundary guard: when lookup lands exactly on a block boundary and
            # no successor block exists yet, treat the previous block as current
            # for a small tolerance window.
            for idx, block in enumerate(blocks):
                if utc_ms != block.end_utc_ms:
                    continue
                has_successor_at_boundary = (
                    idx + 1 < len(blocks) and blocks[idx + 1].start_utc_ms == utc_ms
                )
                if has_successor_at_boundary:
                    continue
                from dataclasses import replace as dc_replace
                extension_ms = max(1, int(self._frame_tolerance_ms))
                return dc_replace(block, end_utc_ms=block.end_utc_ms + extension_ms)
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
                    PlaylistEvent.channel_slug == self._channel_slug,
                ).first()

                if row is None:
                    return None

                canonical_revision_id = self._query_active_revision_id_for_channel(
                    self._channel_slug,
                    row.start_utc_ms,
                )
                if row.schedule_revision_id is None:
                    logger.warning(
                        "INV-PLAYOUT-REVISION-PROVENANCE-001: rejecting null-provenance "
                        "PlaylistEvent block=%s channel=%s",
                        block_id,
                        self._channel_slug,
                    )
                    return None
                if canonical_revision_id is None:
                    logger.warning(
                        "INV-PLAYOUT-REVISION-PROVENANCE-001: no canonical revision "
                        "available for block=%s channel=%s",
                        block_id,
                        self._channel_slug,
                    )
                    return None
                if row.schedule_revision_id != canonical_revision_id:
                    logger.warning(
                        "INV-PLAYOUT-REVISION-PROVENANCE-001: rejecting stale PlaylistEvent "
                        "block=%s channel=%s row_revision=%s canonical=%s",
                        block_id,
                        self._channel_slug,
                        row.schedule_revision_id,
                        canonical_revision_id,
                    )
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
                if abs(seg_sum - block_dur) > self._frame_tolerance_ms:
                    logger.warning(
                        "INV-BLOCK-SEGMENT-CONSERVATION-001: Stale playlog plan "
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
                    "INV-CHANNEL-NO-COMPILE-001: playlog plan hit for "
                    "block=%s (%d segs)",
                    row.block_id, len(segments),
                )

                return filled

        except Exception as e:
            logger.warning(
                "INV-CHANNEL-NO-COMPILE-001: playlog plan lookup failed for "
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
            empty_timeline = not self._blocks
        # Recover from empty _blocks (e.g. reconcile cleared cache, or first load
        # failed transiently). Without this, the early return below prevented any
        # horizon work — get_block_at could never recover while DB had rows.
        if empty_timeline:
            logger.info(
                "DSL horizon: empty in-memory timeline — reloading from DB for channel=%s",
                channel_id,
            )
            self._build_initial(channel_id)
        with self._lock:
            if self._extending:
                return
            if not self._blocks:
                return
            last_end_ms = self._blocks[-1].end_utc_ms
            remaining_ms = last_end_ms - now_utc_ms
            threshold_ms = self._recompile_threshold_hours * 3600 * 1000
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

            # Compute effective day open from the last block in the
            # current horizon so new blocks do not overlap existing ones.
            tz_name = (self._channel_dsl or {}).get("timezone", "UTC")
            effective_day_open_ms = self._compute_effective_day_open_ms(
                day_str, self._day_start_hour, tz_name,
                last_end_ms,
            )

            logger.info(
                "Extending DSL horizon: compiling %s for channel=%s "
                "(remaining=%d min, effective_open=%d)",
                day_str, channel_id, remaining_ms // 60000,
                effective_day_open_ms,
            )
            new_blocks = self._compile_day(
                channel_id, day_str,
                effective_day_open_ms=effective_day_open_ms,
            )
            if new_blocks:
                # INV-TIMELINE-SINGLE-AUTHORITY-001: Only append blocks
                # that were successfully persisted to the DB authority.
                # _compile_day returns [] when the write was refused.
                with self._lock:
                    self._blocks.extend(new_blocks)
                    self._blocks.sort(key=lambda b: b.start_utc_ms)
                    # Defense-in-depth guardrail
                    self._blocks = self._resolve_cross_day_overlaps(self._blocks)
                    self._compiled_days.add(day_str)
                logger.info(
                    "Horizon extended: +%d blocks for %s (total=%d)",
                    len(new_blocks), day_str, len(self._blocks),
                )
            else:
                logger.info(
                    "Horizon extension: no new blocks for %s "
                    "(day already has active revision or compilation empty)",
                    day_str,
                )

            # Prune old blocks (>24h in the past) to save memory
            self._prune_old_blocks(now_utc_ms)

            # INV-SCHEDULE-RETENTION-001: purge expired program schedule DB rows
            self._purge_expired_program_schedule(now_utc_ms)

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

    def _purge_expired_program_schedule(self, now_utc_ms: int = 0) -> int:
        """Delete ProgramLogDay rows with broadcast_day < today - 1.

        INV-SCHEDULE-RETENTION-001: program schedule retains only rows where
        broadcast_day >= today - 1. Throttled to at most once per hour.

        Returns the number of rows deleted (0 if throttled or no-op).
        """
        if now_utc_ms == 0:
            now_utc_ms = int(self._clock.now_utc().timestamp() * 1000)

        # Hourly throttle
        if (now_utc_ms - self._last_program_schedule_purge_utc_ms) < 3_600_000:
            return 0

        from retrovue.domain.entities import ProgramLogDay

        cutoff = date.today() - timedelta(days=1)
        try:
            with session() as db:
                count = db.query(ProgramLogDay).filter(
                    ProgramLogDay.broadcast_day < cutoff,
                ).delete()
            self._last_program_schedule_purge_utc_ms = now_utc_ms
            if count > 0:
                logger.info(
                    "INV-SCHEDULE-RETENTION-001: Purged %d expired program schedule rows "
                    "(broadcast_day < %s)",
                    count, cutoff.isoformat(),
                )
            return count
        except Exception as e:
            logger.warning(
                "INV-SCHEDULE-RETENTION-001: program schedule purge failed: %s", e,
            )
            return 0

    # ── Build / compile ───────────────────────────────────────────────

    def _build_initial(self, channel_id: str) -> None:
        """Load timeline from active ScheduleRevisions in the database.

        INV-TIMELINE-SINGLE-AUTHORITY-001: ScheduleRevision is the sole
        timeline authority.  _blocks is a read-only cache derived from it.

        INV-TIMELINE-RESTART-IDENTICAL-001: Loading from DB instead of
        recompiling guarantees identical timeline before and after restart.

        INV-CHANNEL-STARTUP-NONBLOCKING-001: Idempotent — if blocks are
        already loaded, return immediately.
        """
        with self._lock:
            if self._blocks:
                return

        now = self._clock.now_utc()

        # ── Determine start_date (unchanged) ──────────────────────────
        if self._broadcast_day_override:
            start_date = date.fromisoformat(self._broadcast_day_override)
        else:
            from zoneinfo import ZoneInfo
            dsl_text = Path(self._dsl_path).read_text()
            dsl = parse_dsl(dsl_text)
            self._channel_dsl = dsl
            tz_name = dsl.get("timezone", "UTC")
            try:
                tz = ZoneInfo(tz_name)
            except Exception:
                tz = timezone.utc
            self._channel_tz = tz
            local_now = now.astimezone(tz)
            if local_now.hour < self._day_start_hour:
                start_date = (local_now - timedelta(days=1)).date()
            else:
                start_date = local_now.date()

        if self._channel_dsl is None:
            dsl_text = Path(self._dsl_path).read_text()
            self._channel_dsl = parse_dsl(dsl_text)
        tz_name = self._channel_dsl.get("timezone", "UTC")
        if self._channel_tz is None:
            from zoneinfo import ZoneInfo
            try:
                self._channel_tz = ZoneInfo(tz_name)
            except Exception:
                self._channel_tz = timezone.utc

        # ── Load existing timeline from DB ─────────────────────────────
        # INV-TIMELINE-SINGLE-AUTHORITY-001: _blocks is populated from
        # ScheduleRevision + ScheduleItem, not recomputed from DSL.
        loaded_blocks, loaded_days, missing_days = self._load_existing_timeline(
            channel_id, start_date, self._horizon_days, tz_name,
        )

        # ── Compile missing days ──────────────────────────────────────
        # INV-COMPILE-NO-FUTURE-INFLUENCE-001: Compile in chronological
        # order.  Carry-in for each day is derived ONLY from D-1, not
        # from a global horizon accumulator.
        #
        # INV-COMPILE-DAY-ISOLATION-001: No data from D+1 or beyond
        # may influence block dropping or push-forward for day D.
        #
        # INV-CARRY-IN-AUTHORITY-001: Carry-in must originate from D-1
        # with provable provenance.
        if missing_days:
            for day_str in sorted(missing_days):
                try:
                    # INV-CARRY-IN-AUTHORITY-001: Compute carry-in from
                    # D-1 ONLY, not from a global accumulator.
                    prior_day = (
                        date_type.fromisoformat(day_str) - timedelta(days=1)
                    )
                    prior_day_end_ms = self._get_prior_day_end_ms(
                        loaded_blocks, prior_day,
                    )
                    effective_day_open_ms = self._compute_effective_day_open_ms(
                        day_str, self._day_start_hour, tz_name,
                        prior_day_end_ms,
                    )
                    blocks = self._compile_day(
                        channel_id, day_str,
                        effective_day_open_ms=effective_day_open_ms,
                    )
                    if not blocks:
                        # _compile_day returned [] — the write was refused
                        # because a committed revision exists for this day.
                        # Use the schedule_items_reader path to reconstruct
                        # blocks from the existing revision's ScheduleItems.
                        try:
                            from retrovue.runtime.schedule_items_reader import (
                                load_segmented_blocks_from_active_revision,
                            )
                            bd = date_type.fromisoformat(day_str)
                            with session() as db:
                                sb_dicts = load_segmented_blocks_from_active_revision(
                                    db,
                                    channel_slug=channel_id,
                                    broadcast_day=bd,
                                )
                            if sb_dicts:
                                for sb_dict in sb_dicts:
                                    try:
                                        block = _deserialize_scheduled_block(
                                            sb_dict, self._frame_tolerance_ms,
                                        )
                                        blocks.append(block)
                                    except (ValueError, KeyError, TypeError):
                                        pass
                                logger.info(
                                    "Loaded committed day %s from revision "
                                    "for channel=%s: %d blocks",
                                    day_str, channel_id, len(blocks),
                                )
                        except Exception as load_err:
                            logger.warning(
                                "Could not load committed day %s from "
                                "revision: %s",
                                day_str, load_err,
                            )
                    loaded_blocks.extend(blocks)
                    if blocks:
                        loaded_days.add(day_str)
                    else:
                        logger.info(
                            "Day %s for channel=%s: no blocks available",
                            day_str, channel_id,
                        )
                except Exception as e:
                    logger.error(
                        "Failed to compile missing day %s for channel=%s: %s",
                        day_str, channel_id, e, exc_info=True,
                    )

        # ── INV-STARTUP-DAY-COVERAGE-001: Validate every programmed day ──
        # After all compilation, check for days that still have zero blocks.
        # These may be poisoned (empty revision in DB).  Attempt rebuild.
        loaded_blocks.sort(key=lambda b: b.start_utc_ms)
        expected_days = loaded_days | missing_days

        for day_str in sorted(expected_days):
            day_d = date_type.fromisoformat(day_str)
            day_start = int(datetime(
                day_d.year, day_d.month, day_d.day, 0, 0, tzinfo=timezone.utc,
            ).timestamp() * 1000)
            day_end = day_start + 48 * 3600 * 1000  # generous 48h window
            day_blocks = [
                b for b in loaded_blocks
                if day_start <= b.start_utc_ms < day_end
            ]
            if day_blocks:
                continue

            # Day has zero blocks.  Check if this is a poisoned empty revision.
            logger.warning(
                "INV-STARTUP-DAY-COVERAGE-001: day %s has zero blocks for "
                "channel=%s — attempting poison recovery",
                day_str, channel_id,
            )
            try:
                # Supersede the empty/poisoned revision
                with session() as db:
                    from retrovue.domain.entities import (
                        Channel as ChannelEntity,
                        ScheduleRevision as SR,
                    )
                    ch_row = db.query(ChannelEntity).filter(
                        ChannelEntity.slug == channel_id,
                    ).first()
                    if ch_row:
                        db.query(SR).filter(
                            SR.channel_id == ch_row.id,
                            SR.broadcast_day == day_d,
                            SR.status == "active",
                        ).update(
                            {"status": "superseded"},
                            synchronize_session=False,
                        )

                # Recompile with correct per-day carry-in
                prior_day = day_d - timedelta(days=1)
                prior_end = self._get_prior_day_end_ms(loaded_blocks, prior_day)
                eff_open = self._compute_effective_day_open_ms(
                    day_str, self._day_start_hour, tz_name, prior_end,
                )
                rebuilt = self._compile_day(
                    channel_id, day_str,
                    effective_day_open_ms=eff_open,
                )
                if rebuilt:
                    loaded_blocks.extend(rebuilt)
                    loaded_days.add(day_str)
                    logger.info(
                        "INV-STARTUP-POISON-DETECTION-001: recovered day %s "
                        "for channel=%s — %d blocks rebuilt",
                        day_str, channel_id, len(rebuilt),
                    )
                else:
                    logger.error(
                        "INV-STARTUP-DAY-COVERAGE-001: day %s rebuild failed "
                        "for channel=%s — channel will fail fast for this day",
                        day_str, channel_id,
                    )
            except Exception as e:
                logger.error(
                    "INV-STARTUP-POISON-DETECTION-001: recovery failed for "
                    "day %s channel=%s: %s",
                    day_str, channel_id, e, exc_info=True,
                )

        loaded_blocks.sort(key=lambda b: b.start_utc_ms)

        # INV-CROSS-DAY-CARRY-IN-SURVIVES-RESTART-001: Blocks loaded from
        # schedule_items may overlap across broadcast day boundaries (each
        # day is compiled independently with grid-boundary start times).
        # Enforce contiguity by cascading push-forward across the entire
        # timeline.
        loaded_blocks = self._enforce_timeline_contiguity(loaded_blocks)

        now_ms = int(self._clock.now_utc().timestamp() * 1000)
        active_rid = self._query_active_revision_id_for_channel(channel_id, now_ms)
        with self._lock:
            self._blocks = loaded_blocks
            self._compiled_days = loaded_days
            self._timeline_revision_id = active_rid

        logger.info(
            "INV-TIMELINE-SINGLE-AUTHORITY-001: timeline loaded from DB — "
            "%d blocks across %d days for channel=%s "
            "(missing_days=%s)",
            len(loaded_blocks), len(loaded_days), channel_id,
            sorted(missing_days - loaded_days) if (missing_days - loaded_days) else "none",
        )

    def _load_existing_timeline(
        self,
        channel_id: str,
        start_date: "date_type",
        horizon_days: int,
        tz_name: str,
    ) -> tuple[list["ScheduledBlock"], set[str], set[str]]:
        """Load ScheduledBlocks via time-range query on ScheduleItems.

        docs/contracts/timeline_window_loading.md — Window Intersection Rule:
        A block is included iff block.start < window_end AND block.end > window_start.

        The query joins ScheduleItem → ScheduleRevision (active, matching
        channel) and filters by time overlap against the window.  No
        broadcast_day iteration occurs; broadcast_day is irrelevant to
        inclusion.

        loaded_days / missing_days are derived after loading for the
        compilation fallback in _build_initial — they are not used for
        block selection.

        Returns:
            (blocks, loaded_days, missing_days)
        """
        from retrovue.domain.entities import (
            Channel,
            ChannelActiveRevision,
            ScheduleItem,
            ScheduleRevision,
        )
        from sqlalchemy import select, and_, func

        all_blocks: list[ScheduledBlock] = []
        loaded_days: set[str] = set()

        # ── Compute window bounds ─────────────────────────────────────
        from zoneinfo import ZoneInfo
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = timezone.utc
        day_start_dt = datetime(
            start_date.year, start_date.month, start_date.day,
            self._day_start_hour, 0, tzinfo=tz,
        )
        window_start_ms = int(day_start_dt.timestamp() * 1000)
        window_start_dt = day_start_dt

        end_date = start_date + timedelta(days=horizon_days)
        end_dt = datetime(
            end_date.year, end_date.month, end_date.day,
            self._day_start_hour, 0, tzinfo=tz,
        )
        window_end_ms = int(end_dt.timestamp() * 1000)
        window_end_dt = end_dt

        # Horizon days expected — used to compute missing_days below.
        expected_days: set[str] = set(
            (start_date + timedelta(days=d)).strftime("%Y-%m-%d")
            for d in range(horizon_days)
        )

        try:
            with session() as db:
                # Resolve channel UUID from slug
                ch_row = db.execute(
                    select(Channel).where(Channel.slug == channel_id)
                ).scalars().first()
                if ch_row is None:
                    logger.warning(
                        "INV-TIMELINE-SINGLE-AUTHORITY-001: channel '%s' "
                        "not found in DB — no timeline to load",
                        channel_id,
                    )
                    # Best-effort fallback for same-process startup paths where
                    # schedule rows were published in a transaction not yet
                    # visible to a fresh DB session.
                    from retrovue.runtime.schedule_revision_writer import (
                        get_recent_published_schedule,
                    )
                    for day_str in sorted(expected_days):
                        snap = get_recent_published_schedule(
                            channel_id,
                            date_type.fromisoformat(day_str),
                        )
                        if not snap:
                            continue
                        hydrated = self._hydrate_schedule(snap, channel_id, day_str)
                        if not hydrated:
                            continue
                        all_blocks.extend(hydrated)
                        loaded_days.add(day_str)
                    if loaded_days:
                        all_blocks.sort(key=lambda b: b.start_utc_ms)
                        return all_blocks, loaded_days, expected_days - loaded_days
                    # Treat as no-op for this startup pass when no fallback is
                    # available.
                    return all_blocks, set(), set()

                ch_uuid = ch_row.id

                duplicate_days = (
                    db.query(
                        ScheduleRevision.broadcast_day,
                        func.count(ScheduleRevision.id).label("active_count"),
                    )
                    .filter(
                        ScheduleRevision.channel_id == ch_uuid,
                        ScheduleRevision.status == "active",
                        ScheduleRevision.broadcast_day >= start_date,
                        ScheduleRevision.broadcast_day < end_date,
                    )
                    .group_by(ScheduleRevision.broadcast_day)
                    .having(func.count(ScheduleRevision.id) > 1)
                    .all()
                )
                if duplicate_days:
                    dup_str = ", ".join(d.broadcast_day.isoformat() for d in duplicate_days)
                    raise ValueError(
                        "INV-REVISION-AUTHORITY-CONSISTENCY-001: duplicate active revisions "
                        f"for channel={channel_id} broadcast_day(s)={dup_str}"
                    )

                pointers = (
                    db.query(ChannelActiveRevision)
                    .filter(
                        ChannelActiveRevision.channel_id == ch_uuid,
                        ChannelActiveRevision.broadcast_day >= start_date,
                        ChannelActiveRevision.broadcast_day < end_date,
                    )
                    .order_by(ChannelActiveRevision.broadcast_day.asc())
                    .all()
                )
                if not pointers:
                    return all_blocks, loaded_days, expected_days - loaded_days

                pointer_rev_ids = [p.schedule_revision_id for p in pointers]
                rev_rows = (
                    db.query(ScheduleRevision)
                    .filter(ScheduleRevision.id.in_(pointer_rev_ids))
                    .all()
                )
                rev_map = {r.id: r for r in rev_rows}
                canonical_rev_ids: list[uuid.UUID] = []
                for ptr in pointers:
                    loaded_days.add(ptr.broadcast_day.strftime("%Y-%m-%d"))
                    rev = rev_map.get(ptr.schedule_revision_id)
                    if rev is None:
                        raise ValueError(
                            "INV-REVISION-AUTHORITY-CONSISTENCY-001: ChannelActiveRevision pointer "
                            f"targets missing revision for channel={channel_id} "
                            f"broadcast_day={ptr.broadcast_day.isoformat()}"
                        )
                    if (
                        rev.channel_id != ch_uuid
                        or rev.broadcast_day != ptr.broadcast_day
                        or rev.status != "active"
                    ):
                        raise ValueError(
                            "INV-REVISION-AUTHORITY-CONSISTENCY-001: ChannelActiveRevision pointer "
                            f"targets non-canonical revision for channel={channel_id} "
                            f"broadcast_day={ptr.broadcast_day.isoformat()}"
                        )
                    canonical_rev_ids.append(rev.id)

                # ── Time-range query: all active ScheduleItems whose
                #    time span overlaps the window. ─────────────────────
                #    item overlaps iff:
                #        item.start_time < window_end_dt
                #        AND (item.start_time + duration_sec) > window_start_dt
                #
                #    We approximate the second condition with:
                #        item.start_time > window_start_dt - max_item_duration
                #    then apply the exact predicate after deserialization.
                #    max_item_duration is generous (48h) to avoid missing
                #    any items.
                max_item_duration = timedelta(hours=48)
                items_with_rev = db.execute(
                    select(ScheduleItem, ScheduleRevision.broadcast_day)
                    .join(
                        ScheduleRevision,
                        ScheduleItem.schedule_revision_id == ScheduleRevision.id,
                    )
                    .where(and_(
                        ScheduleItem.schedule_revision_id.in_(canonical_rev_ids),
                        ScheduleItem.start_time < window_end_dt,
                        ScheduleItem.start_time > window_start_dt - max_item_duration,
                    ))
                    .order_by(ScheduleItem.start_time)
                ).all()

                for item, broadcast_day in items_with_rev:
                    # Exact time overlap check at the item level.
                    item_start_ms = int(item.start_time.timestamp() * 1000)
                    item_end_ms = int(
                        (item.start_time + timedelta(seconds=item.duration_sec)).timestamp() * 1000
                    )
                    if item_end_ms <= window_start_ms or item_start_ms >= window_end_ms:
                        continue

                    meta = item.metadata_ or {}
                    compiled_segs = meta.get("compiled_segments")

                    if not compiled_segs:
                        logger.warning(
                            "INV-TIMELINE-SINGLE-AUTHORITY-001: item "
                            "slot=%d (start=%s) has no compiled_segments — skipping",
                            item.slot_index, item.start_time,
                        )
                        continue

                    # INV-LOADER-SCHEMA-DISTINCTION-001: Detect format.
                    # compiled_segments = flat list of segment dicts
                    # segmented_blocks = list of block wrapper dicts with block_id etc.
                    seg_list = compiled_segs if isinstance(compiled_segs, list) else [compiled_segs]

                    if not seg_list or not isinstance(seg_list[0], dict):
                        logger.warning(
                            "INV-TIMELINE-SINGLE-AUTHORITY-001: "
                            "non-dict compiled_segment in slot=%d — skipping",
                            item.slot_index,
                        )
                        continue

                    first_entry = seg_list[0]
                    is_block_format = "block_id" in first_entry and "segments" in first_entry
                    is_segment_format = "segment_type" in first_entry and "duration_ms" in first_entry

                    if is_segment_format and not is_block_format:
                        # Post-BBL compiled_segments: flat segment list.
                        # INV-LOADER-HYDRATE-PATH-001: Hydrate using
                        # ScheduleItem time metadata for the block envelope.
                        from retrovue.runtime.schedule_items_reader import (
                            _hydrate_compiled_segments,
                        )
                        raw_asset_id = (
                            meta.get("asset_id_raw")
                            or (str(item.asset_id) if item.asset_id else "")
                        )
                        try:
                            resolver = self._get_resolver()
                            block = _hydrate_compiled_segments(
                                compiled_segments=seg_list,
                                asset_id=raw_asset_id,
                                start_utc_ms=item_start_ms,
                                slot_duration_ms=item_end_ms - item_start_ms,
                                resolver=resolver,
                            )
                            if block.start_utc_ms < window_end_ms and block.end_utc_ms > window_start_ms:
                                all_blocks.append(block)
                                day_str = broadcast_day.strftime("%Y-%m-%d")
                                loaded_days.add(day_str)
                        except (ValueError, KeyError, TypeError) as exc:
                            logger.warning(
                                "INV-TIMELINE-SINGLE-AUTHORITY-001: "
                                "failed to hydrate compiled_segments in slot=%d "
                                "(start=%s): %s — skipping block",
                                item.slot_index, item.start_time, exc,
                            )
                            continue
                    elif is_block_format:
                        # Legacy segmented_blocks format: block wrapper dicts.
                        for seg_dict in seg_list:
                            missing_fields = [
                                f for f in ("block_id", "start_utc_ms", "end_utc_ms", "segments")
                                if f not in seg_dict
                            ]
                            if missing_fields:
                                logger.warning(
                                    "INV-TIMELINE-CONTINUITY-001: block in "
                                    "slot=%d missing fields %s — skipping",
                                    item.slot_index, missing_fields,
                                )
                                continue
                            try:
                                block = _deserialize_scheduled_block(
                                    seg_dict, self._frame_tolerance_ms,
                                )
                                if block.start_utc_ms < window_end_ms and block.end_utc_ms > window_start_ms:
                                    all_blocks.append(block)
                                    day_str = broadcast_day.strftime("%Y-%m-%d")
                                    loaded_days.add(day_str)
                            except (ValueError, KeyError, TypeError) as exc:
                                logger.warning(
                                    "INV-TIMELINE-SINGLE-AUTHORITY-001: "
                                    "failed to deserialize block in slot=%d "
                                    "(start=%s): %s — skipping block",
                                    item.slot_index, item.start_time, exc,
                                )
                                continue
                    else:
                        logger.warning(
                            "INV-TIMELINE-SINGLE-AUTHORITY-001: "
                            "unrecognized compiled_segments format in slot=%d — skipping",
                            item.slot_index,
                        )
                        continue

        except ValueError:
            raise
        except Exception as e:
            logger.error(
                "INV-TIMELINE-SINGLE-AUTHORITY-001: failed to load "
                "timeline from DB for channel=%s: %s",
                channel_id, e, exc_info=True,
            )

        # Deduplicate by block_id, sort by start_utc_ms
        seen: set[str] = set()
        deduped: list[ScheduledBlock] = []
        for b in all_blocks:
            if b.block_id not in seen:
                deduped.append(b)
                seen.add(b.block_id)
        deduped.sort(key=lambda b: b.start_utc_ms)

        # Derive missing_days: expected horizon days not covered by any
        # loaded block.  This is for _build_initial's compilation fallback,
        # not for block selection.
        missing_days = expected_days - loaded_days

        return deduped, loaded_days, missing_days

    @staticmethod
    def _count_slots_in_dsl(dsl: dict) -> int:
        """Count total episode slots per broadcast day.

        NOTE: INV-SCHEDULE-SEQUENTIAL-ADVANCE-001 is RETIRED. This method
        is retained for non-sequential use cases. Handles three block formats:
          - slot-style:  block_def["slots"] list
          - block-style: block_def["block"] with duration/start/end
          - movie_marathon: block_def["movie_marathon"] with start/end
        """
        _sched = self._resolved_config["scheduling"]
        grid_minutes = _sched["grid_minutes"]["network_television"]

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
        """Load existing active schedule from ScheduleRevision + ScheduleItems.

        INV-TIMELINE-SINGLE-AUTHORITY-001: When an active revision exists
        for (channel, broadcast_day) with valid compiled_segments, return
        it so _compile_day can skip DSL compilation entirely.

        Returns a dict with 'segmented_blocks' key (compatible with
        _hydrate_schedule fast path), or None if no valid revision exists.

        Validation (INV-TIMELINE-CONTINUITY-001):
        - compiled_segments must be present on every ScheduleItem
        - every block must have block_id, start_utc_ms, end_utc_ms, segments
        - blocks must be contiguous (prev.end == next.start)
        - blocks must not overlap

        If any validation fails, returns None (fall through to compile).
        """
        from retrovue.domain.entities import (
            Channel,
            ChannelActiveRevision,
            ScheduleItem,
            ScheduleRevision,
        )
        from sqlalchemy import select, and_, func

        try:
            bd = date_type.fromisoformat(broadcast_day)
            with session() as db:
                channel = db.query(Channel).filter(
                    Channel.slug == channel_id,
                ).first()
                if channel is None:
                    return None

                duplicate_count = (
                    db.query(func.count(ScheduleRevision.id))
                    .filter(
                        ScheduleRevision.channel_id == channel.id,
                        ScheduleRevision.broadcast_day == bd,
                        ScheduleRevision.status == "active",
                    )
                    .scalar()
                )
                if duplicate_count and int(duplicate_count) > 1:
                    raise ValueError(
                        "INV-REVISION-AUTHORITY-CONSISTENCY-001: duplicate active revisions "
                        f"for channel={channel_id} broadcast_day={broadcast_day}"
                    )

                pointer = (
                    db.query(ChannelActiveRevision)
                    .filter(
                        ChannelActiveRevision.channel_id == channel.id,
                        ChannelActiveRevision.broadcast_day == bd,
                    )
                    .first()
                )
                if pointer is None:
                    return None
                rev = db.execute(
                    select(ScheduleRevision).where(and_(
                        ScheduleRevision.id == pointer.schedule_revision_id,
                        ScheduleRevision.channel_id == channel.id,
                        ScheduleRevision.broadcast_day == bd,
                        ScheduleRevision.status == "active",
                    ))
                ).scalars().first()
                if rev is None:
                    return None

                items = db.execute(
                    select(ScheduleItem)
                    .where(ScheduleItem.schedule_revision_id == rev.id)
                    .order_by(ScheduleItem.slot_index)
                ).scalars().all()
                if not items:
                    return None

                # ── Extract and validate compiled_segments ────────────
                # INV-LOADER-SCHEMA-DISTINCTION-001: Detect compiled_segments
                # format (flat segment dicts) vs segmented_blocks format
                # (block wrapper dicts). Convert both into segmented_blocks
                # format for _hydrate_schedule consumption.
                segmented_blocks: list[dict] = []

                for item in items:
                    meta = item.metadata_ or {}
                    compiled_segs = meta.get("compiled_segments")

                    if not compiled_segs:
                        logger.debug(
                            "_get_cached_schedule: item slot=%d in revision "
                            "%s for %s/%s has no compiled_segments — cache miss",
                            item.slot_index, rev.id, channel_id, broadcast_day,
                        )
                        return None

                    seg_list = compiled_segs if isinstance(compiled_segs, list) else [compiled_segs]

                    if not seg_list or not isinstance(seg_list[0], dict):
                        logger.debug(
                            "_get_cached_schedule: non-dict segment in "
                            "slot=%d — cache miss",
                            item.slot_index,
                        )
                        return None

                    first_entry = seg_list[0]
                    is_block_format = "block_id" in first_entry and "segments" in first_entry
                    is_segment_format = "segment_type" in first_entry and "duration_ms" in first_entry

                    if is_segment_format and not is_block_format:
                        # Post-BBL compiled_segments: flat segment list.
                        # Hydrate into a segmented_blocks-compatible dict
                        # using ScheduleItem time metadata for the envelope.
                        from retrovue.runtime.schedule_items_reader import (
                            _hydrate_compiled_segments,
                        )
                        raw_asset_id = (
                            meta.get("asset_id_raw")
                            or (str(item.asset_id) if item.asset_id else "")
                        )
                        item_start_ms = int(item.start_time.timestamp() * 1000)
                        item_slot_ms = int(item.duration_sec) * 1000
                        try:
                            block = _hydrate_compiled_segments(
                                compiled_segments=seg_list,
                                asset_id=raw_asset_id,
                                start_utc_ms=item_start_ms,
                                slot_duration_ms=item_slot_ms,
                            )
                            segmented_blocks.append(
                                _serialize_scheduled_block(block)
                            )
                        except Exception as exc:
                            logger.debug(
                                "_get_cached_schedule: failed to hydrate "
                                "compiled_segments in slot=%d: %s — cache miss",
                                item.slot_index, exc,
                            )
                            return None
                    elif is_block_format:
                        # Legacy segmented_blocks format.
                        for seg_dict in seg_list:
                            required_fields = ("block_id", "start_utc_ms", "end_utc_ms", "segments")
                            missing = [f for f in required_fields if f not in seg_dict]
                            if missing:
                                logger.debug(
                                    "_get_cached_schedule: block in slot=%d "
                                    "missing %s — cache miss",
                                    item.slot_index, missing,
                                )
                                return None
                            if seg_dict["end_utc_ms"] <= seg_dict["start_utc_ms"]:
                                logger.debug(
                                    "_get_cached_schedule: block in slot=%d has "
                                    "end <= start — cache miss",
                                    item.slot_index,
                                )
                                return None
                            segmented_blocks.append(seg_dict)
                    else:
                        logger.debug(
                            "_get_cached_schedule: unrecognized format in "
                            "slot=%d — cache miss",
                            item.slot_index,
                        )
                        return None

                if not segmented_blocks:
                    return None

                # ── Validate contiguity ───────────────────────────────
                segmented_blocks.sort(key=lambda b: b["start_utc_ms"])
                for i in range(1, len(segmented_blocks)):
                    prev_end = segmented_blocks[i - 1]["end_utc_ms"]
                    curr_start = segmented_blocks[i]["start_utc_ms"]
                    if curr_start != prev_end:
                        gap_or_overlap = (
                            "gap" if curr_start > prev_end else "overlap"
                        )
                        logger.warning(
                            "INV-TIMELINE-CONTINUITY-001: %s between blocks "
                            "%d and %d in cached schedule for %s/%s "
                            "(prev_end=%d, curr_start=%d) — cache miss",
                            gap_or_overlap, i - 1, i,
                            channel_id, broadcast_day,
                            prev_end, curr_start,
                        )
                        return None

                logger.info(
                    "INV-TIMELINE-SINGLE-AUTHORITY-001: loaded existing "
                    "schedule from DB for %s/%s — %d blocks from revision %s "
                    "(skipping DSL compilation)",
                    channel_id, broadcast_day,
                    len(segmented_blocks), rev.id,
                )

                return {
                    "segmented_blocks": segmented_blocks,
                    "revision_id": str(rev.id),
                }

        except ValueError:
            raise
        except Exception as e:
            logger.warning(
                "_get_cached_schedule failed for %s/%s: %s",
                channel_id, broadcast_day, e,
            )
            return None

    def _save_compiled_schedule(self, channel_id: str, broadcast_day: str, schedule: dict, dsl_hash: str) -> bool:
        """Persist compiled schedule to relational program_schedule authority only.

        INV-TIMELINE-APPEND-ONLY-001: Returns True if the write succeeded,
        False if it was refused (existing revision) or failed.  Callers
        MUST discard compiled output when False is returned.
        """
        from retrovue.runtime.schedule_revision_writer import (
            write_active_revision_from_compiled_schedule,
        )
        try:
            bd = date_type.fromisoformat(broadcast_day)
            with session() as db:
                return write_active_revision_from_compiled_schedule(
                    db,
                    channel_slug=channel_id,
                    broadcast_day=bd,
                    schedule=schedule,
                    created_by="dsl_schedule_service",
                )
        except Exception as e:
            logger.warning("Failed to save compiled schedule to DB: %s", e)
            return False

    @staticmethod
    def get_horizon_epg(
        *,
        blocks: list,
        compiled_days: set[str],
        horizon_days: int,
        clock_now: datetime,
        channel_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> list[dict]:
        """Horizon-aware EPG: serves the full compiled horizon.

        INV-EPG-HORIZON-COVERAGE-001: For dates within [now, now + HORIZON_DAYS],
        returns non-empty EPG if the scheduler daemon has compiled that date.
        For dates beyond the horizon, returns [].

        INV-EPG-READS-CANONICAL-SCHEDULE-001: DB is the preferred source.
        Falls back to in-memory blocks only when get_canonical_epg returns None
        (canonical unavailable). An empty list from the DB is a valid empty window
        and is returned as-is (no in-memory overlay).

        INV-SCHEDULE-PREWARM-001: MUST NOT trigger compilation.
        """
        # Step 1: Try canonical DB path first
        db_result = DslScheduleService.get_canonical_epg(
            channel_id, window_start, window_end,
        )
        if db_result is not None:
            return db_result

        # Step 2: Check horizon bounds
        horizon_end = (clock_now + timedelta(days=horizon_days)).date()
        requested_date = window_start.date()
        if requested_date > horizon_end:
            return []

        # Step 3: Check if the requested date has been compiled in memory
        requested_date_str = requested_date.isoformat()
        if requested_date_str not in compiled_days:
            return []

        # Step 4: Derive EPG from in-memory blocks (compiled but not persisted)
        window_start_ms = int(window_start.timestamp() * 1000)
        window_end_ms = int(window_end.timestamp() * 1000)

        out: list[dict] = []
        for block in blocks:
            if block.end_utc_ms <= window_start_ms or block.start_utc_ms >= window_end_ms:
                continue
            for seg in block.segments:
                if seg.segment_type in ("filler", "padding", "pad"):
                    continue
                start_dt = datetime.fromtimestamp(
                    block.start_utc_ms / 1000, tz=timezone.utc,
                )
                out.append({
                    "start_at": start_dt.isoformat(),
                    "slot_duration_sec": block.duration_ms // 1000,
                    "asset_id": seg.asset_uri,
                    "collection": None,
                    "content_type": seg.segment_type,
                })
                break  # one EPG entry per block

        out.sort(key=lambda x: x["start_at"])
        return out

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
                    return None

                # INV-EPG-NO-REVISION-OVERLAP-001: collect items from all candidate
                # revisions, then suppress items from earlier revisions that start
                # at or after the first item of the next chronological revision.
                # This prevents stale carry-over programs from previous broadcast_day
                # revisions from producing overlapping EPG entries (e.g. Bird Box from
                # yesterday appearing alongside Mission Galactica from today).
                rev_items = []  # (broadcast_day, start_time, ScheduleItem)
                for rev in revisions:
                    _rev_items = (
                        db.query(ScheduleItem)
                        .filter(ScheduleItem.schedule_revision_id == rev.id)
                        .order_by(ScheduleItem.slot_index.asc())
                        .all()
                    )
                    for it in _rev_items:
                        rev_items.append((rev.broadcast_day, it.start_time, it))

                # Find the earliest start_time in each revision.
                rev_day_first: dict = {}
                for bd, st, _ in rev_items:
                    if bd not in rev_day_first or st < rev_day_first[bd]:
                        rev_day_first[bd] = st

                # cutover[bd] = first start_time of the next later revision.
                # Items from revision bd that start >= cutover[bd] are suppressed.
                sorted_days = sorted(rev_day_first.keys())
                cutover: dict = {}
                for i, bd in enumerate(sorted_days):
                    cutover[bd] = rev_day_first[sorted_days[i + 1]] if i + 1 < len(sorted_days) else None

                out = []
                for bd, block_start, it in rev_items:
                    block_end = block_start + timedelta(seconds=it.duration_sec)
                    if block_end <= window_start or block_start >= window_end:
                        continue
                    co = cutover.get(bd)
                    if co is not None and block_start >= co:
                        # This item starts at or after the next revision took over; suppress it.
                        continue
                    # Clip block_end at the cutover so items that straddle the
                    # revision boundary do not overlap the successor revision.
                    effective_end = block_end if (co is None or block_end <= co) else co
                    effective_dur = int((effective_end - block_start).total_seconds())
                    meta = it.metadata_ or {}
                    out.append({
                        "start_at": block_start.isoformat(),
                        "slot_duration_sec": effective_dur,
                        "asset_id": meta.get("asset_id_raw") or (str(it.asset_id) if it.asset_id else ""),
                        "collection": meta.get("collection_raw") or (str(it.container_id) if it.container_id else None),
                        "title": meta.get("title") or "",
                        "content_type": it.content_type,
                        "schedule_revision_id": str(it.schedule_revision_id),
                    })

                out.sort(key=lambda x: x["start_at"])
                return out
        except Exception as e:
            logger.warning("Failed to read canonical EPG for %s/%s: %s", channel_id, window_start, e)
        return None

    def _compile_day(
        self, channel_id: str, broadcast_day: str,
        effective_day_open_ms: int = 0,
    ) -> list[ScheduledBlock]:
        """Compile a single broadcast day into filled ScheduledBlocks.

        DB-first: checks for a locked cached schedule before compiling.
        Uses deterministic sequential counters based on day offset from epoch,
        so episodes are consistent regardless of compilation order.

        ``effective_day_open_ms`` is the first legal block start time for
        this broadcast day.  It equals max(broadcast_day_start_ms,
        prior_block_end_ms).  Blocks that start before this time are
        removed before persisting — they will never air because a
        prior-day block owns that time.
        """
        from retrovue.runtime.schedule_cache_monotonicity import (
            channel_timeline_cache_payload_is_stale,
        )

        # DB-first: check cache
        cached = self._get_cached_schedule(channel_id, broadcast_day)
        if cached is not None and channel_timeline_cache_payload_is_stale(
            channel_id, cached
        ):
            logger.info(
                "INV-SCHEDULE-REVISION-MONOTONICITY-001: ignoring stale compiled "
                "schedule cache for %s/%s — revision head mismatch",
                channel_id,
                broadcast_day,
            )
            cached = None
        if cached is not None:
            logger.debug("Using cached schedule for %s/%s", channel_id, broadcast_day)
            blocks = self._hydrate_schedule(cached, channel_id, broadcast_day)
            # INV-CROSS-DAY-CARRY-IN-SURVIVES-RESTART-001: Cached blocks have
            # original grid times.  Apply push-forward so they don't overlap
            # with prior-day carry-in.
            if effective_day_open_ms > 0:
                blocks = self._push_forward_scheduled_blocks(
                    blocks, effective_day_open_ms, broadcast_day,
                )
            return blocks

        dsl_text = Path(self._dsl_path).read_text()
        dsl = parse_dsl(dsl_text)
        self._channel_dsl = dsl  # cache for traffic policy resolution
        dsl["broadcast_day"] = broadcast_day
        # Authoritative channel id for this service: schedule YAML may set dsl_path to a
        # shared network DSL whose top-level `channel:` differs from the tuning slug
        # (e.g. a harness slug using a shared network DSL file for grid/pools).
        if self._channel_slug:
            dsl["channel"] = self._channel_slug

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
                                         seed=_seed, run_store=run_store,
                                         resolved_config=self._resolved_config)

        # Resolve all plex:// URIs to local file paths
        self._resolve_uris(
            resolver,
            schedule,
            mode=self._asset_resolution_mode,
        )

        # Broadcast days are accounting constructs.  The schedule is a
        # linked list — each block starts where the previous one ended.
        # When a prior-day block extends past the day boundary, the
        # first block of the new day starts at that block's end, not
        # the grid boundary.
        #
        # Apply overlap push-forward to program_blocks BEFORE expansion
        # so that ScheduledBlocks are born with correct start times.
        if effective_day_open_ms > 0:
            self._apply_overlap_push_forward(
                schedule, effective_day_open_ms, broadcast_day,
            )

        # Enforce forward-only compilation for restart/runtime paths:
        # drop only fully past blocks; preserve in-progress overlap.
        now_utc = self._clock.now_utc()
        now_utc_ms = int(now_utc.timestamp() * 1000)
        program_blocks = schedule.get("program_blocks", [])
        if program_blocks:
            filtered_program_blocks = []
            dropped = 0
            for pb in program_blocks:
                pb_start = datetime.fromisoformat(pb["start_at"])
                if pb_start.tzinfo is None:
                    pb_start = pb_start.replace(tzinfo=timezone.utc)
                else:
                    pb_start = pb_start.astimezone(timezone.utc)
                pb_start_ms = int(pb_start.timestamp() * 1000)
                pb_end = pb.get("end_at")
                if pb_end:
                    pb_end_dt = datetime.fromisoformat(pb_end)
                    if pb_end_dt.tzinfo is None:
                        pb_end_dt = pb_end_dt.replace(tzinfo=timezone.utc)
                    else:
                        pb_end_dt = pb_end_dt.astimezone(timezone.utc)
                    pb_end_ms = int(pb_end_dt.timestamp() * 1000)
                else:
                    duration_sec = int(pb.get("slot_duration_sec", 0))
                    pb_end_ms = pb_start_ms + (duration_sec * 1000)
                if pb_end_ms <= now_utc_ms:
                    dropped += 1
                    continue
                filtered_program_blocks.append(pb)
            if dropped:
                logger.info(
                    "INV-SCHEDULE-FORWARD-ONLY-001: dropped %d historical program "
                    "blocks for %s/%s (now=%s)",
                    dropped,
                    channel_id,
                    broadcast_day,
                    now_utc.isoformat(),
                )
            schedule["program_blocks"] = filtered_program_blocks

        if not schedule.get("program_blocks"):
            logger.info(
                "INV-SCHEDULE-FORWARD-ONLY-001: no future program blocks remain "
                "for %s/%s; skipping compile/save",
                channel_id,
                broadcast_day,
            )
            return []

        # Expand each program block into segmented blocks
        # (content segments + empty filler placeholders)
        blocks = self._expand_schedule_to_blocks(schedule, resolver)
        # Apply block-level degraded metadata from schedule definitions so
        # callers always observe explicit degradation state, even when tests
        # or alternate expansion paths override _expand_schedule_to_blocks.
        if blocks and schedule.get("program_blocks"):
            from dataclasses import replace as dc_replace

            patched_blocks: list[ScheduledBlock] = []
            for pb, blk in zip(schedule["program_blocks"], blocks):
                pb_is_degraded = bool(pb.get("is_degraded", False))
                pb_reasons = list(pb.get("degraded_reasons", []))
                if pb_is_degraded or pb_reasons:
                    blk = dc_replace(
                        blk,
                        is_degraded=pb_is_degraded,
                        degraded_reasons=pb_reasons,
                    )
                patched_blocks.append(blk)
            # Preserve any trailing blocks when list lengths differ.
            if len(blocks) > len(patched_blocks):
                patched_blocks.extend(blocks[len(patched_blocks):])
            blocks = patched_blocks

        # Compile-time validation: catch compiler bugs before bad data
        # enters the playlog.  These are safety-net assertions on the
        # production path (ScheduledBlock list), not the derivation chain.
        from retrovue.scheduling.compile_time_validation import (
            validate_compiled_block_contiguity,
            validate_compiled_grid_alignment,
        )
        if blocks:
            validate_compiled_block_contiguity(blocks)
            _sched_cfg = self._resolved_config.get("scheduling", {})
            _grid_mins_cfg = _sched_cfg.get("grid_minutes", {})
            _grid_min = _grid_mins_cfg.get("network_television", 30)
            validate_compiled_grid_alignment(blocks, _grid_min * 60 * 1000)

        # INV-SCHEDULE-HORIZON-001: Persist segmented blocks alongside
        # program metadata so playlog plan (PlaylistBuilderDaemon) can consume
        # pre-segmented data without re-expanding.
        schedule["segmented_blocks"] = [
            _serialize_scheduled_block(b) for b in blocks
        ]

        # Save to DB.  INV-TIMELINE-APPEND-ONLY-001: If an active revision
        # already exists for this day, the write is refused.  In that case
        # the compiled blocks MUST be discarded — _blocks must not diverge
        # from the DB authority.
        dsl_hash = self._hash_dsl(dsl_text)
        written = self._save_compiled_schedule(channel_id, broadcast_day, schedule, dsl_hash)

        if not written:
            logger.info(
                "INV-TIMELINE-SINGLE-AUTHORITY-001: discarding compiled "
                "schedule for %s/%s — DB authority unchanged, refusing "
                "to create in-memory fork (%d blocks discarded)",
                channel_id, broadcast_day, len(blocks),
            )
            # During early startup races, channel metadata can lag the compile
            # path momentarily. Keep the freshly compiled overlap/future blocks
            # in memory so current-block lookup can still resolve "now".
            return blocks

        return blocks

    def _hydrate_schedule(self, schedule: dict, channel_id: str, broadcast_day: str) -> list[ScheduledBlock]:
        """Hydrate a cached schedule dict into ScheduledBlocks.

        INV-SCHEDULE-HORIZON-001: If segmented_blocks are present in the
        cached schedule, deserialize directly (no re-expansion needed).
        Falls back to expand_program_block if segmented_blocks are absent
        (backward compatibility with pre-program_schedule cached schedules).
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
        if self._channel_slug:
            dsl["channel"] = self._channel_slug

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
        # cached program schedule row so PlaylistBuilderDaemon can consume them.
        # Without this, stale rows (pre-segmented_blocks) stay stale and
        # the daemon can't pre-fill playlog plan, causing synchronous compiles
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

    @staticmethod
    def _apply_overlap_push_forward(
        schedule: dict,
        effective_day_open_ms: int,
        broadcast_day: str,
    ) -> None:
        """Push program blocks forward past prior-day overlap.

        Broadcast days are accounting constructs.  The schedule is a
        continuous linked list — each block starts where the previous one
        ended.  When a prior-day block extends past the day boundary,
        blocks that fall entirely within the overlap window are dropped,
        and the first surviving block's start_at is pushed forward to the
        effective day open.  Subsequent blocks cascade forward to remain
        contiguous.

        Mutates ``schedule["program_blocks"]`` in-place.
        """
        program_blocks = schedule.get("program_blocks", [])
        if not program_blocks:
            return

        effective_open_dt = datetime.fromtimestamp(
            effective_day_open_ms / 1000, tz=timezone.utc,
        )

        surviving: list[dict] = []
        pushed = False
        for pb in program_blocks:
            pb_start = datetime.fromisoformat(pb["start_at"])
            pb_end_ms = int(pb_start.timestamp() * 1000) + int(pb["slot_duration_sec"] * 1000)

            if pb_end_ms <= effective_day_open_ms:
                # Fully subsumed — this block never airs
                continue

            pb_start_ms = int(pb_start.timestamp() * 1000)
            if pb_start_ms < effective_day_open_ms:
                # This block starts before the effective day open.
                # Push it forward so it starts at the overlap end.
                # Subsequent blocks cascade via the same push.
                push_ms = effective_day_open_ms - pb_start_ms
                pb["start_at"] = effective_open_dt.isoformat()
                pushed = True
                logger.info(
                    "INV-CROSS-DAY-CARRY-IN-001: Pushed block '%s' start "
                    "%s → %s (+%dms) for broadcast_day=%s",
                    pb.get("title", "?"),
                    pb_start.isoformat(), effective_open_dt.isoformat(),
                    push_ms, broadcast_day,
                )
                surviving.append(pb)

                # Cascade: push all subsequent blocks forward by the same amount
                cursor = effective_open_dt + timedelta(seconds=pb["slot_duration_sec"])
                continue

            if pushed:
                # Cascade: push this block forward to maintain contiguity
                pb["start_at"] = cursor.isoformat()  # type: ignore[possibly-undefined]
                cursor = cursor + timedelta(seconds=pb["slot_duration_sec"])  # type: ignore[possibly-undefined]
            surviving.append(pb)

        if len(surviving) < len(program_blocks):
            logger.info(
                "INV-CROSS-DAY-CARRY-IN-001: Dropped %d subsumed blocks "
                "from %s (prior-day block owns time before %s)",
                len(program_blocks) - len(surviving),
                broadcast_day, effective_open_dt.isoformat(),
            )

        schedule["program_blocks"] = surviving

    @staticmethod
    def _push_forward_scheduled_blocks(
        blocks: list[ScheduledBlock],
        effective_day_open_ms: int,
        broadcast_day: str,
    ) -> list[ScheduledBlock]:
        """Push cached ScheduledBlocks forward past prior-day overlap.

        INV-CROSS-DAY-CARRY-IN-SURVIVES-RESTART-001: When blocks are loaded
        from the schedule cache, they have original grid times that may
        overlap with prior-day carry-in.  This applies the same push-forward
        logic as _apply_overlap_push_forward, but on ScheduledBlock objects
        instead of program_block dicts.

        Blocks fully subsumed by the carry-in window are dropped.
        The first surviving block is pushed to effective_day_open_ms.
        Subsequent blocks cascade forward to remain contiguous.
        """
        from dataclasses import replace as dc_replace

        result: list[ScheduledBlock] = []
        cursor_ms = effective_day_open_ms

        for block in blocks:
            block_dur_ms = block.end_utc_ms - block.start_utc_ms

            if block.end_utc_ms <= effective_day_open_ms:
                logger.info(
                    "INV-CROSS-DAY-CARRY-IN-001: Dropping subsumed cached "
                    "block %s (%d-%d) for broadcast_day=%s (effective_open=%d)",
                    block.block_id, block.start_utc_ms, block.end_utc_ms,
                    broadcast_day, effective_day_open_ms,
                )
                continue

            if block.start_utc_ms < cursor_ms:
                push_ms = cursor_ms - block.start_utc_ms
                new_start = cursor_ms
                new_end = new_start + block_dur_ms
                logger.info(
                    "INV-CROSS-DAY-CARRY-IN-001: Pushed cached block %s "
                    "start %d → %d (+%dms) for broadcast_day=%s",
                    block.block_id, block.start_utc_ms, new_start,
                    push_ms, broadcast_day,
                )
                block = dc_replace(block, start_utc_ms=new_start, end_utc_ms=new_end)

            result.append(block)
            cursor_ms = block.end_utc_ms

        if len(result) < len(blocks):
            logger.info(
                "INV-CROSS-DAY-CARRY-IN-001: Dropped %d subsumed cached "
                "blocks from %s (prior-day block owns time before %d)",
                len(blocks) - len(result), broadcast_day, effective_day_open_ms,
            )

        return result

    @staticmethod
    def _enforce_timeline_contiguity(
        blocks: list[ScheduledBlock],
    ) -> list[ScheduledBlock]:
        """Enforce contiguity across the entire in-memory timeline.

        INV-CROSS-DAY-CARRY-IN-SURVIVES-RESTART-001: When blocks from
        multiple broadcast days are loaded from schedule_items, they may
        overlap across day boundaries because each day was compiled with
        independent grid-boundary start times.  This method cascades
        push-forward across the sorted block list so all blocks are
        contiguous: block[i].end == block[i+1].start.

        Blocks fully subsumed by a prior block are dropped.
        Partially overlapping blocks are pushed forward.
        """
        if not blocks:
            return blocks

        from dataclasses import replace as dc_replace

        result: list[ScheduledBlock] = [blocks[0]]
        dropped = 0
        pushed = 0

        for block in blocks[1:]:
            prev = result[-1]
            block_dur_ms = block.end_utc_ms - block.start_utc_ms

            if block.end_utc_ms <= prev.end_utc_ms:
                # Fully subsumed by previous block — drop
                dropped += 1
                continue

            if block.start_utc_ms < prev.end_utc_ms:
                # Partial overlap — push forward
                new_start = prev.end_utc_ms
                new_end = new_start + block_dur_ms
                block = dc_replace(
                    block, start_utc_ms=new_start, end_utc_ms=new_end,
                )
                pushed += 1

            result.append(block)

        if dropped or pushed:
            logger.info(
                "INV-CROSS-DAY-CARRY-IN-001: Timeline contiguity enforced: "
                "%d blocks dropped, %d blocks pushed forward "
                "(%d → %d blocks)",
                dropped, pushed, len(blocks), len(result),
            )

        return result

    def _expand_schedule_to_blocks(self, schedule: dict, resolver: CatalogAssetResolver) -> list[ScheduledBlock]:
        """Expand compiled program blocks into ScheduledBlocks with empty filler placeholders.

        Produces program schedule data: content segments + empty filler placeholders
        (break opportunities). Ad fill happens at playlog plan generation (PlaylistBuilderDaemon),
        not here.

        INV-TRAFFIC-LATE-BIND-001: RETIRED — replaced by INV-PLAYLOG-PREFILL-001.
        Ad fill now happens at playlog plan generation time (2-3h ahead), not at
        feed time. See: docs/architecture/program-schedule-playlog-plan-horizon.md
        """
        return self._expand_blocks_inner(schedule, resolver)

    def _expand_blocks_inner(self, schedule: dict, resolver: CatalogAssetResolver) -> list[ScheduledBlock]:
        """Hydrate compiled_segments into ScheduledBlocks.

        INV-EXPANSION-NON-MUTATION-001: Structural segments (T0–T3) from
        compiled_segments are treated as read-only editorial truth. This
        method hydrates asset_id → asset_uri (path resolution) and sequences
        segments into tier order. It MUST NOT re-derive content structure,
        detect breaks, or modify segment durations.

        Filler placeholders (segment_type=filler, asset_uri="") are carried
        through from compiled_segments. They are filled by
        PlaylistBuilderDaemon at playlog plan generation time.
        """
        # STRUCTURAL INVARIANT:
        # All structural segmentation must occur at compile time.
        # Expansion is hydration-only.
        _real_expand = expand_program_block

        def _guarded_expand(*args, **kwargs):
            raise RuntimeError(
                "expand_program_block must not be called during expansion"
            )

        # Temporarily shadow the module-level import so any accidental call
        # inside this method (or anything it delegates to) is caught.
        import retrovue.runtime.dsl_schedule_service as _self_mod
        _prev = getattr(_self_mod, "expand_program_block", _real_expand)
        _self_mod.expand_program_block = _guarded_expand
        try:
            return self._expand_blocks_hydrate(schedule, resolver)
        finally:
            _self_mod.expand_program_block = _prev

    def _expand_blocks_hydrate(self, schedule: dict, resolver: CatalogAssetResolver) -> list[ScheduledBlock]:
        """Inner hydration loop — called by _expand_blocks_inner under the
        expand_program_block guard."""
        blocks: list[ScheduledBlock] = []
        for block_def in schedule["program_blocks"]:
            asset_id = block_def["asset_id"]
            is_degraded = bool(block_def.get("is_degraded", False))
            degraded_reasons = list(block_def.get("degraded_reasons", []))
            dt = datetime.fromisoformat(block_def["start_at"])
            start_utc_ms = int(dt.timestamp() * 1000)
            full_slot_ms = int(block_def["slot_duration_sec"] * 1000)
            end_utc_ms = start_utc_ms + full_slot_ms

            compiled_segments = block_def.get("compiled_segments")
            if not compiled_segments:
                # Legacy block without compiled_segments — skip.
                # These should not exist after the compiler refactor.
                logger.warning(
                    "Block '%s' at %s has no compiled_segments — skipping. "
                    "Recompile the schedule to populate compiled_segments.",
                    block_def.get("title", "?"), block_def.get("start_at", "?"),
                )
                continue

            # INV-EXPANSION-NON-MUTATION-001: Hydrate each compiled segment.
            # Resolve asset_id → asset_uri via catalog. Preserve all other
            # fields (duration, offsets, transitions, gain_db, is_primary)
            # exactly as the compiler produced them.
            segments: list[ScheduledSegment] = []
            for cs in compiled_segments:
                seg_type = cs.get("segment_type", "content")
                seg_asset_id = cs.get("asset_id", "")

                # Hydrate: resolve asset_id → file path + loudness gain
                asset_uri = ""
                gain_db = cs.get("gain_db", 0.0)
                if seg_asset_id:
                    try:
                        seg_meta = resolver.lookup(seg_asset_id)
                        asset_uri = self._resolve_uri(seg_meta.file_uri)
                        # Enqueue loudness measurement for unmeasured assets
                        if (
                            gain_db == 0.0
                            and asset_uri.startswith("/")
                            and resolver.asset_needs_loudness_measurement(seg_asset_id)
                        ):
                            self._enqueue_loudness_measurement(seg_asset_id, asset_uri)
                    except (KeyError, AttributeError) as exc:
                        if self._asset_resolution_mode == "strict":
                            raise AssetResolutionError(
                                f"Unknown asset: {seg_asset_id}"
                            ) from exc
                        reason = f"missing_asset:{seg_asset_id}"
                        if reason not in degraded_reasons:
                            degraded_reasons.append(reason)
                        is_degraded = True
                        logger.warning(
                            "Asset resolution degraded: failed to resolve asset_id '%s' "
                            "in block '%s'",
                            seg_asset_id, block_def.get("title", "?"),
                        )

                segments.append(ScheduledSegment(
                    segment_type=seg_type,
                    asset_uri=asset_uri,
                    asset_start_offset_ms=int(cs.get("asset_start_offset_ms", 0)),
                    segment_duration_ms=int(cs["duration_ms"]),
                    transition_in=cs.get("transition_in", "TRANSITION_NONE"),
                    transition_in_duration_ms=int(cs.get("transition_in_duration_ms", 0)),
                    transition_out=cs.get("transition_out", "TRANSITION_NONE"),
                    transition_out_duration_ms=int(cs.get("transition_out_duration_ms", 0)),
                    gain_db=gain_db,
                    is_primary=cs.get("is_primary", False),
                ))

            # Build block ID (deterministic from asset + start time)
            raw = f"{asset_id}:{start_utc_ms}"
            block_id = f"blk-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"

            expanded = ScheduledBlock(
                block_id=block_id,
                start_utc_ms=start_utc_ms,
                end_utc_ms=end_utc_ms,
                segments=tuple(segments),
                is_degraded=is_degraded,
                degraded_reasons=degraded_reasons,
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
                    "delta_ms=%d",
                    expanded.block_id, sum_segment_ms, block_duration_ms,
                    delta_ms,
                )
            else:
                logger.debug(
                    "BLOCK_PLAN_INVARIANT_CHECK block_id=%s "
                    "sum_segment_ms=%d block_duration_ms=%d delta_ms=0",
                    expanded.block_id, sum_segment_ms, block_duration_ms,
                )

            blocks.append(expanded)

        return blocks

    # _get_asset_library removed: ad fill now handled by PlaylistBuilderDaemon (playlog plan).
    # See: INV-PLAYLOG-PREFILL-001, docs/architecture/program-schedule-playlog-plan-horizon.md

    def _resolve_uris(
        self,
        resolver: CatalogAssetResolver,
        schedule: dict,
        mode: Literal["strict", "tolerant"] = "tolerant",
    ) -> None:
        """Pre-resolve source file paths to local paths using PathMappings.

        No external API calls — all data comes from the database.
        Assets store source file paths in canonical_uri (set during ingest).
        PathMappings translate source prefixes to local prefixes.
        """
        from retrovue.domain.entities import Asset, Container, PathMapping

        with session() as db:
            # Load all path mappings keyed by collection
            path_mappings: dict[str, list[tuple[str, str]]] = {}
            for col in db.query(Container).all():
                col_uuid = str(col.uuid)
                pms = db.query(PathMapping).filter(
                    PathMapping.container_id == col.uuid
                ).all()
                if pms:
                    path_mappings[col_uuid] = [(pm.source_path, pm.retrovue_path) for pm in pms]

            # Resolve each scheduled asset
            for block_def in schedule["program_blocks"]:
                asset_id = block_def["asset_id"]
                block_def.setdefault("is_degraded", False)
                block_def.setdefault("degraded_reasons", [])
                degraded_reasons = block_def["degraded_reasons"]
                try:
                    meta = resolver.lookup(asset_id)
                except KeyError as exc:
                    if mode == "strict":
                        raise AssetResolutionError(f"Unknown asset: {asset_id}") from exc
                    reason = f"missing_asset:{asset_id}"
                    if reason not in degraded_reasons:
                        degraded_reasons.append(reason)
                    block_def["is_degraded"] = True
                    logger.warning(
                        "Asset resolution degraded: skipping URI pre-resolution for unknown "
                        "asset_id=%s",
                        asset_id,
                    )
                    continue
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
                    col_uuid = str(asset_obj.container_id)
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
