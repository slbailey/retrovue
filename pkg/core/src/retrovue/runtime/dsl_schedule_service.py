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

logger = logging.getLogger(__name__)

# How many days ahead to compile on initial load
HORIZON_DAYS = 3

# When remaining schedule falls below this many hours, compile the next day
RECOMPILE_THRESHOLD_HOURS = 6


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
    ) -> None:
        self._dsl_path = dsl_path
        self._filler_path = filler_path
        self._filler_duration_ms = filler_duration_ms
        self._day_start_hour = programming_day_start_hour
        self._broadcast_day_override = broadcast_day

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
        
        Also checks if the horizon needs extending.
        """
        # Check horizon before lookup
        self._maybe_extend_horizon(channel_id, utc_ms)

        with self._lock:
            for block in self._blocks:
                if block.start_utc_ms <= utc_ms < block.end_utc_ms:
                    return block

        logger.warning(
            "No DSL block covers utc_ms=%d for channel=%s", utc_ms, channel_id
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

    def _compile_day(self, channel_id: str, broadcast_day: str) -> list[ScheduledBlock]:
        """Compile a single broadcast day into filled ScheduledBlocks.
        
        Uses deterministic sequential counters based on day offset from epoch,
        so episodes are consistent regardless of compilation order.
        """

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

        # Compile program schedule with deterministic counters
        schedule = compile_schedule(dsl, resolver=resolver, dsl_path=self._dsl_path,
                                     sequential_counters=sequential_counters)

        # Resolve all plex:// URIs to local file paths
        self._resolve_uris(resolver, schedule)

        # Expand each program block and fill ad breaks
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

            # Expand into acts + ad breaks
            expanded = expand_program_block(
                asset_id=asset_id,
                asset_uri=asset_uri,
                start_utc_ms=start_utc_ms,
                slot_duration_ms=block_def["slot_duration_sec"] * 1000,
                episode_duration_ms=block_def["episode_duration_sec"] * 1000,
                chapter_markers_ms=chapter_ms,
            )

            # Fill ad breaks with filler
            filled = fill_ad_blocks(
                expanded,
                filler_uri=self._filler_path,
                filler_duration_ms=self._filler_duration_ms,
            )

            blocks.append(filled)

        return blocks

    def _resolve_uris(self, resolver: CatalogAssetResolver, schedule: dict) -> None:
        """Pre-resolve all plex:// URIs to local file paths."""
        from retrovue.domain.entities import Asset, Collection, PathMapping
        from retrovue.adapters.registry import get_importer

        with session() as db:
            # Get all collections with path mappings
            collections = db.query(Collection).all()
            sources = {}
            path_mappings = {}

            for col in collections:
                col_uuid = str(col.uuid)
                if col.source:
                    sources[col_uuid] = col.source
                pms = db.query(PathMapping).filter(
                    PathMapping.collection_uuid == col.uuid
                ).all()
                path_mappings[col_uuid] = [(pm.plex_path, pm.local_path) for pm in pms]

            # For each asset in the schedule, resolve its URI
            for block_def in schedule["program_blocks"]:
                asset_id = block_def["asset_id"]
                meta = resolver.lookup(asset_id)
                uri = meta.file_uri

                if uri in self._uri_cache:
                    continue

                if uri.startswith("plex://"):
                    # Find which collection this asset belongs to
                    asset = db.query(Asset).filter(Asset.uuid == asset_id).first()
                    if asset:
                        col_uuid = str(asset.collection_uuid)
                        source = sources.get(col_uuid)
                        pms = path_mappings.get(col_uuid, [])

                        if source and pms:
                            config = {k: v for k, v in (source.config or {}).items()
                                      if k != "enrichers"}
                            importer = get_importer(source.type, **config)
                            rating_key = uri.replace("plex://", "")
                            try:
                                ep_meta = importer.client.get_episode_metadata(int(rating_key))
                                file_path = None
                                for media in (ep_meta or {}).get("Media", []):
                                    for part in media.get("Part", []):
                                        if part.get("file"):
                                            file_path = part["file"]
                                            break
                                    if file_path:
                                        break
                                if file_path:
                                    synth = {
                                        "path_uri": uri,
                                        "path": file_path,
                                        "raw_labels": [f"plex_file_path:{file_path}"],
                                    }
                                    local = importer.resolve_local_uri(
                                        synth, collection=asset.collection,
                                        path_mappings=pms,
                                    )
                                    if local:
                                        self._uri_cache[uri] = local
                            except Exception as e:
                                logger.warning(f"Failed to resolve {uri}: {e}")

    def _resolve_uri(self, uri: str) -> str:
        """Resolve a single URI, returning local path or original URI."""
        return self._uri_cache.get(uri, uri)
