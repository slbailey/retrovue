"""
Contract tests for INV-MARATHON-CROSSMIDNIGHT-001.

A movie marathon whose time range spans midnight (e.g., 22:00–06:00) MUST
resolve the end time to the next calendar day and MUST produce program blocks.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from retrovue.runtime.asset_resolver import AssetMetadata, StubAssetResolver
from retrovue.runtime.schedule_compiler import (
    _compile_movie_marathon,
    _parse_time,
    ProgramBlockOutput,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_resolver() -> StubAssetResolver:
    """Build a resolver with a late_night movie pool."""
    r = StubAssetResolver()

    movie_ids = []
    for letter, dur_sec in [("a", 5400), ("b", 6000), ("c", 4800), ("d", 7200)]:
        mid = f"asset.movies.late_{letter}"
        movie_ids.append(mid)
        r.add(mid, AssetMetadata(
            type="movie", duration_sec=dur_sec,
            title=f"Movie {letter.upper()}", rating="R",
        ))

    # Collection entry: lookup("late_night") must return metadata with tags
    r.add("late_night", AssetMetadata(
        type="collection", duration_sec=0,
        tags=tuple(movie_ids),
    ))
    return r


def _crossmidnight_block_def() -> dict:
    return {
        "movie_marathon": {
            "start": "22:00",
            "end": "06:00",
            "title": "Late Night Marathon",
            "movie_selector": {
                "pool": "late_night",
                "mode": "random",
            },
            "allow_bleed": True,
        }
    }


class TestInvMarathonCrossmidnight001:
    """
    Invariant: INV-MARATHON-CROSSMIDNIGHT-001
    Derived from: LAW-GRID, LAW-LIVENESS
    Failure class: Planning fault
    """

    def test_crossmidnight_marathon_produces_blocks(self):
        """A 22:00–06:00 marathon MUST produce at least one block."""
        resolver = _make_resolver()
        blocks = _compile_movie_marathon(
            _crossmidnight_block_def(),
            "2026-03-01",
            "America/New_York",
            resolver,
            grid_minutes=30,
            seed=42,
        )
        assert len(blocks) > 0, "Cross-midnight marathon produced 0 blocks"

    def test_crossmidnight_blocks_start_after_2200(self):
        """All blocks from 22:00–06:00 marathon MUST start at or after 22:00 local."""
        resolver = _make_resolver()
        blocks = _compile_movie_marathon(
            _crossmidnight_block_def(),
            "2026-03-01",
            "America/New_York",
            resolver,
            grid_minutes=30,
            seed=42,
        )
        marathon_start = _parse_time("22:00", "2026-03-01", "America/New_York")
        for b in blocks:
            assert b.start_at >= marathon_start, (
                f"Block {b.title} starts at {b.start_at}, before marathon start"
            )

    def test_crossmidnight_end_resolves_to_next_day(self):
        """A 22:00–06:00 marathon MUST have its last block end AFTER midnight
        (i.e. on the next calendar day), proving end was resolved correctly."""
        resolver = _make_resolver()
        blocks = _compile_movie_marathon(
            _crossmidnight_block_def(),
            "2026-03-01",
            "America/New_York",
            resolver,
            grid_minutes=30,
            seed=42,
        )
        assert len(blocks) > 0, "Need blocks to verify end resolution"
        last_end = blocks[-1].end_at()
        marathon_start = _parse_time("22:00", "2026-03-01", "America/New_York")
        # The last block must end well past the start — at least 6 hours into
        # the 8-hour window, proving the end time resolved to the next day.
        assert last_end > marathon_start + timedelta(hours=6), (
            f"Last block ends at {last_end}, expected > 6h past start {marathon_start}; "
            f"06:00 end must resolve to next calendar day"
        )

    def test_crossmidnight_fills_window(self):
        """Cross-midnight marathon MUST fill most of its 8-hour window."""
        resolver = _make_resolver()
        blocks = _compile_movie_marathon(
            _crossmidnight_block_def(),
            "2026-03-01",
            "America/New_York",
            resolver,
            grid_minutes=30,
            seed=42,
        )
        total_sec = sum(b.slot_duration_sec for b in blocks)
        # 8 hours = 28800 seconds. Allow bleed may extend past, but
        # coverage must be substantial (at least 6 hours of the 8-hour window).
        assert total_sec >= 6 * 3600, (
            f"Cross-midnight marathon only covers {total_sec/3600:.1f}h, "
            f"expected at least 6h of the 8h window"
        )
