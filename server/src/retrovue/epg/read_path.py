"""
Shared EPG read-path: canonical schedule → JSON payload.

Used by web/api/epg.py and ProgramDirector's /api/epg so behavior stays aligned.
"""

from __future__ import annotations

import logging
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from typing import Any

from zoneinfo import ZoneInfo

from retrovue.epg.duration import epg_display_duration
from retrovue.runtime.broadcast_day import derive_broadcast_day_for_utc
from retrovue.runtime.catalog_resolver import CatalogAssetResolver
from retrovue.runtime.clock import SystemClock
from retrovue.runtime.dsl_schedule_service import DslScheduleService

logger = logging.getLogger(__name__)
_clock = SystemClock()


def build_epg_payload(
    channels: list[dict[str, Any]],
    broadcast_day: str,
    shared_resolver: CatalogAssetResolver,
) -> dict[str, Any]:
    """Build broadcast_day JSON: per-channel schedule status + flat program entries."""
    channel_schedule: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []

    for ch in channels:
        try:
            sc = ch.get("schedule_config", {})
            ch_tz_name = sc.get("channel_tz", "UTC")
            ch_day_start = sc.get("broadcast_day_start_hour", 6)
            ch_tz = ZoneInfo(ch_tz_name)

            bd = date_type.fromisoformat(broadcast_day)
            window_start = datetime(bd.year, bd.month, bd.day, ch_day_start, 0, tzinfo=ch_tz)
            window_end = window_start + timedelta(hours=24)

            blocks = DslScheduleService.get_canonical_epg(
                ch["channel_id"], window_start, window_end
            )
            if blocks is None:
                channel_schedule.append({
                    "channel_id": ch["channel_id"],
                    "channel_name": ch["name"],
                    "schedule_status": "unavailable",
                    "detail": "Canonical schedule unavailable (not published or unreadable)",
                    "schedule_revision_id": None,
                })
                continue

            if not blocks:
                channel_schedule.append({
                    "channel_id": ch["channel_id"],
                    "channel_name": ch["name"],
                    "schedule_status": "empty_window",
                    "detail": None,
                    "schedule_revision_id": None,
                })
                continue

            rev_ids = {b.get("schedule_revision_id") for b in blocks if b.get("schedule_revision_id")}
            summary_rev = next(iter(rev_ids), None) if len(rev_ids) == 1 else None

            channel_schedule.append({
                "channel_id": ch["channel_id"],
                "channel_name": ch["name"],
                "schedule_status": "ok",
                "detail": None,
                "schedule_revision_id": summary_rev,
            })

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

                entries.append({
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
                    "schedule_revision_id": block.get("schedule_revision_id"),
                })
        except Exception as e:
            logger.error("EPG read failed for %s: %s", ch["channel_id"], e, exc_info=True)
            channel_schedule.append({
                "channel_id": ch["channel_id"],
                "channel_name": ch["name"],
                "schedule_status": "unavailable",
                "detail": str(e),
                "schedule_revision_id": None,
            })

    return {
        "broadcast_day": broadcast_day,
        "channel_schedule": channel_schedule,
        "entries": entries,
    }


def resolve_epg_broadcast_day(
    channels: list[dict[str, Any]],
    date_param: str | None,
    now_utc: datetime | None = None,
) -> str:
    """Pick broadcast_day using the first channel's tz and day-start hour (matches /api/epg)."""
    default_tz_name = "UTC"
    default_day_start = 6
    if channels:
        sc = channels[0].get("schedule_config", {})
        default_tz_name = sc.get("channel_tz", "UTC")
        default_day_start = sc.get("broadcast_day_start_hour", 6)

    if date_param is None:
        ref_utc = now_utc
        if ref_utc is None:
            ref_utc = _clock.now_utc()
        if ref_utc.tzinfo is None:
            ref_utc = ref_utc.replace(tzinfo=timezone.utc)
        day = derive_broadcast_day_for_utc(
            ref_utc,
            tz_name=default_tz_name,
            day_start_hour=default_day_start,
        )
        return day.strftime("%Y-%m-%d")
    return date_param
