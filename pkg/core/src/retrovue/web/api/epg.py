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

CHANNELS_JSON = Path("/opt/retrovue/config/channels.json")


def _load_channels() -> list[dict[str, Any]]:
    with open(CHANNELS_JSON) as f:
        return json.load(f)["channels"]


def _count_slots_in_dsl(dsl: dict[str, Any]) -> int:
    """Count total episode slots per broadcast day in a DSL schedule."""
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


def _compile_epg(channel_cfg: dict[str, Any], broadcast_day: str) -> list[dict[str, Any]]:
    """Compile a single channel's DSL for a broadcast day and return EPG entries.
    
    Uses deterministic sequential counters based on the broadcast day offset
    from a fixed epoch, so each day shows different episodes.
    """
    dsl_path = channel_cfg["schedule_config"]["dsl_path"]
    dsl_text = Path(dsl_path).read_text()
    dsl = parse_dsl(dsl_text)
    dsl["broadcast_day"] = broadcast_day

    with session() as db:
        resolver = CatalogAssetResolver(db)

    # Calculate deterministic counter offset based on day number from epoch
    # This ensures each day starts at the right episode regardless of
    # which day the EPG is viewed
    from datetime import date as date_type
    epoch = date_type(2026, 1, 1)  # fixed epoch
    target = date_type.fromisoformat(broadcast_day)
    day_offset = (target - epoch).days

    # Count slots per day to compute starting counter
    slots_per_day = _count_slots_in_dsl(dsl)
    starting_counter = day_offset * slots_per_day

    # Pre-seed sequential counters for all pools
    sequential_counters = {}
    pools = dsl.get("pools", {})
    for pool_id in pools:
        sequential_counters[pool_id] = starting_counter

    schedule = compile_schedule(dsl, resolver=resolver, dsl_path=dsl_path,
                                sequential_counters=sequential_counters)

    entries = []
    for block in schedule["program_blocks"]:
        asset_id = block["asset_id"]

        # Look up editorial metadata from catalog
        series_title = block.get("title", "")
        season_number = None
        episode_number = None
        episode_title = ""

        # Find the catalog entry for richer metadata
        for cat_entry in resolver._catalog:
            if cat_entry.canonical_id == asset_id:
                series_title = cat_entry.series_title or series_title
                season_number = cat_entry.season
                episode_number = cat_entry.episode
                break

        start_dt = datetime.fromisoformat(block["start_at"])
        slot_sec = block["slot_duration_sec"]
        ep_sec = block["episode_duration_sec"]
        end_dt = start_dt + __import__("datetime").timedelta(seconds=slot_sec)

        entries.append({
            "channel_id": channel_cfg["channel_id"],
            "channel_name": channel_cfg["name"],
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "title": series_title,
            "season": season_number,
            "episode": episode_number,
            "duration_minutes": round(ep_sec / 60, 1),
            "slot_minutes": round(slot_sec / 60, 1),
        })

    return entries


@router.get("/epg")
async def get_epg(
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

    all_entries = []
    for ch in channels:
        try:
            entries = _compile_epg(ch, broadcast_day)
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
