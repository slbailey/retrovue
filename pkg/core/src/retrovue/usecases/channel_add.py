from __future__ import annotations

import re
from datetime import time
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..domain.entities import Channel

ALLOWED_GRID_SIZES: set[int] = {15, 30, 60}


def add_channel(
    db: Session,
    *,
    name: str,
    grid_size_minutes: int,
    grid_offset_minutes: int = 0,
    broadcast_day_start: str = "06:00",
    is_active: bool = True,
) -> dict[str, Any]:
    """Create a Channel and return a contract-aligned dict.

    Minimal validation aligned with ChannelAddContract.md.
    """
    if not name:
        raise ValueError("name is required")
    if grid_size_minutes not in ALLOWED_GRID_SIZES:
        raise ValueError("grid-size-minutes must be one of 15, 30, 60")
    if not isinstance(grid_offset_minutes, int) or not (0 <= grid_offset_minutes <= 59):
        raise ValueError("grid-offset-minutes must be an integer in 0..59")

    # Derive slug from name (lowercase kebab-case)
    slug = re.sub(r"[^a-z0-9-]", "-", name.lower().strip()).replace("--", "-")

    # Kind is optional/non-functional; omit assumption by using 'specialty' as neutral default
    kind = "specialty"

    # Programming day anchor from HH:MM string (seconds forced to 00)
    try:
        hh, mm = [int(x) for x in broadcast_day_start.split(":", 1)]
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError
        programming_day_start = time(hh, mm, 0)
    except Exception:
        raise ValueError("broadcast-day-start must be HH:MM (00:00..23:59)")

    # Alignment: start minute must align to grid and be compatible with offset
    start_minute = programming_day_start.minute
    if (start_minute - grid_offset_minutes) % grid_size_minutes != 0:
        raise ValueError("broadcast-day-start minute must align to grid and offset")

    # Compute per-hour allowed offsets from grid_size and alignment offset
    offsets: list[int] = sorted({(grid_offset_minutes + k * grid_size_minutes) % 60 for k in range(60)})
    offsets = [o for o in offsets if 0 <= o <= 59]

    # Enforce uniqueness of slug (case-insensitive)
    existing = (
        db.query(Channel)
        .filter(func.lower(Channel.slug) == slug.lower())
        .first()
    )
    if existing is not None:
        raise ValueError("Channel name already exists.")

    channel = Channel(
        slug=slug,
        title=name,
        grid_block_minutes=grid_size_minutes,
        kind=kind,
        programming_day_start=programming_day_start,
        block_start_offsets_minutes=offsets,
        is_active=is_active,
    )

    db.add(channel)
    db.commit()
    db.refresh(channel)

    return {
        "id": str(channel.id),
        "name": name,
        "grid_size_minutes": grid_size_minutes,
        "grid_offset_minutes": grid_offset_minutes,
        "broadcast_day_start": f"{programming_day_start.hour:02d}:{programming_day_start.minute:02d}",
        "is_active": channel.is_active,
        "version": 1,
        "created_at": channel.created_at.isoformat() if channel.created_at else None,
        "updated_at": channel.updated_at.isoformat() if channel.updated_at else None,
    }


