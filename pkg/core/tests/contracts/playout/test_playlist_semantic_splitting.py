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


def _generate_playlist_events(schedule_items: list[dict], *, grid_duration_ms: int = 1_800_000) -> list[dict]:
    return generate_playlist_events_from_schedule_items(schedule_items)


class TestInvPlaylistSemanticSplit002:
    def test_grid_boundaries_do_not_split_content(self):
        si = _make_schedule_item(slot_duration_ms=5_400_000, episode_duration_ms=5_400_000, ad_break_offsets_ms=[])
        events = _generate_playlist_events([si], grid_duration_ms=1_800_000)
        content_events = [e for e in events if e["kind"] == "content"]
        assert len(content_events) == 1

    def test_ad_break_creates_split(self):
        si = _make_schedule_item(slot_duration_ms=5_400_000, episode_duration_ms=5_400_000, ad_break_offsets_ms=[2_700_000])
        events = _generate_playlist_events([si])
        content_events = [e for e in events if e["kind"] == "content"]
        assert len(content_events) >= 1

    def test_content_transition_creates_split(self):
        si_a = _make_schedule_item(asset_id="asset.movies.film_a", start_utc_ms=1_000_000_000_000, slot_duration_ms=1_800_000, episode_duration_ms=1_320_000)
        si_b = _make_schedule_item(asset_id="asset.movies.film_b", start_utc_ms=1_000_001_800_000, slot_duration_ms=1_800_000, episode_duration_ms=1_320_000)
        si_b["id"] = "si-002"
        events = _generate_playlist_events([si_a, si_b])
        content_events = [e for e in events if e["kind"] == "content"]
        asset_ids = [e["asset_id"] for e in content_events]
        assert "asset.movies.film_a" in asset_ids
        assert "asset.movies.film_b" in asset_ids
