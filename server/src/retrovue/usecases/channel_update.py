from __future__ import annotations

import re
import uuid as _uuid
from datetime import time
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..domain.entities import Channel

ALLOWED_GRID_SIZES: set[int] = {15, 30, 60}


def _parse_hhmm(value: str | None) -> time | None:
    if value is None:
        return None
    v = value.strip()
    if ":" not in v:
        raise ValueError("broadcast-day-start must be HH:MM (00:00..23:59)")
    parts = v.split(":", 2)
    try:
        hh = int(parts[0])
        mm = int(parts[1])
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError
        return time(hh, mm, 0)
    except Exception:
        raise ValueError("broadcast-day-start must be HH:MM (00:00..23:59)")


def update_channel(
    db: Session,
    *,
    identifier: str,
    name: str | None = None,
    grid_size_minutes: int | None = None,
    grid_offset_minutes: int | None = None,
    broadcast_day_start: str | None = None,
    is_active: bool | None = None,
) -> dict[str, Any]:
    """Update a channel and return the contract-aligned dict."""
    # Resolve channel by UUID or slug
    ch: Channel | None = None
    try:
        _ = _uuid.UUID(identifier)
        ch = db.query(Channel).filter(Channel.id == identifier).first()
    except Exception:
        ch = (
            db.query(Channel)
            .filter(func.lower(Channel.slug) == identifier.lower())
            .first()
        )
    if ch is None:
        raise ValueError(f"Channel '{identifier}' not found")

    # Gather existing values
    current_grid = ch.grid_block_minutes
    current_offset = 0
    if isinstance(ch.block_start_offsets_minutes, list) and ch.block_start_offsets_minutes:
        current_offset = min(ch.block_start_offsets_minutes)

    # Validate grid
    new_grid = grid_size_minutes if grid_size_minutes is not None else current_grid
    if new_grid not in ALLOWED_GRID_SIZES:
        raise ValueError("grid-size-minutes must be one of 15, 30, 60")

    # Validate offset
    new_offset = grid_offset_minutes if grid_offset_minutes is not None else current_offset
    if not isinstance(new_offset, int) or not (0 <= new_offset <= 59):
        raise ValueError("grid-offset-minutes must be an integer in 0..59")

    # Parse broadcast-day-start
    new_anchor_time = _parse_hhmm(broadcast_day_start) if broadcast_day_start else ch.programming_day_start
    if new_anchor_time is None:
        new_anchor_time = time(6, 0, 0)

    # Alignment rule
    start_minute = new_anchor_time.minute
    if (start_minute - new_offset) % new_grid != 0:
        raise ValueError("broadcast-day-start minute must align to grid and offset")

    # Apply name/title and slug changes
    if name:
        new_slug = re.sub(r"[^a-z0-9-]", "-", name.lower().strip()).replace("--", "-")
        # Enforce slug uniqueness (exclude current channel)
        dup = (
            db.query(Channel)
            .filter(func.lower(Channel.slug) == new_slug.lower(), Channel.id != ch.id)
            .first()
        )
        if dup is not None:
            raise ValueError("Channel name already exists.")
        ch.title = name
        ch.slug = new_slug

    # Update grid/offset/anchor
    ch.grid_block_minutes = new_grid
    ch.programming_day_start = new_anchor_time

    # Recompute offsets for the hour pattern
    offsets = sorted({(new_offset + k * new_grid) % 60 for k in range(60)})
    offsets = [o for o in offsets if 0 <= o <= 59]
    ch.block_start_offsets_minutes = offsets

    # Active flag
    if is_active is not None:
        ch.is_active = bool(is_active)

    db.add(ch)
    db.commit()
    db.refresh(ch)

    return {
        "id": str(ch.id),
        "name": ch.title,
        "grid_size_minutes": ch.grid_block_minutes,
        "grid_offset_minutes": new_offset,
        "broadcast_day_start": f"{ch.programming_day_start.hour:02d}:{ch.programming_day_start.minute:02d}",
        "is_active": bool(ch.is_active),
        "version": 1,
        "created_at": ch.created_at.isoformat() if ch.created_at else None,
        "updated_at": ch.updated_at.isoformat() if ch.updated_at else None,
    }


