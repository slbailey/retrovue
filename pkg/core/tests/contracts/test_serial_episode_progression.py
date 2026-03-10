"""
Contract Tests: INV-SERIAL-EPISODE-PROGRESSION

Contract reference:
    pkg/core/docs/contracts/runtime/INV-SERIAL-EPISODE-PROGRESSION.md

These tests enforce deterministic serial episode progression for strip-
scheduled programs.  The tests validate occurrence counting, episode
selection, wrap policies, and scheduler-downtime independence using a
pure-function model that requires no database, no scheduler runtime,
and no mutable state.

Every test references the specific invariant(s) it enforces.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

import pytest


# =============================================================================
# Model: Occurrence Counter  (OC-001 through OC-005)
# =============================================================================


def count_occurrences(anchor: date, target: date, placement_days: int) -> int:
    """Count matching days in [anchor, target).

    Pure function.  Returns the number of dates d where:
        anchor <= d < target  AND  d.weekday() bit is set in placement_days.

    OC-001: Calendar-based only.
    OC-002: anchor date yields 0 (half-open: anchor itself is not counted
            because [anchor, anchor) is empty).
    OC-003: Half-open interval.
    OC-004: Pure / deterministic.
    OC-005: Arithmetic, not iteration over dates.
    """
    if target <= anchor:
        return 0

    total_days = (target - anchor).days
    full_weeks, remainder = divmod(total_days, 7)

    # Bits set in mask = occurrences per full week
    bits_per_week = bin(placement_days).count("1")
    count = full_weeks * bits_per_week

    # Partial week remainder
    anchor_dow = anchor.weekday()  # 0 = Monday
    for i in range(remainder):
        if placement_days & (1 << ((anchor_dow + i) % 7)):
            count += 1

    return count


# =============================================================================
# Model: Wrap Policy  (WP-001 through WP-003)
# =============================================================================

WRAP = "wrap"
HOLD_LAST = "hold_last"
STOP = "stop"

# Sentinel returned by apply_wrap_policy when policy is "stop" and
# the series is exhausted.
FILLER = None


def apply_wrap_policy(
    raw_index: int,
    episode_count: int,
    policy: str,
) -> int | None:
    """Map raw_index to effective episode index under the given policy.

    Returns an integer index, or FILLER (None) for 'stop' when exhausted.

    WP-001: wrap   → raw_index % episode_count
    WP-002: hold   → min(raw_index, episode_count - 1)
    WP-003: stop   → None when raw_index >= episode_count
    """
    if episode_count <= 0:
        return FILLER

    if policy == WRAP:
        return raw_index % episode_count
    if policy == HOLD_LAST:
        return min(raw_index, episode_count - 1)
    if policy == STOP:
        if raw_index >= episode_count:
            return FILLER
        return raw_index

    msg = f"Unknown wrap policy: {policy}"
    raise ValueError(msg)


# =============================================================================
# Model: Serial Episode Resolver  (INV-SERIAL-001 through INV-SERIAL-008)
# =============================================================================


@dataclass(frozen=True)
class SerialRun:
    """Test model of a serial_runs record."""

    channel_id: str
    placement_time: time
    placement_days: int          # 7-bit DOW bitmask, bit 0 = Monday
    content_source_id: str
    anchor_date: date
    anchor_episode_index: int
    wrap_policy: str             # "wrap", "hold_last", "stop"


def resolve_serial_episode(
    run: SerialRun,
    target_broadcast_day: date,
    episode_count: int,
) -> int | None:
    """Select the episode index for a target broadcast day.

    Pure function.  Returns an episode index, or FILLER (None) under
    the 'stop' policy when the series is exhausted.

    INV-SERIAL-001: Deterministic — same inputs always produce same output.
    INV-SERIAL-002: Independent of scheduler uptime.
    INV-SERIAL-006: Calendar-based occurrence counting.
    """
    occ = count_occurrences(run.anchor_date, target_broadcast_day, run.placement_days)
    raw_index = run.anchor_episode_index + occ
    return apply_wrap_policy(raw_index, episode_count, run.wrap_policy)


# =============================================================================
# Constants: Day-of-week bitmasks
# =============================================================================

MONDAY    = 1 << 0   # 1
TUESDAY   = 1 << 1   # 2
WEDNESDAY = 1 << 2   # 4
THURSDAY  = 1 << 3   # 8
FRIDAY    = 1 << 4   # 16
SATURDAY  = 1 << 5   # 32
SUNDAY    = 1 << 6   # 64

DAILY   = 0b1111111  # 127
WEEKDAY = 0b0011111  # 31
WEEKEND = 0b1100000  # 96

MWF = MONDAY | WEDNESDAY | FRIDAY  # 21


# =============================================================================
# 1. INV-SERIAL-001 + INV-SERIAL-006: Basic daily progression
# =============================================================================


class TestDailyStripProgression:
    """Daily strip: one episode per day, deterministic selection."""

    @pytest.fixture()
    def daily_run(self) -> SerialRun:
        return SerialRun(
            channel_id="kvue",
            placement_time=time(10, 0),
            placement_days=DAILY,
            content_source_id="bonanza",
            anchor_date=date(2026, 3, 2),   # Monday
            anchor_episode_index=0,
            wrap_policy=WRAP,
        )

    # Tier: 2 | Scheduling logic invariant
    def test_INV_SERIAL_001_anchor_date_selects_anchor_episode(
        self, daily_run: SerialRun,
    ) -> None:
        """INV-SERIAL-003: Anchor date always resolves to anchor episode."""
        idx = resolve_serial_episode(daily_run, date(2026, 3, 2), episode_count=100)
        assert idx == 0, (
            "INV-SERIAL-003 VIOLATION: anchor date must resolve to "
            f"anchor_episode_index (0), got {idx}"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_INV_SERIAL_001_sequential_daily_progression(
        self, daily_run: SerialRun,
    ) -> None:
        """INV-SERIAL-001: Mon→E00, Tue→E01, Wed→E02, Thu→E03, Fri→E04."""
        expected = {
            date(2026, 3, 2): 0,   # Mon
            date(2026, 3, 3): 1,   # Tue
            date(2026, 3, 4): 2,   # Wed
            date(2026, 3, 5): 3,   # Thu
            date(2026, 3, 6): 4,   # Fri
            date(2026, 3, 7): 5,   # Sat
            date(2026, 3, 8): 6,   # Sun
        }
        for target, want in expected.items():
            got = resolve_serial_episode(daily_run, target, episode_count=100)
            assert got == want, (
                f"INV-SERIAL-001 VIOLATION: {target.isoformat()} expected "
                f"episode {want}, got {got}"
            )

    # Tier: 2 | Scheduling logic invariant
    def test_INV_SERIAL_001_second_week_continues(
        self, daily_run: SerialRun,
    ) -> None:
        """INV-SERIAL-001: Progression continues across week boundary."""
        # Second Monday = 7 days after anchor = occurrence_count 7
        idx = resolve_serial_episode(daily_run, date(2026, 3, 9), episode_count=100)
        assert idx == 7, (
            f"INV-SERIAL-001 VIOLATION: second Monday expected episode 7, got {idx}"
        )


# =============================================================================
# 2. INV-SERIAL-001: Weekly show progression
# =============================================================================


class TestWeeklyShowProgression:
    """Weekly show: same day each week."""

    @pytest.fixture()
    def weekly_monday_run(self) -> SerialRun:
        return SerialRun(
            channel_id="kvue",
            placement_time=time(20, 0),
            placement_days=MONDAY,
            content_source_id="lost",
            anchor_date=date(2026, 3, 2),   # Monday
            anchor_episode_index=0,
            wrap_policy=WRAP,
        )

    # Tier: 2 | Scheduling logic invariant
    def test_INV_SERIAL_001_weekly_progression(
        self, weekly_monday_run: SerialRun,
    ) -> None:
        """INV-SERIAL-001: Mon W1→E00, Mon W2→E01, Mon W3→E02."""
        expected = {
            date(2026, 3, 2): 0,    # Week 1
            date(2026, 3, 9): 1,    # Week 2
            date(2026, 3, 16): 2,   # Week 3
            date(2026, 3, 23): 3,   # Week 4
        }
        for target, want in expected.items():
            got = resolve_serial_episode(weekly_monday_run, target, episode_count=100)
            assert got == want, (
                f"INV-SERIAL-001 VIOLATION: {target.isoformat()} expected "
                f"episode {want}, got {got}"
            )

    # Tier: 2 | Scheduling logic invariant
    def test_INV_SERIAL_006_non_matching_days_ignored(
        self, weekly_monday_run: SerialRun,
    ) -> None:
        """INV-SERIAL-006: Tuesday–Sunday are not occurrences for a Monday-only strip."""
        # Tuesday after anchor Monday — still 0 occurrences in [Mon, Tue)
        # because only Monday counts, and [Mar 2, Mar 3) contains only Mar 2.
        # Wait — Mar 2 is Mon, it IS an occurrence.  count_occurrences
        # returns 1 for [Mar 2, Mar 3) because Mar 2 (Monday) is in range.
        # But the anchor is Mar 2 itself, so occurrence_count = 1 means
        # one matching day passed (the anchor itself).
        idx_tue = resolve_serial_episode(weekly_monday_run, date(2026, 3, 3), episode_count=100)
        idx_next_mon = resolve_serial_episode(weekly_monday_run, date(2026, 3, 9), episode_count=100)
        assert idx_tue == 1, (
            "INV-SERIAL-006 VIOLATION: Tuesday should count 1 occurrence "
            f"(the anchor Monday), got {idx_tue}"
        )
        assert idx_next_mon == 1, (
            "INV-SERIAL-006 VIOLATION: next Monday should also count 1 "
            f"occurrence (same anchor Monday in range), got {idx_next_mon}"
        )


# =============================================================================
# 3. INV-SERIAL-002: Scheduler downtime
# =============================================================================


class TestSchedulerDowntime:
    """Scheduler offline for multiple days; progression must be correct."""

    @pytest.fixture()
    def weekday_run(self) -> SerialRun:
        return SerialRun(
            channel_id="kvue",
            placement_time=time(20, 0),
            placement_days=WEEKDAY,
            content_source_id="cheers",
            anchor_date=date(2026, 3, 2),   # Monday
            anchor_episode_index=0,
            wrap_policy=WRAP,
        )

    # Tier: 2 | Scheduling logic invariant
    def test_INV_SERIAL_002_daily_downtime_skips_correctly(
        self, weekday_run: SerialRun,
    ) -> None:
        """INV-SERIAL-002: Offline Tue–Thu, Friday still gets E04.

        Occurrences Mon–Fri in [anchor=Mon, target=Fri):
            Mon, Tue, Wed, Thu = 4 matching weekdays
        raw_index = 0 + 4 = 4
        """
        # Resolve Monday (anchor) — scheduler is up
        mon = resolve_serial_episode(weekday_run, date(2026, 3, 2), episode_count=100)
        assert mon == 0

        # Scheduler offline Tue–Thu.  No resolve calls.

        # Resolve Friday directly — scheduler comes back
        fri = resolve_serial_episode(weekday_run, date(2026, 3, 6), episode_count=100)
        assert fri == 4, (
            "INV-SERIAL-002 VIOLATION: after 3-day downtime, Friday must be "
            f"episode 4 (Mon=0,Tue=1,Wed=2,Thu=3,Fri=4), got {fri}"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_INV_SERIAL_002_full_week_downtime(
        self, weekday_run: SerialRun,
    ) -> None:
        """INV-SERIAL-002: Scheduler offline for an entire week."""
        # Next Monday = date(2026, 3, 9)
        # Occurrences in [Mar 2, Mar 9): Mon–Fri = 5 weekdays
        next_mon = resolve_serial_episode(weekday_run, date(2026, 3, 9), episode_count=100)
        assert next_mon == 5, (
            f"INV-SERIAL-002 VIOLATION: after full-week downtime expected 5, got {next_mon}"
        )


# =============================================================================
# 4. INV-SERIAL-001 + INV-SERIAL-006: Out-of-order resolution
# =============================================================================


class TestOutOfOrderResolution:
    """Resolving dates in non-chronological order must produce same results."""

    @pytest.fixture()
    def daily_run(self) -> SerialRun:
        return SerialRun(
            channel_id="kvue",
            placement_time=time(10, 0),
            placement_days=DAILY,
            content_source_id="seinfeld",
            anchor_date=date(2026, 3, 2),
            anchor_episode_index=0,
            wrap_policy=WRAP,
        )

    # Tier: 2 | Scheduling logic invariant
    def test_INV_SERIAL_006_resolve_friday_before_tuesday(
        self, daily_run: SerialRun,
    ) -> None:
        """INV-SERIAL-006: Resolution order does not affect results.

        Resolve Friday first, then Tuesday.  Both must return the same
        values as if resolved in chronological order.
        """
        # Resolve Friday first
        fri = resolve_serial_episode(daily_run, date(2026, 3, 6), episode_count=100)
        # Then resolve Tuesday
        tue = resolve_serial_episode(daily_run, date(2026, 3, 3), episode_count=100)

        assert fri == 4, f"INV-SERIAL-006 VIOLATION: Friday expected 4, got {fri}"
        assert tue == 1, f"INV-SERIAL-006 VIOLATION: Tuesday expected 1, got {tue}"

    # Tier: 2 | Scheduling logic invariant
    def test_INV_SERIAL_001_repeated_resolution_identical(
        self, daily_run: SerialRun,
    ) -> None:
        """INV-SERIAL-001: Resolving the same date twice yields same result."""
        first = resolve_serial_episode(daily_run, date(2026, 3, 5), episode_count=100)
        second = resolve_serial_episode(daily_run, date(2026, 3, 5), episode_count=100)
        assert first == second, (
            f"INV-SERIAL-001 VIOLATION: same date resolved twice produced "
            f"{first} then {second}"
        )


# =============================================================================
# 5. INV-SERIAL-008: Season boundary rollover
# =============================================================================


class TestSeasonBoundaryRollover:
    """Season boundaries are invisible to serial progression."""

    @pytest.fixture()
    def daily_run(self) -> SerialRun:
        return SerialRun(
            channel_id="kvue",
            placement_time=time(20, 0),
            placement_days=DAILY,
            content_source_id="cheers",
            anchor_date=date(2026, 3, 2),
            anchor_episode_index=0,
            wrap_policy=WRAP,
        )

    # Tier: 2 | Scheduling logic invariant
    def test_INV_SERIAL_008_crosses_season_boundary(
        self, daily_run: SerialRun,
    ) -> None:
        """INV-SERIAL-008: S01 has 22 episodes, S02 starts at index 22.

        Day 23 (0-indexed: occurrence 22) should select index 22 = S02E01.
        No special logic at the season boundary.
        """
        # 22 days after anchor → occurrence_count = 22
        target = date(2026, 3, 24)  # 22 days after Mar 2
        total_episodes = 46  # S01: 22 + S02: 24

        idx = resolve_serial_episode(daily_run, target, episode_count=total_episodes)
        assert idx == 22, (
            "INV-SERIAL-008 VIOLATION: season boundary rollover, expected "
            f"index 22 (S02E01), got {idx}"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_INV_SERIAL_008_last_episode_of_season(
        self, daily_run: SerialRun,
    ) -> None:
        """INV-SERIAL-008: Index 21 = S01E22 (last of season 1)."""
        target = date(2026, 3, 23)  # 21 days after Mar 2
        idx = resolve_serial_episode(daily_run, target, episode_count=46)
        assert idx == 21, (
            f"INV-SERIAL-008 VIOLATION: expected index 21 (S01E22), got {idx}"
        )


# =============================================================================
# 6. INV-SERIAL-004: Wrap policy behavior
# =============================================================================


class TestWrapPolicy:
    """Wrap policies: wrap, hold_last, stop."""

    @pytest.fixture()
    def five_episode_run(self) -> SerialRun:
        """Daily strip with only 5 episodes, starting Monday."""
        return SerialRun(
            channel_id="kvue",
            placement_time=time(10, 0),
            placement_days=DAILY,
            content_source_id="miniseries",
            anchor_date=date(2026, 3, 2),   # Monday
            anchor_episode_index=0,
            wrap_policy=WRAP,
        )

    # Tier: 2 | Scheduling logic invariant
    def test_INV_SERIAL_004_wrap_cycles_back(
        self, five_episode_run: SerialRun,
    ) -> None:
        """WP-001: After 5 episodes, wrap returns to episode 0."""
        # Day 6 (Saturday) → occurrence_count = 5, raw_index = 5
        # 5 % 5 = 0
        run = five_episode_run
        idx = resolve_serial_episode(run, date(2026, 3, 7), episode_count=5)
        assert idx == 0, f"WP-001 VIOLATION: expected wrap to 0, got {idx}"

        # Day 7 (Sunday) → occurrence_count = 6, raw_index = 6
        # 6 % 5 = 1
        idx = resolve_serial_episode(run, date(2026, 3, 8), episode_count=5)
        assert idx == 1, f"WP-001 VIOLATION: expected wrap to 1, got {idx}"

    # Tier: 2 | Scheduling logic invariant
    def test_INV_SERIAL_004_hold_last_repeats_final(self) -> None:
        """WP-002: hold_last repeats the last episode indefinitely."""
        run = SerialRun(
            channel_id="kvue",
            placement_time=time(10, 0),
            placement_days=DAILY,
            content_source_id="miniseries",
            anchor_date=date(2026, 3, 2),
            anchor_episode_index=0,
            wrap_policy=HOLD_LAST,
        )
        # Day 5 (Saturday, occ=5): raw_index=5, min(5, 4)=4
        idx_sat = resolve_serial_episode(run, date(2026, 3, 7), episode_count=5)
        assert idx_sat == 4, f"WP-002 VIOLATION: expected hold at 4, got {idx_sat}"

        # Day 30: still holds at 4
        idx_far = resolve_serial_episode(run, date(2026, 4, 1), episode_count=5)
        assert idx_far == 4, f"WP-002 VIOLATION: expected hold at 4, got {idx_far}"

    # Tier: 2 | Scheduling logic invariant
    def test_INV_SERIAL_004_stop_returns_filler(self) -> None:
        """WP-003: stop returns FILLER after last episode."""
        run = SerialRun(
            channel_id="kvue",
            placement_time=time(10, 0),
            placement_days=DAILY,
            content_source_id="miniseries",
            anchor_date=date(2026, 3, 2),
            anchor_episode_index=0,
            wrap_policy=STOP,
        )
        # Day 5 (last valid): raw_index=4, 4 < 5 → 4
        idx_fri = resolve_serial_episode(run, date(2026, 3, 6), episode_count=5)
        assert idx_fri == 4, f"WP-003 VIOLATION: expected 4, got {idx_fri}"

        # Day 6 (exhausted): raw_index=5, 5 >= 5 → FILLER
        idx_sat = resolve_serial_episode(run, date(2026, 3, 7), episode_count=5)
        assert idx_sat is FILLER, (
            f"WP-003 VIOLATION: expected FILLER after exhaustion, got {idx_sat}"
        )

        # Day 30: still FILLER
        idx_far = resolve_serial_episode(run, date(2026, 4, 1), episode_count=5)
        assert idx_far is FILLER, (
            f"WP-003 VIOLATION: expected FILLER long after exhaustion, got {idx_far}"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_INV_SERIAL_004_last_valid_episode_before_exhaustion(self) -> None:
        """All three policies agree on the last valid episode."""
        anchor = date(2026, 3, 2)
        last_day = date(2026, 3, 6)  # occ_count=4, raw_index=4, ep_count=5

        for policy in (WRAP, HOLD_LAST, STOP):
            run = SerialRun(
                channel_id="kvue",
                placement_time=time(10, 0),
                placement_days=DAILY,
                content_source_id="miniseries",
                anchor_date=anchor,
                anchor_episode_index=0,
                wrap_policy=policy,
            )
            idx = resolve_serial_episode(run, last_day, episode_count=5)
            assert idx == 4, (
                f"Policy '{policy}' should select episode 4 on last valid day, "
                f"got {idx}"
            )


# =============================================================================
# 7. INV-SERIAL-007: Anchor validation
# =============================================================================


class TestAnchorValidation:
    """Anchor date must match the placement day pattern."""

    # Tier: 2 | Scheduling logic invariant
    def test_INV_SERIAL_007_anchor_on_matching_day(self) -> None:
        """INV-SERIAL-007: Anchor on Monday for a weekday strip is valid."""
        anchor = date(2026, 3, 2)  # Monday
        assert anchor.weekday() == 0  # Monday
        assert (1 << anchor.weekday()) & WEEKDAY != 0

    # Tier: 2 | Scheduling logic invariant
    def test_INV_SERIAL_007_anchor_on_non_matching_day_is_invalid(self) -> None:
        """INV-SERIAL-007: Anchor on Saturday for a weekday strip is invalid."""
        anchor = date(2026, 3, 7)  # Saturday
        assert anchor.weekday() == 5  # Saturday
        assert (1 << anchor.weekday()) & WEEKDAY == 0, (
            "INV-SERIAL-007 VIOLATION: Saturday bit must not be set in weekday mask"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_INV_SERIAL_007_anchor_on_sunday_for_weekend_strip(self) -> None:
        """INV-SERIAL-007: Anchor on Sunday for a weekend strip is valid."""
        anchor = date(2026, 3, 8)  # Sunday
        assert anchor.weekday() == 6
        assert (1 << anchor.weekday()) & WEEKEND != 0


# =============================================================================
# 8. INV-SERIAL-005: Placement identity stability
# =============================================================================


class TestPlacementIdentityStability:
    """Two runs with different placement identities are independent."""

    # Tier: 2 | Scheduling logic invariant
    def test_INV_SERIAL_005_same_show_different_times_independent(self) -> None:
        """PI-002: Bonanza at 10:00 and Bonanza at 23:00 are separate strips."""
        morning = SerialRun(
            channel_id="kvue",
            placement_time=time(10, 0),
            placement_days=DAILY,
            content_source_id="bonanza",
            anchor_date=date(2026, 3, 2),
            anchor_episode_index=0,   # Morning starts at E00
            wrap_policy=WRAP,
        )
        night = SerialRun(
            channel_id="kvue",
            placement_time=time(23, 0),
            placement_days=DAILY,
            content_source_id="bonanza",
            anchor_date=date(2026, 3, 2),
            anchor_episode_index=50,  # Night starts at E50
            wrap_policy=WRAP,
        )

        target = date(2026, 3, 5)  # Thursday, occurrence_count = 3

        morning_idx = resolve_serial_episode(morning, target, episode_count=200)
        night_idx = resolve_serial_episode(night, target, episode_count=200)

        assert morning_idx == 3, f"Morning strip expected 3, got {morning_idx}"
        assert night_idx == 53, f"Night strip expected 53, got {night_idx}"
        assert morning_idx != night_idx

    # Tier: 2 | Scheduling logic invariant
    def test_INV_SERIAL_005_same_time_different_days_independent(self) -> None:
        """PI-002: Bonanza weekday and Movies weekend at 10:00 are separate."""
        weekday_strip = SerialRun(
            channel_id="kvue",
            placement_time=time(10, 0),
            placement_days=WEEKDAY,
            content_source_id="bonanza",
            anchor_date=date(2026, 3, 2),   # Monday
            anchor_episode_index=0,
            wrap_policy=WRAP,
        )
        weekend_strip = SerialRun(
            channel_id="kvue",
            placement_time=time(10, 0),
            placement_days=WEEKEND,
            content_source_id="movies",
            anchor_date=date(2026, 3, 7),   # Saturday
            anchor_episode_index=0,
            wrap_policy=WRAP,
        )

        # Saturday Mar 7: weekday strip has 5 occ [Mon-Fri], weekend has 0
        wkday_sat = resolve_serial_episode(weekday_strip, date(2026, 3, 7), episode_count=100)
        wkend_sat = resolve_serial_episode(weekend_strip, date(2026, 3, 7), episode_count=100)

        assert wkday_sat == 5   # Mon-Fri = 5 weekday occurrences
        assert wkend_sat == 0   # Saturday is anchor, occurrence_count = 0


# =============================================================================
# 9. OC-001 through OC-005: Occurrence counter edge cases
# =============================================================================


class TestOccurrenceCounter:
    """Direct tests of count_occurrences()."""

    # Tier: 2 | Scheduling logic invariant
    def test_OC_002_anchor_equals_target_returns_zero(self) -> None:
        """OC-002: [anchor, anchor) is empty, returns 0."""
        assert count_occurrences(date(2026, 3, 2), date(2026, 3, 2), DAILY) == 0

    # Tier: 2 | Scheduling logic invariant
    def test_OC_003_single_day_interval(self) -> None:
        """OC-003: [Mon, Tue) contains one day (Monday)."""
        # Monday, DAILY mask
        assert count_occurrences(date(2026, 3, 2), date(2026, 3, 3), DAILY) == 1

    # Tier: 2 | Scheduling logic invariant
    def test_OC_003_single_day_non_matching(self) -> None:
        """OC-003: [Mon, Tue) with WEEKEND mask contains zero matching days."""
        assert count_occurrences(date(2026, 3, 2), date(2026, 3, 3), WEEKEND) == 0

    # Tier: 2 | Scheduling logic invariant
    def test_OC_001_full_week_daily(self) -> None:
        """OC-001: 7 days with daily mask = 7 occurrences."""
        assert count_occurrences(date(2026, 3, 2), date(2026, 3, 9), DAILY) == 7

    # Tier: 2 | Scheduling logic invariant
    def test_OC_001_full_week_weekday(self) -> None:
        """OC-001: 7 days with weekday mask = 5 occurrences (Mon-Fri)."""
        assert count_occurrences(date(2026, 3, 2), date(2026, 3, 9), WEEKDAY) == 5

    # Tier: 2 | Scheduling logic invariant
    def test_OC_001_full_week_weekend(self) -> None:
        """OC-001: 7 days starting Monday with weekend mask = 2 (Sat+Sun)."""
        assert count_occurrences(date(2026, 3, 2), date(2026, 3, 9), WEEKEND) == 2

    # Tier: 2 | Scheduling logic invariant
    def test_OC_001_two_weeks_mwf(self) -> None:
        """OC-001: 14 days with Mon/Wed/Fri mask = 6 occurrences."""
        assert count_occurrences(date(2026, 3, 2), date(2026, 3, 16), MWF) == 6

    # Tier: 2 | Scheduling logic invariant
    def test_OC_004_deterministic_same_call_twice(self) -> None:
        """OC-004: Same inputs always produce same output."""
        a = count_occurrences(date(2026, 3, 2), date(2026, 6, 15), WEEKDAY)
        b = count_occurrences(date(2026, 3, 2), date(2026, 6, 15), WEEKDAY)
        assert a == b

    # Tier: 2 | Scheduling logic invariant
    def test_OC_005_large_range_is_efficient(self) -> None:
        """OC-005: 10 years of daily occurrences computed without iteration."""
        anchor = date(2026, 1, 1)
        target = date(2036, 1, 1)
        result = count_occurrences(anchor, target, DAILY)
        expected = (target - anchor).days  # Every day matches
        assert result == expected

    # Tier: 2 | Scheduling logic invariant
    def test_OC_001_target_before_anchor_returns_zero(self) -> None:
        """OC-003: target <= anchor returns 0."""
        assert count_occurrences(date(2026, 3, 9), date(2026, 3, 2), DAILY) == 0

    # Tier: 2 | Scheduling logic invariant
    def test_OC_001_partial_week_from_wednesday(self) -> None:
        """OC-001: [Wed, Mon) = Wed,Thu,Fri,Sat,Sun = 5 days."""
        # With weekday mask: Wed, Thu, Fri = 3
        assert count_occurrences(date(2026, 3, 4), date(2026, 3, 9), WEEKDAY) == 3

    # Tier: 2 | Scheduling logic invariant
    def test_OC_001_monday_only_across_multiple_weeks(self) -> None:
        """OC-001: Monday-only mask across 3 weeks = 3 Mondays."""
        # [Mar 2, Mar 23) = 21 days = 3 full weeks, 3 Mondays
        assert count_occurrences(date(2026, 3, 2), date(2026, 3, 23), MONDAY) == 3


# =============================================================================
# 10. MWF recurrence pattern
# =============================================================================


class TestMWFStripProgression:
    """Mon/Wed/Fri strip: non-daily recurrence pattern."""

    @pytest.fixture()
    def mwf_run(self) -> SerialRun:
        return SerialRun(
            channel_id="kvue",
            placement_time=time(20, 0),
            placement_days=MWF,
            content_source_id="jeopardy",
            anchor_date=date(2026, 3, 2),   # Monday
            anchor_episode_index=0,
            wrap_policy=WRAP,
        )

    # Tier: 2 | Scheduling logic invariant
    def test_INV_SERIAL_001_mwf_progression(self, mwf_run: SerialRun) -> None:
        """INV-SERIAL-001: Mon→E00, Wed→E01, Fri→E02, next Mon→E03."""
        cases = {
            date(2026, 3, 2): 0,    # Mon (anchor)
            date(2026, 3, 4): 1,    # Wed: [Mon, Wed) has Mon = 1 occ
            date(2026, 3, 6): 2,    # Fri: [Mon, Fri) has Mon,Wed = 2 occ
            date(2026, 3, 9): 3,    # Next Mon: [Mon, Mon+7) has Mon,Wed,Fri = 3 occ
            date(2026, 3, 11): 4,   # Next Wed: 4 occ
            date(2026, 3, 13): 5,   # Next Fri: 5 occ
        }
        for target, want in cases.items():
            got = resolve_serial_episode(mwf_run, target, episode_count=100)
            assert got == want, (
                f"INV-SERIAL-001 VIOLATION: MWF strip on {target.isoformat()} "
                f"expected {want}, got {got}"
            )

    # Tier: 2 | Scheduling logic invariant
    def test_INV_SERIAL_002_mwf_downtime(self, mwf_run: SerialRun) -> None:
        """INV-SERIAL-002: Offline for 2 weeks, third Monday correct."""
        # [Mar 2, Mar 16) = 14 days = 2 weeks.  MWF per week = 3.  2*3 = 6.
        idx = resolve_serial_episode(mwf_run, date(2026, 3, 16), episode_count=100)
        assert idx == 6, (
            f"INV-SERIAL-002 VIOLATION: MWF 2-week downtime expected 6, got {idx}"
        )


# =============================================================================
# 11. INV-SERIAL-003: Anchor episode index offset
# =============================================================================


class TestAnchorEpisodeOffset:
    """Anchor can start at a non-zero episode index."""

    # Tier: 2 | Scheduling logic invariant
    def test_INV_SERIAL_003_non_zero_anchor_index(self) -> None:
        """INV-SERIAL-003: If anchor_episode_index=10, anchor date → E10."""
        run = SerialRun(
            channel_id="kvue",
            placement_time=time(10, 0),
            placement_days=DAILY,
            content_source_id="cheers",
            anchor_date=date(2026, 3, 2),
            anchor_episode_index=10,
            wrap_policy=WRAP,
        )
        # Anchor date → E10
        assert resolve_serial_episode(run, date(2026, 3, 2), episode_count=200) == 10

        # Day 3 (Wed) → occ=1, raw=11
        assert resolve_serial_episode(run, date(2026, 3, 3), episode_count=200) == 11

        # Day 7 (Sun) → occ=5, raw=15
        assert resolve_serial_episode(run, date(2026, 3, 7), episode_count=200) == 15

    # Tier: 2 | Scheduling logic invariant
    def test_INV_SERIAL_003_anchor_index_with_wrap(self) -> None:
        """INV-SERIAL-003 + WP-001: Non-zero anchor wraps correctly."""
        run = SerialRun(
            channel_id="kvue",
            placement_time=time(10, 0),
            placement_days=DAILY,
            content_source_id="miniseries",
            anchor_date=date(2026, 3, 2),
            anchor_episode_index=3,   # Start at E03
            wrap_policy=WRAP,
        )
        # 5 episodes total.  anchor=3, so 2 more until wrap.
        # Day 3 (occ=2): raw=5, 5%5=0 → wrapped to E00
        idx = resolve_serial_episode(run, date(2026, 3, 4), episode_count=5)
        assert idx == 0, (
            f"INV-SERIAL-003+WP-001 VIOLATION: expected wrap to 0, got {idx}"
        )


# =============================================================================
# 12. Integration: multiple strips on same channel
# =============================================================================


class TestMultipleStripsOnChannel:
    """Multiple concurrent strips on the same channel, fully independent."""

    # Tier: 2 | Scheduling logic invariant
    def test_PI_002_three_strips_no_interference(self) -> None:
        """PI-002: Three strips on KVUE progress independently."""
        bonanza_morning = SerialRun(
            channel_id="kvue",
            placement_time=time(10, 0),
            placement_days=WEEKDAY,
            content_source_id="bonanza",
            anchor_date=date(2026, 3, 2),
            anchor_episode_index=0,
            wrap_policy=WRAP,
        )
        bonanza_night = SerialRun(
            channel_id="kvue",
            placement_time=time(23, 0),
            placement_days=DAILY,
            content_source_id="bonanza",
            anchor_date=date(2026, 3, 2),
            anchor_episode_index=100,
            wrap_policy=HOLD_LAST,
        )
        movies_weekend = SerialRun(
            channel_id="kvue",
            placement_time=time(10, 0),
            placement_days=WEEKEND,
            content_source_id="movies",
            anchor_date=date(2026, 3, 7),   # Saturday
            anchor_episode_index=0,
            wrap_policy=STOP,
        )

        # Resolve all three for Saturday Mar 7
        target = date(2026, 3, 7)

        # bonanza_morning: weekday strip, [Mon Mar 2, Sat Mar 7) = Mon-Fri = 5
        bm = resolve_serial_episode(bonanza_morning, target, episode_count=200)
        assert bm == 5

        # bonanza_night: daily strip, [Mon Mar 2, Sat Mar 7) = 5 days
        bn = resolve_serial_episode(bonanza_night, target, episode_count=200)
        assert bn == 105  # 100 + 5

        # movies_weekend: weekend strip, anchor IS Saturday, occ=0
        mw = resolve_serial_episode(movies_weekend, target, episode_count=50)
        assert mw == 0

        # All three are independent
        assert len({bm, bn, mw}) == 3
