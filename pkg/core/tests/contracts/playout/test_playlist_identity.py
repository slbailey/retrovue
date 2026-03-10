"""
Contract tests for INV-PLAYLIST-CONTENT-IDENTITY-005.

A content PlaylistEvent must reference the same asset
as its source ScheduleItem.

See: docs/contracts/invariants/core/playout/INV-PLAYLIST-CONTENT-IDENTITY-005.md
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_schedule_item(
    *,
    asset_id: str = "asset.movies.film_a",
    start_utc_ms: int = 1_000_000_000_000,
    slot_duration_ms: int = 5_400_000,
    episode_duration_ms: int = 5_400_000,
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


class TestInvPlaylistContentIdentity005:
    """INV-PLAYLIST-CONTENT-IDENTITY-005 contract tests."""

    # Tier: 2 | Scheduling logic invariant
    def test_content_event_asset_matches_schedule_item(self):
        """Every content-kind PlaylistEvent must carry the same asset_id
        as the ScheduleItem it derives from.

        Execution intent cannot change editorial identity.
        """
        si = _make_schedule_item(
            asset_id="asset.movies.film_a",
            ad_break_offsets_ms=[2_700_000],
        )
        events = _generate_playlist_events([si])
        content_events = [e for e in events if e["kind"] == "content"]

        assert len(content_events) >= 1, "Expected at least one content event"

        for i, event in enumerate(content_events):
            assert event["asset_id"] == si["asset_id"], (
                f"Content event {i} asset_id '{event['asset_id']}' != "
                f"ScheduleItem asset_id '{si['asset_id']}'"
            )
