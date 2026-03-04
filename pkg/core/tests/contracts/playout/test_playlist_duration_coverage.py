"""
Contract tests for INV-PLAYLIST-DURATION-COVERAGE-004.

The sum of PlaylistEvent durations derived from a ScheduleItem
must equal the ScheduleItem's slot duration.

See: docs/contracts/invariants/core/playout/INV-PLAYLIST-DURATION-COVERAGE-004.md
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_schedule_item(
    *,
    asset_id: str = "asset.sitcoms.show_a",
    start_utc_ms: int = 1_000_000_000_000,
    slot_duration_ms: int = 1_800_000,  # 30 minutes
    episode_duration_ms: int = 1_320_000,  # 22 minutes
    ad_break_offsets_ms: list[int] | None = None,
) -> dict:
    return {
        "id": "si-001",
        "asset_id": asset_id,
        "start_utc_ms": start_utc_ms,
        "slot_duration_ms": slot_duration_ms,
        "episode_duration_ms": episode_duration_ms,
        "ad_break_offsets_ms": ad_break_offsets_ms or [],
    }


def _generate_playlist_events(schedule_items: list[dict]) -> list[dict]:
    from retrovue.runtime.playlist_event_generation import generate_playlist_events_from_schedule_items
    return generate_playlist_events_from_schedule_items(schedule_items)


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


class TestInvPlaylistDurationCoverage004:
    """INV-PLAYLIST-DURATION-COVERAGE-004 contract tests."""

    def test_playlist_events_cover_schedule_item_duration(self):
        """Sum of all PlaylistEvent durations must equal the slot duration.

        A 22-min episode in a 30-min slot requires content + pad = 30 min.
        """
        si = _make_schedule_item(
            slot_duration_ms=1_800_000,
            episode_duration_ms=1_320_000,
        )
        events = _generate_playlist_events([si])

        # Filter to events derived from this ScheduleItem
        derived = [e for e in events if e.get("schedule_item_id") == si["id"] or e["kind"] != "content"]
        total_ms = sum(e["duration_ms"] for e in derived)

        assert total_ms == si["slot_duration_ms"], (
            f"Duration mismatch: sum of events = {total_ms}ms, "
            f"slot_duration = {si['slot_duration_ms']}ms, "
            f"delta = {total_ms - si['slot_duration_ms']}ms"
        )
