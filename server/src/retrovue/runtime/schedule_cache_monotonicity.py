"""In-process revision head for schedule timeline cache (INV-SCHEDULE-REVISION-MONOTONICITY-001).

After a successful splice publish, :func:`bump_channel_schedule_revision_head` records the new
active ``ScheduleRevision`` id. Future-facing readers that use cached structures **without**
matching ``revision_id`` must treat them as stale and re-resolve against ``R_active``.
"""

from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()
# channel_slug -> schedule_revision_id (str) from the last publish in this process
_revision_head_by_channel: dict[str, str] = {}


def bump_channel_schedule_revision_head(channel_slug: str, revision_id: str) -> None:
    """Call after commit of a new active revision for this channel (same process)."""
    with _lock:
        _revision_head_by_channel[channel_slug] = revision_id


def get_channel_schedule_revision_head(channel_slug: str) -> str | None:
    """Return last bumped revision id for this channel, if any."""
    with _lock:
        return _revision_head_by_channel.get(channel_slug)


def channel_timeline_cache_payload_is_stale(channel_slug: str, payload: dict[str, Any] | None) -> bool:
    """True if a future-facing cached schedule dict cannot be trusted vs the bumped head.

    When no bump exists in this process, returns False — canonical DB reads remain authoritative.
    When a bump exists, payloads without ``revision_id`` or with a mismatched id are stale.
    """
    head = get_channel_schedule_revision_head(channel_slug)
    if head is None:
        return False
    rid = (payload or {}).get("revision_id")
    if rid is None:
        return True
    return str(rid) != str(head)
