from __future__ import annotations

from retrovue.runtime.playlist_event_generation import generate_playlist_events_from_schedule_items


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
    return generate_playlist_events_from_schedule_items(schedule_items)


class TestInvPlaylistContentOffset003:
    def test_content_offsets_increase_monotonically(self):
        si = _make_schedule_item(ad_break_offsets_ms=[2_700_000])
        events = _generate_playlist_events([si])
        content_events = sorted([e for e in events if e["kind"] == "content"], key=lambda e: e["start_utc_ms"])
        for i in range(len(content_events) - 1):
            assert content_events[i + 1].get("offset_ms", 0) >= content_events[i].get("offset_ms", 0)

    def test_content_events_cover_asset_in_order(self):
        si = _make_schedule_item(episode_duration_ms=5_400_000, ad_break_offsets_ms=[1_800_000, 3_600_000])
        events = _generate_playlist_events([si])
        total = sum(e["duration_ms"] for e in events if e.get("schedule_item_id") == si["id"])
        assert total == si["slot_duration_ms"]
