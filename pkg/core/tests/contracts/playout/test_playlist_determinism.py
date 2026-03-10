"""
Contract tests for INV-PLAYLIST-HORIZON-DETERMINISM-007.

PlaylistEvent generation must be deterministic. Same inputs -> same outputs.

See: docs/contracts/invariants/core/playout/INV-PLAYLIST-HORIZON-DETERMINISM-007.md
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
    slot_duration_ms: int = 1_800_000,
    episode_duration_ms: int = 1_320_000,
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


class TestInvPlaylistHorizonDeterminism007:
    """INV-PLAYLIST-HORIZON-DETERMINISM-007 contract tests."""

    # Tier: 2 | Scheduling logic invariant
    def test_playlist_generation_is_deterministic(self):
        """Generating PlaylistEvents twice from identical inputs must
        produce identical results.

        Field-by-field equality across all events.
        """
        si = _make_schedule_item(
            ad_break_offsets_ms=[660_000],  # 11 min
        )

        run_1 = _generate_playlist_events([si])
        run_2 = _generate_playlist_events([si])

        assert len(run_1) == len(run_2), (
            f"Event count differs: run_1={len(run_1)}, run_2={len(run_2)}"
        )

        fields = ["id", "start_utc_ms", "duration_ms", "kind", "schedule_item_id",
                   "asset_id", "offset_ms"]

        for i, (e1, e2) in enumerate(zip(run_1, run_2)):
            for field in fields:
                assert e1.get(field) == e2.get(field), (
                    f"Event {i} field '{field}' differs: "
                    f"run_1={e1.get(field)}, run_2={e2.get(field)}"
                )
