"""
Contract tests for INV-PLAYLIST-TIMELINE-CONTINUITY-001
and INV-PLAYLIST-TIME-ANCHOR-006.

PlaylistEvents must form a continuous, gap-free, overlap-free timeline
for a channel. The first event must start exactly at the ScheduleItem start.

See: docs/contracts/invariants/core/playout/INV-PLAYLIST-TIMELINE-CONTINUITY-001.md
See: docs/contracts/invariants/core/playout/INV-PLAYLIST-TIME-ANCHOR-006.md
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Fixtures — stubbed until PlaylistEvent generator exists
# ---------------------------------------------------------------------------


def _make_schedule_item(
    *,
    asset_id: str = "asset.movies.film_a",
    start_utc_ms: int = 1_000_000_000_000,
    slot_duration_ms: int = 1_800_000,
) -> dict:
    """Minimal ScheduleItem-shaped dict for testing."""
    return {
        "id": "si-001",
        "asset_id": asset_id,
        "start_utc_ms": start_utc_ms,
        "slot_duration_ms": slot_duration_ms,
    }


def _generate_playlist_events(schedule_items: list[dict]) -> list[dict]:
    from retrovue.runtime.playlist_event_generation import generate_playlist_events_from_schedule_items
    return generate_playlist_events_from_schedule_items(schedule_items)


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


class TestInvPlaylistTimelineContinuity001:
    """INV-PLAYLIST-TIMELINE-CONTINUITY-001 contract tests."""

    # Tier: 2 | Scheduling logic invariant
    def test_playlist_events_have_no_gaps(self):
        """Adjacent PlaylistEvents must have no gap between them.

        event[i].start_utc_ms + event[i].duration_ms == event[i+1].start_utc_ms
        """
        items = [
            _make_schedule_item(start_utc_ms=1_000_000_000_000, slot_duration_ms=1_800_000),
            _make_schedule_item(start_utc_ms=1_000_001_800_000, slot_duration_ms=1_800_000),
        ]
        events = _generate_playlist_events(items)
        events_sorted = sorted(events, key=lambda e: e["start_utc_ms"])

        for i in range(len(events_sorted) - 1):
            end_i = events_sorted[i]["start_utc_ms"] + events_sorted[i]["duration_ms"]
            start_next = events_sorted[i + 1]["start_utc_ms"]
            assert end_i == start_next, (
                f"Gap between event {i} and {i+1}: "
                f"end={end_i}, next_start={start_next}, delta={start_next - end_i}ms"
            )

    # Tier: 2 | Scheduling logic invariant
    def test_playlist_events_have_no_overlaps(self):
        """Adjacent PlaylistEvents must not overlap.

        event[i].start_utc_ms + event[i].duration_ms <= event[i+1].start_utc_ms
        """
        items = [
            _make_schedule_item(start_utc_ms=1_000_000_000_000, slot_duration_ms=1_800_000),
            _make_schedule_item(start_utc_ms=1_000_001_800_000, slot_duration_ms=1_800_000),
        ]
        events = _generate_playlist_events(items)
        events_sorted = sorted(events, key=lambda e: e["start_utc_ms"])

        for i in range(len(events_sorted) - 1):
            end_i = events_sorted[i]["start_utc_ms"] + events_sorted[i]["duration_ms"]
            start_next = events_sorted[i + 1]["start_utc_ms"]
            assert end_i <= start_next, (
                f"Overlap between event {i} and {i+1}: "
                f"end={end_i}, next_start={start_next}, overlap={end_i - start_next}ms"
            )


class TestInvPlaylistTimeAnchor006:
    """INV-PLAYLIST-TIME-ANCHOR-006 contract tests."""

    # Tier: 2 | Scheduling logic invariant
    def test_first_event_anchored_to_schedule_item_start(self):
        """The first PlaylistEvent must start exactly at ScheduleItem.start_utc_ms."""
        si = _make_schedule_item(start_utc_ms=1_000_000_000_000)
        events = _generate_playlist_events([si])
        events_sorted = sorted(events, key=lambda e: e["start_utc_ms"])

        assert events_sorted[0]["start_utc_ms"] == si["start_utc_ms"], (
            f"First event start {events_sorted[0]['start_utc_ms']} != "
            f"ScheduleItem start {si['start_utc_ms']}"
        )
