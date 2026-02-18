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
import threading
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Any

from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment
from retrovue.runtime.schedule_compiler import compile_schedule, parse_dsl
from retrovue.runtime.playout_log_expander import expand_program_block
from retrovue.runtime.traffic_manager import fill_ad_blocks
from retrovue.runtime.catalog_resolver import CatalogAssetResolver
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
    return {
        "block_id": block.block_id,
        "start_utc_ms": block.start_utc_ms,
        "end_utc_ms": block.end_utc_ms,
        "segments": [
            {
                "segment_type": s.segment_type,
                "asset_uri": s.asset_uri,
                "asset_start_offset_ms": s.asset_start_offset_ms,
                "segment_duration_ms": s.segment_duration_ms,
                "transition_in": s.transition_in,
                "transition_in_duration_ms": s.transition_in_duration_ms,
                "transition_out": s.transition_out,
                "transition_out_duration_ms": s.transition_out_duration_ms,
            }
            for s in block.segments
        ],
    }


def _deserialize_scheduled_block(d: dict) -> "ScheduledBlock":
    """Deserialize a dict back into a ScheduledBlock.

    INV-SCHEDULE-HORIZON-001: Used by Tier 2 (Playlog Horizon Daemon)
    and _hydrate_schedule to reconstruct blocks from DB cache.
    """
    from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment
    return ScheduledBlock(
        block_id=d["block_id"],
        start_utc_ms=d["start_utc_ms"],
        end_utc_ms=d["end_utc_ms"],
        segments=tuple(
            ScheduledSegment(
                segment_type=s["segment_type"],
                asset_uri=s.get("asset_uri", ""),
                asset_start_offset_ms=s.get("asset_start_offset_ms", 0),
                segment_duration_ms=s.get("segment_duration_ms", 0),
                transition_in=s.get("transition_in", "TRANSITION_NONE"),
                transition_in_duration_ms=s.get("transition_in_duration_ms", 0),
                transition_out=s.get("transition_out", "TRANSITION_NONE"),
                transition_out_duration_ms=s.get("transition_out_duration_ms", 0),
            )
            for s in d["segments"]
        ),
    )


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
    ) -> None:
        self._dsl_path = dsl_path
        self._filler_path = filler_path
        self._filler_duration_ms = filler_duration_ms
        self._day_start_hour = programming_day_start_hour
        self._broadcast_day_override = broadcast_day
        self._channel_slug = channel_slug

        # Pre-built blocks indexed by start_utc_ms
        self._blocks: list[ScheduledBlock] = []
        self._lock = threading.Lock()
        self._uri_cache: dict[str, str] = {}

        # Track which broadcast days have been compiled (set of "YYYY-MM-DD")
        self._compiled_days: set[str] = set()


        # Recompile guard: prevent concurrent horizon extensions
        self._extending = False

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

        INV-CHANNEL-NO-COMPILE-001: Prefers Tier 2 (TransmissionLog) data
        which contains fully-filled ad breaks. Falls back to in-memory
        unfilled blocks only if Tier 2 hasn't pre-filled yet.

        Also checks if the horizon needs extending.
        """
        # Check horizon before lookup
        self._maybe_extend_horizon(channel_id, utc_ms)

        # Tier 2 first: check TransmissionLog for pre-filled block
        filled = self._get_filled_block_at(channel_id, utc_ms)
        if filled is not None:
            return filled

        # Fallback: unfilled in-memory block (Tier 2 hasn't reached this block yet)
        with self._lock:
            for block in self._blocks:
                if block.start_utc_ms <= utc_ms < block.end_utc_ms:
                    logger.info(
                        "INV-CHANNEL-NO-COMPILE-001: Tier 2 miss for "
                        "channel=%s utc_ms=%d — using unfilled block %s",
                        channel_id, utc_ms, block.block_id,
                    )
                    return block

        logger.warning(
            "No DSL block covers utc_ms=%d for channel=%s", utc_ms, channel_id
        )
        return None

    def _get_filled_block_at(self, channel_id: str, utc_ms: int) -> ScheduledBlock | None:
        """Look up a pre-filled block from TransmissionLog (Tier 2).

        INV-CHANNEL-NO-COMPILE-001 / INV-PLAYLOG-PREFILL-001:
        Returns a ScheduledBlock with real ad URIs if the Playlog Horizon
        Daemon has already filled this block. Returns None otherwise.
        """
        try:
            from retrovue.infra.uow import session as db_session_factory
            from retrovue.domain.entities import TransmissionLog

            with db_session_factory() as db:
                row = db.query(TransmissionLog).filter(
                    TransmissionLog.channel_slug == channel_id,
                    TransmissionLog.start_utc_ms <= utc_ms,
                    TransmissionLog.end_utc_ms > utc_ms,
                ).first()

                if row is None:
                    return None

                # Deserialize TX log segments into ScheduledBlock
                segments = []
                for s in row.segments:
                    segments.append(ScheduledSegment(
                        segment_type=s.get("segment_type", "content"),
                        asset_uri=s.get("asset_uri", ""),
                        asset_start_offset_ms=s.get("asset_start_offset_ms", 0),
                        segment_duration_ms=s.get("segment_duration_ms", 0),
                        transition_in=s.get("transition_in", "TRANSITION_NONE"),
                        transition_in_duration_ms=s.get("transition_in_duration_ms", 0),
                        transition_out=s.get("transition_out", "TRANSITION_NONE"),
                        transition_out_duration_ms=s.get("transition_out_duration_ms", 0),
                    ))

                logger.debug(
                    "INV-CHANNEL-NO-COMPILE-001: Tier 2 hit for "
                    "channel=%s block=%s (%d segs)",
                    channel_id, row.block_id, len(segments),
                )

                return ScheduledBlock(
                    block_id=row.block_id,
                    start_utc_ms=row.start_utc_ms,
                    end_utc_ms=row.end_utc_ms,
                    segments=tuple(segments),
                )

        except Exception as e:
            logger.warning(
                "INV-CHANNEL-NO-COMPILE-001: Tier 2 lookup failed for "
                "channel=%s utc_ms=%d: %s — falling back to unfilled",
                channel_id, utc_ms, e,
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

    # ── Build / compile ───────────────────────────────────────────────

    def _build_initial(self, channel_id: str) -> None:
        """Compile DSL for today + HORIZON_DAYS-1 additional days."""
        now = datetime.now(timezone.utc)

        if self._broadcast_day_override:
            start_date = date.fromisoformat(self._broadcast_day_override)
        else:
            # Programming day starts at day_start_hour; if before that, use yesterday
            from zoneinfo import ZoneInfo
            # Read timezone from DSL
            dsl_text = Path(self._dsl_path).read_text()
            dsl = parse_dsl(dsl_text)
            tz_name = dsl.get("timezone", "UTC")
            try:
                tz = ZoneInfo(tz_name)
            except Exception:
                tz = timezone.utc
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
                logger.info(
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
        """Count total episode slots per broadcast day."""
        count = 0
        schedule = dsl.get("schedule", {})
        for day_key, day_value in schedule.items():
            if isinstance(day_value, list):
                for block_def in day_value:
                    if isinstance(block_def, dict):
                        count += len(block_def.get("slots", []))
            elif isinstance(day_value, dict):
                count += len(day_value.get("slots", []))
        return count

    def _get_cached_schedule(self, channel_id: str, broadcast_day: str) -> dict | None:
        """Check DB for a locked compiled schedule."""
        from retrovue.domain.entities import CompiledProgramLog
        try:
            with session() as db:
                row = db.query(CompiledProgramLog).filter(
                    CompiledProgramLog.channel_id == channel_id,
                    CompiledProgramLog.broadcast_day == date_type.fromisoformat(broadcast_day),
                    CompiledProgramLog.locked == True,
                ).first()
                if row:
                    return row.compiled_json
        except Exception as e:
            logger.warning("Failed to check compiled_program_log cache: %s", e)
        return None

    def _save_compiled_schedule(self, channel_id: str, broadcast_day: str, schedule: dict, dsl_hash: str) -> None:
        """Persist a compiled schedule to the DB.

        INV-SCHEDULE-HORIZON-001: Stores both program-level metadata
        (program_blocks) and segmented block data (segmented_blocks).
        Segmented blocks contain content segments + empty filler
        placeholders (break opportunities with durations/positions).
        """
        from retrovue.domain.entities import CompiledProgramLog
        try:
            with session() as db:
                row = CompiledProgramLog(
                    channel_id=channel_id,
                    broadcast_day=date_type.fromisoformat(broadcast_day),
                    schedule_hash=dsl_hash,
                    compiled_json=schedule,
                    locked=True,
                )
                db.merge(row)
        except Exception as e:
            logger.warning("Failed to save compiled schedule to DB: %s", e)

    @staticmethod
    def _hash_dsl(dsl_text: str) -> str:
        return hashlib.sha256(dsl_text.encode("utf-8")).hexdigest()

    def _compile_day(self, channel_id: str, broadcast_day: str) -> list[ScheduledBlock]:
        """Compile a single broadcast day into filled ScheduledBlocks.
        
        DB-first: checks for a locked cached schedule before compiling.
        Uses deterministic sequential counters based on day offset from epoch,
        so episodes are consistent regardless of compilation order.
        """
        # DB-first: check cache
        cached = self._get_cached_schedule(channel_id, broadcast_day)
        if cached is not None:
            logger.info("Using cached schedule for %s/%s", channel_id, broadcast_day)
            return self._hydrate_schedule(cached, channel_id, broadcast_day)

        dsl_text = Path(self._dsl_path).read_text()
        dsl = parse_dsl(dsl_text)
        dsl["broadcast_day"] = broadcast_day

        # Build resolver from catalog
        with session() as db:
            resolver = CatalogAssetResolver(db)

        # Deterministic sequential counters based on day offset
        from datetime import date as date_type
        epoch = date_type(2026, 1, 1)
        target = date_type.fromisoformat(broadcast_day)
        day_offset = (target - epoch).days
        slots_per_day = self._count_slots_in_dsl(dsl)
        starting_counter = day_offset * slots_per_day

        sequential_counters = {}
        pools = dsl.get("pools", {})
        for pool_id in pools:
            sequential_counters[pool_id] = starting_counter

        # Derive channel-specific seed from channel_id hash so different
        # channels with the same pool don't get identical movie sequences
        _channel_seed = abs(hash(channel_id)) % 100000

        # Compile program schedule with deterministic counters
        schedule = compile_schedule(dsl, resolver=resolver, dsl_path=self._dsl_path,
                                     sequential_counters=sequential_counters,
                                     seed=_channel_seed)

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
            logger.info(
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
        dsl["broadcast_day"] = broadcast_day

        # Build resolver from catalog
        with session() as db:
            resolver = CatalogAssetResolver(db)

        # Register pools
        pools = dsl.get("pools", {})
        if pools and hasattr(resolver, "register_pools"):
            resolver.register_pools(pools)

        # Resolve URIs
        self._resolve_uris(resolver, schedule)

        return self._expand_schedule_to_blocks(schedule, resolver)

    def _expand_schedule_to_blocks(self, schedule: dict, resolver: CatalogAssetResolver) -> list[ScheduledBlock]:
        """Expand compiled program blocks into ScheduledBlocks with empty filler placeholders.

        Produces Tier 1 data: content segments + empty filler placeholders
        (break opportunities). Ad fill happens at Tier 2 (PlaylogHorizonDaemon),
        not here.

        INV-TRAFFIC-LATE-BIND-001: RETIRED — replaced by INV-PLAYLOG-PREFILL-001.
        Ad fill now happens at Tier 2 generation time (2-3h ahead), not at
        feed time. See: docs/architecture/two-tier-horizon.md
        """
        return self._expand_blocks_inner(schedule, resolver)

    def _expand_blocks_inner(self, schedule: dict, resolver: CatalogAssetResolver) -> list[ScheduledBlock]:
        """Inner expand loop -- produces Tier 1 blocks with EMPTY filler placeholders.

        Filler placeholders (segment_type=filler, asset_uri="") are filled by
        PlaylogHorizonDaemon at Tier 2 generation time and written to
        TransmissionLog. ChannelManager reads filled blocks from TransmissionLog.

        INV-PLAYLOG-PREFILL-001: Ad selection at Tier 2, not compile time or feed time.
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

            # Expand into acts + ad breaks (empty filler placeholders — Tier 1 data).
            # INV-PLAYLOG-PREFILL-001: Ad fill happens at Tier 2 (PlaylogHorizonDaemon),
            # not here at compile time and not at feed time.
            expanded = expand_program_block(
                asset_id=asset_id,
                asset_uri=asset_uri,
                start_utc_ms=start_utc_ms,
                slot_duration_ms=block_def["slot_duration_sec"] * 1000,
                episode_duration_ms=block_def["episode_duration_sec"] * 1000,
                chapter_markers_ms=chapter_ms,
            )

            blocks.append(expanded)

        return blocks

    # _get_asset_library removed: ad fill now handled by PlaylogHorizonDaemon (Tier 2).
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
