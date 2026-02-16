"""
DSL-backed ScheduleService.

Compiles a Programming DSL file into a full day's playout log,
resolves asset URIs to local file paths, and serves ScheduledBlocks
to ChannelManager on demand.

Implements the ScheduleService protocol (get_block_at, get_playout_plan_now).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment
from retrovue.runtime.schedule_compiler import compile_schedule, parse_dsl
from retrovue.runtime.playout_log_expander import expand_program_block
from retrovue.runtime.traffic_manager import fill_ad_blocks
from retrovue.runtime.catalog_resolver import CatalogAssetResolver
from retrovue.infra.uow import session

logger = logging.getLogger(__name__)


class DslScheduleService:
    """
    Schedule service backed by the Programming DSL compiler pipeline.

    On load, compiles the DSL → program schedule → playout log → filled blocks.
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
        self._broadcast_day = broadcast_day

        # Pre-built blocks indexed by start_utc_ms
        self._blocks: list[ScheduledBlock] = []
        self._uri_cache: dict[str, str] = {}  # plex://xxx → /mnt/data/...

    def load_schedule(self, channel_id: str) -> tuple[bool, str | None]:
        """Compile DSL and build the full day's playout log."""
        try:
            self._build(channel_id)
            return (True, None)
        except Exception as e:
            logger.error(f"Failed to load DSL schedule: {e}", exc_info=True)
            return (False, str(e))

    def get_block_at(self, channel_id: str, utc_ms: int) -> ScheduledBlock | None:
        """Return the ScheduledBlock covering the given wall-clock time."""
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

    def _build(self, channel_id: str) -> None:
        """Compile DSL → expand → fill for the full broadcast day."""

        # Read DSL file
        dsl_text = Path(self._dsl_path).read_text()
        dsl = parse_dsl(dsl_text)

        # Override broadcast_day to today if not set
        if self._broadcast_day:
            dsl["broadcast_day"] = self._broadcast_day
        elif "broadcast_day" not in dsl:
            now = datetime.now(timezone.utc)
            dsl["broadcast_day"] = now.strftime("%Y-%m-%d")

        # Build resolver from catalog
        with session() as db:
            resolver = CatalogAssetResolver(db)

        # Compile program schedule
        schedule = compile_schedule(dsl, resolver=resolver, dsl_path=self._dsl_path)

        # Resolve all plex:// URIs to local file paths
        self._resolve_uris(resolver, schedule)

        # Expand each program block and fill ad breaks
        self._blocks = []
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

            self._blocks.append(filled)

        self._blocks.sort(key=lambda b: b.start_utc_ms)

        logger.info(
            f"DSL schedule built: {len(self._blocks)} blocks for "
            f"channel={channel_id} day={dsl.get('broadcast_day')}"
        )

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
