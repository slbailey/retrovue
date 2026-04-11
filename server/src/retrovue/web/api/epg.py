"""
EPG (Electronic Program Guide) API.

Reads from canonical DB-cached schedule (ScheduleRevision/ScheduleItems)
and returns program block metadata as JSON.

INV-EPG-READS-CANONICAL-SCHEDULE-001: EPG endpoints MUST read from the
canonical compiled schedule. They MUST NOT call compile_schedule() directly.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from retrovue.runtime.dsl_schedule_service import DslScheduleService
from retrovue.runtime.catalog_resolver import CatalogAssetResolver
from retrovue.infra.uow import session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["epg"])

YAML_CHANNELS_DIR = __import__("pathlib").Path("/opt/retrovue/config/channels")


def _load_channels() -> list[dict[str, Any]]:
    from retrovue.runtime.providers import YamlChannelConfigProvider
    from retrovue.config import load_defaults
    if YAML_CHANNELS_DIR.is_dir():
        return YamlChannelConfigProvider(YAML_CHANNELS_DIR, resolved_config=load_defaults()).to_channels_list()
    return []


@router.get("/epg")
def get_epg(
    date: str = Query(default=None, description="Date in YYYY-MM-DD format"),
    channel: str = Query(default=None, description="Channel ID filter"),
):
    """Return EPG data for all (or one) channel on a given date.

    INV-EPG-READS-CANONICAL-SCHEDULE-001: reads from canonical relational
    schedule data via DslScheduleService.get_canonical_epg().
    """
    from zoneinfo import ZoneInfo
    from datetime import date as _date_type

    channels = _load_channels()
    if channel:
        channels = [c for c in channels if c["channel_id"] == channel]

    # Determine broadcast day using channel timezone (not hardcoded).
    # Use the first channel's tz as default; per-channel window is computed below.
    default_tz_name = "UTC"
    default_day_start = 6
    if channels:
        sc = channels[0].get("schedule_config", {})
        default_tz_name = sc.get("channel_tz", "UTC")
        default_day_start = sc.get("broadcast_day_start_hour", 6)

    if date is None:
        tz = ZoneInfo(default_tz_name)
        now = datetime.now(tz)
        if now.hour < default_day_start:
            broadcast_day = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            broadcast_day = now.strftime("%Y-%m-%d")
    else:
        broadcast_day = date

    with session() as db:
        shared_resolver = CatalogAssetResolver(db)

    all_entries = []
    for ch in channels:
        try:
            sc = ch.get("schedule_config", {})
            ch_tz_name = sc.get("channel_tz", "UTC")
            ch_day_start = sc.get("broadcast_day_start_hour", 6)
            ch_tz = ZoneInfo(ch_tz_name)

            _bd = _date_type.fromisoformat(broadcast_day)
            window_start = datetime(_bd.year, _bd.month, _bd.day, ch_day_start, 0, tzinfo=ch_tz)
            window_end = window_start + timedelta(hours=24)

            blocks = DslScheduleService.get_canonical_epg(
                ch["channel_id"], window_start, window_end
            )
            if blocks is None:
                all_entries.append({
                    "channel_id": ch["channel_id"],
                    "channel_name": ch["name"],
                    "error": "Schedule not yet compiled",
                })
                continue

            from retrovue.epg.duration import epg_display_duration

            for block in blocks:
                asset_id = block["asset_id"]
                series_title = block.get("title", "")
                season_number = None
                episode_number = None
                description = ""
                episode_title = ""

                for cat_entry in shared_resolver._catalog:
                    if cat_entry.canonical_id == asset_id:
                        series_title = cat_entry.series_title or series_title
                        season_number = cat_entry.season
                        episode_number = cat_entry.episode
                        description = getattr(cat_entry, "description", "") or ""
                        episode_title = getattr(cat_entry, "title", "") or ""
                        break

                start_dt = datetime.fromisoformat(block["start_at"])
                slot_sec = block["slot_duration_sec"]
                ep_sec = block.get("episode_duration_sec", block["slot_duration_sec"])
                end_dt = start_dt + timedelta(seconds=slot_sec)

                all_entries.append({
                    "channel_id": ch["channel_id"],
                    "channel_name": ch["name"],
                    "start_time": start_dt.isoformat(),
                    "end_time": end_dt.isoformat(),
                    "title": (series_title or episode_title or "Untitled"),
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
                    "asset_id": str(asset_id) if asset_id else None,
                })
        except Exception as e:
            logger.error("Failed to compile EPG for %s: %s", ch["channel_id"], e, exc_info=True)
            all_entries.append({
                "channel_id": ch["channel_id"],
                "channel_name": ch["name"],
                "error": str(e),
            })

    return JSONResponse(content={
        "broadcast_day": broadcast_day,
        "entries": all_entries,
    })
