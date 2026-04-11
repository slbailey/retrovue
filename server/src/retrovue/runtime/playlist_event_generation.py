"""Utility helpers for ScheduleItem -> PlaylistEvent derivation.

Used by Stage-3 contract tests to validate baseline PlaylistEvent invariants.
"""

from __future__ import annotations

from typing import Any


def generate_playlist_events_from_schedule_items(schedule_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate simple deterministic PlaylistEvent dicts from schedule-item dicts.

    This keeps timeline/timing identity invariants explicit:
    - first content event anchored to schedule_item.start_utc_ms
    - total derived duration equals schedule slot duration
    - content event carries source asset_id
    """
    out: list[dict[str, Any]] = []
    event_idx = 0

    for si in sorted(schedule_items, key=lambda x: x["start_utc_ms"]):
        sid = si["id"]
        start = int(si["start_utc_ms"])
        slot = int(si["slot_duration_ms"])
        episode = int(si.get("episode_duration_ms", slot))
        content_ms = min(max(episode, 0), slot)
        filler_ms = max(0, slot - content_ms)

        out.append({
            "id": f"pe-{event_idx}",
            "schedule_item_id": sid,
            "start_utc_ms": start,
            "duration_ms": content_ms,
            "kind": "content",
            "asset_id": si.get("asset_id"),
        })
        event_idx += 1

        if filler_ms > 0:
            out.append({
                "id": f"pe-{event_idx}",
                "schedule_item_id": sid,
                "start_utc_ms": start + content_ms,
                "duration_ms": filler_ms,
                "kind": "filler",
                "asset_id": None,
            })
            event_idx += 1

    return out
