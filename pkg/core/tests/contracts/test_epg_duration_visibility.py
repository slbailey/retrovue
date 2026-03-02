"""
Contract tests for INV-EPG-DURATION-VISIBILITY-001.

Tests the three pure functions that implement duration visibility:
  - is_grid_aligned(start_minute, end_minute, slot_duration_sec)
  - format_human_duration(slot_duration_sec)
  - epg_display_duration(start_time, end_time, slot_duration_sec)

Each test maps to a row in TEST-MATRIX-EPG.md Section 6.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from retrovue.epg.duration import (
    epg_display_duration,
    format_human_duration,
    is_grid_aligned,
)


def _utc(hour: int, minute: int, second: int = 0) -> datetime:
    """Build a UTC datetime on a fixed date for test clarity."""
    return datetime(2026, 3, 1, hour, minute, second, tzinfo=timezone.utc)


class TestInvEpgDurationVisibility001:
    """
    Invariant: INV-EPG-DURATION-VISIBILITY-001
    Derived from: LAW-GRID, LAW-DERIVATION
    Failure class: Planning fault
    """

    # -- A) Grid-aligned 30 min item: not shown -------------------------

    def test_grid_aligned_30min_not_shown(self):
        """TEPG-DV-001: 09:00–09:30 (30min) is grid-implicit. No duration shown."""
        start = _utc(9, 0)
        end = _utc(9, 30)
        slot_sec = 30 * 60  # 1800

        assert is_grid_aligned(start.minute, end.minute, slot_sec) is True
        assert epg_display_duration(start, end, slot_sec) is None

    # -- B) Grid-aligned 60 min item: not shown -------------------------

    def test_grid_aligned_60min_not_shown(self):
        """TEPG-DV-002: 09:00–10:00 (60min) is grid-implicit. No duration shown."""
        start = _utc(9, 0)
        end = _utc(10, 0)
        slot_sec = 60 * 60

        assert is_grid_aligned(start.minute, end.minute, slot_sec) is True
        assert epg_display_duration(start, end, slot_sec) is None

    # -- C) Grid-aligned 120 min item: not shown ------------------------

    def test_grid_aligned_120min_not_shown(self):
        """TEPG-DV-003: 09:00–11:00 (120min) is grid-implicit. No duration shown."""
        start = _utc(9, 0)
        end = _utc(11, 0)
        slot_sec = 120 * 60

        assert is_grid_aligned(start.minute, end.minute, slot_sec) is True
        assert epg_display_duration(start, end, slot_sec) is None

    # -- D) 2h 5m movie: duration shown as "2h 5m" ---------------------

    def test_125min_shown_as_2h_5m(self):
        """TEPG-DV-004: 09:00–11:05 (125min) disrupts grid. Show '2h 5m'."""
        start = _utc(9, 0)
        end = _utc(11, 5)
        slot_sec = 125 * 60

        assert is_grid_aligned(start.minute, end.minute, slot_sec) is False
        result = epg_display_duration(start, end, slot_sec)
        assert result == "2h 5m"

    # -- E) 89.5 min rounds to 90, grid-aligned: not shown -------------

    def test_89_5min_rounds_to_90_grid_aligned(self):
        """TEPG-DV-005: 89.5min rounds to 90. 09:00–10:29:30 → grid-aligned after rounding."""
        start = _utc(9, 0)
        end = _utc(10, 29, 30)
        slot_sec = int(89.5 * 60)  # 5370 seconds

        # Rounding happens BEFORE grid evaluation:
        #   5370s / 60 = 89.5 → round to 90 → 90 % 30 == 0
        #   start.minute == 0 ∈ {0, 30}
        #   end.minute == 29 ∉ {0, 30} — but rounding makes the duration grid-aligned,
        #   and the end time's minute is evaluated from start + rounded duration.
        # The invariant defines grid alignment on rounded_duration and start/end minutes
        # derived from the slot boundary. Since the slot is 5370s, the end minute from
        # start + slot is 10:29:30 (minute=29). However, the rounded duration (90min)
        # IS a multiple of 30. The spec says rounding happens BEFORE grid evaluation,
        # meaning the rounded duration drives the check — a 90-minute rounded slot
        # starting at :00 ending at :30 (start + 90min = 10:30 minute=30) is grid-implicit.
        #
        # The display_duration function uses start_time + rounded_duration to compute
        # the effective end minute for grid alignment.
        assert epg_display_duration(start, end, slot_sec) is None

    # -- F) 90.5 min rounds to 91: show "1h 31m" -----------------------

    def test_90_5min_rounds_to_91_shown(self):
        """TEPG-DV-006: 90.5min rounds to 91. 91 % 30 != 0. Show '1h 31m'."""
        start = _utc(9, 0)
        end = _utc(10, 30, 30)
        slot_sec = int(90.5 * 60)  # 5430 seconds

        result = epg_display_duration(start, end, slot_sec)
        assert result == "1h 31m"

    # -- G) 45 min item: show "45m" ------------------------------------

    def test_45min_shown(self):
        """TEPG-DV-007: 09:00–09:45 (45min). 45 % 30 != 0. Show '45m'."""
        start = _utc(9, 0)
        end = _utc(9, 45)
        slot_sec = 45 * 60

        assert is_grid_aligned(start.minute, end.minute, slot_sec) is False
        result = epg_display_duration(start, end, slot_sec)
        assert result == "45m"

    # -- H) 30 min off-grid: show "30m" --------------------------------

    def test_30min_off_grid_shown(self):
        """TEPG-DV-008: 09:05–09:35 (30min). Start off-grid. Show '30m'."""
        start = _utc(9, 5)
        end = _utc(9, 35)
        slot_sec = 30 * 60

        assert is_grid_aligned(start.minute, end.minute, slot_sec) is False
        result = epg_display_duration(start, end, slot_sec)
        assert result == "30m"

    # -- I) No decimals ever appear in output ---------------------------

    def test_no_decimals_in_output(self):
        """TEPG-DV-009: No formatted output contains decimal points."""
        test_cases = [
            # (slot_duration_sec, description)
            (45 * 60, "45min"),
            (int(89.5 * 60), "89.5min"),
            (int(90.5 * 60), "90.5min"),
            (125 * 60, "125min"),
            (37 * 60, "37min"),
            (int(119.7 * 60), "119.7min"),
            (61 * 60, "61min"),
        ]
        start = _utc(9, 0)
        for slot_sec, desc in test_cases:
            end = start + __import__("datetime").timedelta(seconds=slot_sec)
            result = epg_display_duration(start, end, slot_sec)
            if result is not None:
                assert "." not in result, (
                    f"Decimal found in display_duration for {desc}: {result!r}"
                )

    # -- J) Content shorter than grid slot: show content duration ---------

    def test_content_shorter_than_slot_shows_content_duration(self):
        """TEPG-DV-010: 90.5min movie in 120min grid slot. Show content duration '1h 31m'."""
        start = _utc(9, 0)
        end = _utc(11, 0)  # 120min slot, grid-aligned
        slot_sec = 120 * 60
        ep_sec = int(90.5 * 60)  # 5430s — content is 90.5min

        # Slot alone would be grid-implicit (120min, :00→:00).
        # But content duration (90.5min → rounds to 91 → 91 % 30 != 0) disrupts the grid.
        result = epg_display_duration(start, end, slot_sec, ep_sec)
        assert result == "1h 31m"

    def test_content_equals_slot_grid_aligned(self):
        """Content fills the slot exactly and both are grid-aligned. No duration shown."""
        start = _utc(9, 0)
        end = _utc(10, 0)
        slot_sec = 60 * 60
        ep_sec = 60 * 60

        assert epg_display_duration(start, end, slot_sec, ep_sec) is None

    def test_content_grid_aligned_in_larger_slot(self):
        """90min content in 120min slot. 90 % 30 == 0, starts on grid. Not shown."""
        start = _utc(9, 0)
        end = _utc(11, 0)
        slot_sec = 120 * 60
        ep_sec = 90 * 60  # exactly 90min — grid-aligned

        assert epg_display_duration(start, end, slot_sec, ep_sec) is None

    # -- K) TV episodes never show duration --------------------------------

    def test_tv_episode_never_shows_duration(self):
        """TEPG-DV-013: TV episode with non-grid content. Grid check runs, but
        duration formatting is suppressed because is_movie=False."""
        start = _utc(9, 0)
        end = _utc(9, 45)
        slot_sec = 45 * 60
        ep_sec = 22 * 60  # 22min sitcom in 45min slot

        # Grid check runs — 22min is not grid-aligned
        assert is_grid_aligned(start.minute, _utc(9, 22).minute, ep_sec) is False

        # But is_movie=False suppresses the formatted output
        assert epg_display_duration(start, end, slot_sec, ep_sec, is_movie=False) is None

        # Same inputs as movie would show duration
        assert epg_display_duration(start, end, slot_sec, ep_sec, is_movie=True) is not None

    def test_movie_no_season_shows_duration(self):
        """TEPG-DV-014: Movie (is_movie=True) uses normal duration visibility rules."""
        start = _utc(9, 0)
        end = _utc(11, 0)
        slot_sec = 120 * 60
        ep_sec = int(90.5 * 60)

        assert epg_display_duration(start, end, slot_sec, ep_sec, is_movie=True) == "1h 31m"

    def test_tv_episode_grid_aligned_returns_none(self):
        """TEPG-DV-015: TV episode that IS grid-aligned. Grid check passes → None."""
        start = _utc(9, 0)
        end = _utc(9, 30)
        slot_sec = 30 * 60
        ep_sec = 22 * 60

        # Grid-aligned by slot boundaries, so None even before is_movie check
        assert epg_display_duration(start, end, slot_sec, ep_sec, is_movie=False) is None

    # -- Formatting unit tests ------------------------------------------

    def test_format_sub_60(self):
        """format_human_duration for durations under 60 minutes."""
        assert format_human_duration(45 * 60) == "45m"
        assert format_human_duration(1 * 60) == "1m"
        assert format_human_duration(59 * 60) == "59m"

    def test_format_exact_hours(self):
        """format_human_duration for exact hour multiples."""
        assert format_human_duration(60 * 60) == "1h"
        assert format_human_duration(120 * 60) == "2h"
        assert format_human_duration(180 * 60) == "3h"

    def test_format_hours_and_minutes(self):
        """format_human_duration for hours + remainder."""
        assert format_human_duration(91 * 60) == "1h 31m"
        assert format_human_duration(125 * 60) == "2h 5m"
        assert format_human_duration(61 * 60) == "1h 1m"

    def test_format_rounds_fractional_seconds(self):
        """format_human_duration rounds fractional minutes before formatting."""
        assert format_human_duration(int(89.5 * 60)) == "1h 30m"  # 5370s → 89.5 → 90min
        assert format_human_duration(int(90.5 * 60)) == "1h 31m"  # 5430s → 90.5 → 91min
