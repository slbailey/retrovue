"""
EPG (Electronic Program Guide) API.

Compiles DSL schedules on-demand and returns program block metadata as JSON.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from retrovue.runtime.schedule_compiler import compile_schedule, parse_dsl
from retrovue.runtime.catalog_resolver import CatalogAssetResolver
from retrovue.infra.uow import session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["epg"])

YAML_CHANNELS_DIR = Path("/opt/retrovue/config/channels")


def _load_channels() -> list[dict[str, Any]]:
    from retrovue.runtime.providers import YamlChannelConfigProvider
    if YAML_CHANNELS_DIR.is_dir():
        return YamlChannelConfigProvider(YAML_CHANNELS_DIR).to_channels_list()
    return []



def _compile_epg(channel_cfg: dict[str, Any], broadcast_day: str, resolver: CatalogAssetResolver | None = None, run_store: object = None) -> list[dict[str, Any]]:
    """Compile a single channel's DSL for a broadcast day and return EPG entries.

    Episode progression uses the canonical calendar-based resolver
    (docs/contracts/episode_progression.md) with persistent run records.
    """
    dsl_path = channel_cfg["schedule_config"]["dsl_path"]
    dsl_text = Path(dsl_path).read_text()
    dsl = parse_dsl(dsl_text)
    dsl["broadcast_day"] = broadcast_day

    if resolver is None:
        with session() as db:
            resolver = CatalogAssetResolver(db)

    ch_id = channel_cfg["channel_id"]

    # INV-SCHEDULE-SEED-DAY-VARIANCE-001: day-varying deterministic seed
    from retrovue.runtime.schedule_compiler import compilation_seed
    _seed = compilation_seed(ch_id, broadcast_day)

    schedule = compile_schedule(dsl, resolver=resolver, dsl_path=dsl_path,
                                seed=_seed, run_store=run_store)

    entries = []
    for block in schedule["program_blocks"]:
        asset_id = block["asset_id"]

        # Look up editorial metadata from catalog
        series_title = block.get("title", "")
        season_number = None
        episode_number = None
        episode_title = ""

        # Find the catalog entry for richer metadata
        description = ''
        episode_title = ''
        for cat_entry in resolver._catalog:
            if cat_entry.canonical_id == asset_id:
                series_title = cat_entry.series_title or series_title
                season_number = cat_entry.season
                episode_number = cat_entry.episode
                description = cat_entry.description or ''
                episode_title = cat_entry.title or ''
                break

        start_dt = datetime.fromisoformat(block["start_at"])
        slot_sec = block["slot_duration_sec"]
        ep_sec = block["episode_duration_sec"]
        end_dt = start_dt + __import__("datetime").timedelta(seconds=slot_sec)

        from retrovue.epg.duration import epg_display_duration
        entries.append({
            "channel_id": channel_cfg["channel_id"],
            "channel_name": channel_cfg["name"],
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "title": series_title,
            "episode_title": episode_title,
            "season": season_number,
            "episode": episode_number,
            "description": description,
            "duration_minutes": round(ep_sec / 60, 1),
            "slot_minutes": round(slot_sec / 60, 1),
            "display_duration": epg_display_duration(
                start_dt, end_dt, slot_sec, ep_sec,
                is_movie=season_number is None,
            ),
        })

    return entries


@router.get("/epg")
def get_epg(
    date: str = Query(default=None, description="Date in YYYY-MM-DD format"),
    channel: str = Query(default=None, description="Channel ID filter"),
):
    """Return EPG data for all (or one) channel on a given date."""
    if date is None:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
        if now.hour < 6:
            broadcast_day = (now - __import__("datetime").timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            broadcast_day = now.strftime("%Y-%m-%d")
    else:
        broadcast_day = date

    channels = _load_channels()
    if channel:
        channels = [c for c in channels if c["channel_id"] == channel]

    # Part 2A: Build resolver and run store once per EPG request.
    from retrovue.runtime.progression_run_store import DbProgressionRunStore
    with session() as db:
        shared_resolver = CatalogAssetResolver(db)
        shared_run_store = DbProgressionRunStore(db)

    all_entries = []
    for ch in channels:
        try:
            entries = _compile_epg(ch, broadcast_day, resolver=shared_resolver, run_store=shared_run_store)
            all_entries.extend(entries)
        except Exception as e:
            logger.error(f"Failed to compile EPG for {ch['channel_id']}: {e}", exc_info=True)
            all_entries.append({
                "channel_id": ch["channel_id"],
                "channel_name": ch["name"],
                "error": str(e),
            })

    return JSONResponse(content={
        "broadcast_day": broadcast_day,
        "entries": all_entries,
    })
