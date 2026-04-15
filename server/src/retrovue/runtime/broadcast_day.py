"""Shared broadcast-day derivation logic for scheduling."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def derive_broadcast_day_for_utc(
    utc_dt: datetime,
    *,
    tz_name: str = "UTC",
    day_start_hour: int = 6,
) -> date:
    """Derive broadcast day from a UTC instant using tz/day-start rules."""
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    else:
        utc_dt = utc_dt.astimezone(timezone.utc)

    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc

    local_now = utc_dt.astimezone(tz)
    if local_now.hour < day_start_hour:
        return (local_now - timedelta(days=1)).date()
    return local_now.date()
