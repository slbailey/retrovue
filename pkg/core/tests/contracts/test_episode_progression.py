"""
Contract Tests: Episode Progression Invariants

Canonical contract:
    docs/contracts/episode_progression.md

Test matrix:
    docs/contracts/TEST-MATRIX-SCHEDULING-CONSTITUTION.md

These tests enforce the Episode Progression invariants
(INV-EPISODE-PROGRESSION-001 through INV-EPISODE-PROGRESSION-012) using the
production resolver.  No resolver logic is reimplemented here — all episode
selection flows through the production functions.

Every test references the specific invariant(s) and test-matrix ID(s) it
validates.
"""

from __future__ import annotations

import time as _time
from datetime import date, time, timedelta

import pytest

from retrovue.runtime.serial_episode_resolver import (
    DAILY,
    FILLER,
    FRIDAY,
    MONDAY,
    SATURDAY,
    SUNDAY,
    TUESDAY,
    WEDNESDAY,
    WEEKDAY,
    WEEKEND,
    SerialRunInfo,
    apply_wrap_policy,
    count_occurrences,
    resolve_serial_episode,
    validate_anchor,
)


# =============================================================================
# Fixed dates — all tests use deterministic calendar constants.
# =============================================================================

MON_JAN_06 = date(2025, 1, 6)   # Monday
TUE_JAN_07 = date(2025, 1, 7)   # Tuesday
WED_JAN_08 = date(2025, 1, 8)   # Wednesday
THU_JAN_09 = date(2025, 1, 9)   # Thursday
FRI_JAN_10 = date(2025, 1, 10)  # Friday
SAT_JAN_11 = date(2025, 1, 11)  # Saturday
SUN_JAN_12 = date(2025, 1, 12)  # Sunday
MON_JAN_13 = date(2025, 1, 13)  # Monday (week 2)
TUE_JAN_14 = date(2025, 1, 14)  # Tuesday (week 2)
WED_JAN_15 = date(2025, 1, 15)  # Wednesday (week 2)
FRI_JAN_17 = date(2025, 1, 17)  # Friday (week 2)
MON_JAN_20 = date(2025, 1, 20)  # Monday (week 3)

EPISODE_COUNT = 100  # Default catalog size for most tests.


# =============================================================================
# Helpers
# =============================================================================


def _make_run(
    *,
    anchor_date: date = MON_JAN_06,
    placement_days: int = DAILY,
    anchor_episode_index: int = 0,
    wrap_policy: str = "wrap",
    channel_id: str = "ch-test",
    placement_time: time = time(10, 0),
    content_source_id: str = "show-a",
) -> SerialRunInfo:
    """Build a SerialRunInfo with sensible defaults."""
    return SerialRunInfo(
        channel_id=channel_id,
        placement_time=placement_time,
        placement_days=placement_days,
        content_source_id=content_source_id,
        anchor_date=anchor_date,
        anchor_episode_index=anchor_episode_index,
        wrap_policy=wrap_policy,
    )


def _resolve(run: SerialRunInfo, target: date, episode_count: int = EPISODE_COUNT) -> int | None:
    """Convenience wrapper around resolve_serial_episode."""
    return resolve_serial_episode(run, target, episode_count)


# =============================================================================
# Test Groups
# =============================================================================


@pytest.mark.contract
class TestDeterminism:
    """Validates INV-EPISODE-PROGRESSION-001 — Deterministic episode selection."""

    # Tier: 2 | Scheduling logic invariant
    def test_anchor_date_selects_anchor_episode(self) -> None:
        """EP-DETERM-001: Anchor date resolves to anchor episode index."""
        # Validates INV-EPISODE-PROGRESSION-001
        run = _make_run(anchor_date=MON_JAN_06, anchor_episode_index=0)
        assert _resolve(run, MON_JAN_06) == 0

    # Tier: 2 | Scheduling logic invariant
    def test_daily_sequential_progression(self) -> None:
        """EP-DETERM-002: Daily sequential progression Mon→E0, Tue→E1, Wed→E2."""
        # Validates INV-EPISODE-PROGRESSION-001
        run = _make_run(anchor_date=MON_JAN_06, placement_days=DAILY)
        assert _resolve(run, MON_JAN_06) == 0
        assert _resolve(run, TUE_JAN_07) == 1
        assert _resolve(run, WED_JAN_08) == 2
        assert _resolve(run, THU_JAN_09) == 3
        assert _resolve(run, FRI_JAN_10) == 4

    # Tier: 2 | Scheduling logic invariant
    def test_second_week_continues(self) -> None:
        """EP-DETERM-003: Progression crosses week boundary without reset."""
        # Validates INV-EPISODE-PROGRESSION-001
        run = _make_run(anchor_date=MON_JAN_06, placement_days=DAILY)
        assert _resolve(run, SUN_JAN_12) == 6   # End of week 1
        assert _resolve(run, MON_JAN_13) == 7   # Start of week 2

    # Tier: 2 | Scheduling logic invariant
    def test_repeated_resolution_identical(self) -> None:
        """EP-DETERM-004: Same date resolved twice yields identical result."""
        # Validates INV-EPISODE-PROGRESSION-001
        run = _make_run(anchor_date=MON_JAN_06, placement_days=DAILY)
        first = _resolve(run, WED_JAN_08)
        second = _resolve(run, WED_JAN_08)
        assert first == second


@pytest.mark.contract
class TestRestartInvariance:
    """Validates INV-EPISODE-PROGRESSION-002 — Restart invariance."""

    # Tier: 2 | Scheduling logic invariant
    def test_scheduler_downtime_daily(self) -> None:
        """EP-RESTART-001: Scheduler offline Tue–Thu; Friday selects correct episode.

        The scheduler did not compile Tue, Wed, or Thu.  When it resumes on
        Friday, the episode must be E4 (not E1, which is what a counter-based
        system that lost state would produce).
        """
        # Validates INV-EPISODE-PROGRESSION-002
        run = _make_run(anchor_date=MON_JAN_06, placement_days=DAILY)

        # Monday was compiled normally.
        assert _resolve(run, MON_JAN_06) == 0

        # Simulate downtime: skip Tue–Thu entirely.
        # Friday must still be correct.
        assert _resolve(run, FRI_JAN_10) == 4

    # Tier: 2 | Scheduling logic invariant
    def test_scheduler_downtime_full_week(self) -> None:
        """EP-RESTART-002: Scheduler offline full week; next compilation correct."""
        # Validates INV-EPISODE-PROGRESSION-002
        run = _make_run(anchor_date=MON_JAN_06, placement_days=DAILY)

        # Skip week 1 entirely.  Week 2 Monday must be E7.
        assert _resolve(run, MON_JAN_13) == 7


@pytest.mark.contract
class TestMonotonicAdvancement:
    """Validates INV-EPISODE-PROGRESSION-003 — Monotonic ordered advancement."""

    # Tier: 2 | Scheduling logic invariant
    def test_daily_monotonic(self) -> None:
        """EP-MONO-001: Each day's episode index ≥ previous day's."""
        # Validates INV-EPISODE-PROGRESSION-003
        run = _make_run(anchor_date=MON_JAN_06, placement_days=DAILY)
        indices = [_resolve(run, MON_JAN_06 + timedelta(days=d)) for d in range(14)]
        for i in range(1, len(indices)):
            assert indices[i] >= indices[i - 1], (
                f"Day {i}: episode {indices[i]} < previous {indices[i - 1]}"
            )

    # Tier: 2 | Scheduling logic invariant
    def test_non_zero_anchor_index(self) -> None:
        """EP-MONO-002: anchor_episode_index=10 → anchor date selects E10."""
        # Validates INV-EPISODE-PROGRESSION-003
        run = _make_run(anchor_date=MON_JAN_06, anchor_episode_index=10)
        assert _resolve(run, MON_JAN_06) == 10
        assert _resolve(run, TUE_JAN_07) == 11

    # Tier: 2 | Scheduling logic invariant
    def test_out_of_order_resolution(self) -> None:
        """EP-MONO-003: Resolving Friday before Tuesday produces same results."""
        # Validates INV-EPISODE-PROGRESSION-001, INV-EPISODE-PROGRESSION-003
        run = _make_run(anchor_date=MON_JAN_06, placement_days=DAILY)

        # Resolve out of calendar order.
        fri_result = _resolve(run, FRI_JAN_10)
        tue_result = _resolve(run, TUE_JAN_07)

        # Now resolve in calendar order and compare.
        assert tue_result == _resolve(run, TUE_JAN_07)
        assert fri_result == _resolve(run, FRI_JAN_10)

        # Tuesday must be before Friday.
        assert tue_result < fri_result


@pytest.mark.contract
class TestPlacementIsolation:
    """Validates INV-EPISODE-PROGRESSION-004 — Placement isolation."""

    # Tier: 2 | Scheduling logic invariant
    def test_same_show_different_times_independent(self) -> None:
        """EP-ISOLATE-001: Bonanza at 10:00 and 23:00 are separate runs."""
        # Validates INV-EPISODE-PROGRESSION-004
        run_10am = _make_run(
            placement_time=time(10, 0),
            content_source_id="bonanza",
            anchor_episode_index=0,
        )
        run_11pm = _make_run(
            placement_time=time(23, 0),
            content_source_id="bonanza",
            anchor_episode_index=5,
        )
        # Different anchor_episode_index → different result on same day.
        assert _resolve(run_10am, WED_JAN_08) != _resolve(run_11pm, WED_JAN_08)

    # Tier: 2 | Scheduling logic invariant
    def test_same_show_different_days_independent(self) -> None:
        """EP-ISOLATE-002: Weekday and weekend runs are separate."""
        # Validates INV-EPISODE-PROGRESSION-004
        weekday_run = _make_run(placement_days=WEEKDAY)
        weekend_run = _make_run(placement_days=WEEKEND, anchor_date=SAT_JAN_11)

        # Each run advances independently on its own days.
        assert _resolve(weekday_run, MON_JAN_06) == 0  # Weekday E0
        assert _resolve(weekend_run, SAT_JAN_11) == 0  # Weekend E0

        # Friday for weekday run: 5th weekday (Mon–Fri) → E4.
        assert _resolve(weekday_run, FRI_JAN_10) == 4
        # Sunday for weekend run: 2nd weekend day → E1.
        assert _resolve(weekend_run, SUN_JAN_12) == 1

    # Tier: 2 | Scheduling logic invariant
    def test_three_strips_no_interference(self) -> None:
        """EP-ISOLATE-003: Three concurrent runs progress independently."""
        # Validates INV-EPISODE-PROGRESSION-004
        run_a = _make_run(content_source_id="show-a", anchor_episode_index=0)
        run_b = _make_run(content_source_id="show-b", anchor_episode_index=10)
        run_c = _make_run(content_source_id="show-c", anchor_episode_index=50)

        target = WED_JAN_08  # 2 occurrences from anchor (Mon)

        assert _resolve(run_a, target) == 2    # 0 + 2
        assert _resolve(run_b, target) == 12   # 10 + 2
        assert _resolve(run_c, target) == 52   # 50 + 2

    # Tier: 2 | Scheduling logic invariant
    def test_shared_run_id_same_episode(self) -> None:
        """EP-ISOLATE-004: Two blocks with same run_id resolve same episode."""
        # Validates INV-EPISODE-PROGRESSION-004
        #
        # Shared run identity means shared SerialRunInfo — same anchor, same
        # placement, same policy.  Two blocks referencing the same run record
        # must produce identical results for the same broadcast day.
        shared_run = _make_run(anchor_date=MON_JAN_06, placement_days=DAILY)

        block_a_result = _resolve(shared_run, THU_JAN_09)
        block_b_result = _resolve(shared_run, THU_JAN_09)

        assert block_a_result == block_b_result == 3

    # Tier: 2 | Scheduling logic invariant
    def test_shared_run_same_day_same_episode(self) -> None:
        """EP-SHARED-001 (part 1): Two blocks at different times sharing run_id
        resolve identical episode for same broadcast day."""
        # Validates INV-EPISODE-PROGRESSION-004
        #
        # The 08:00 and 18:00 placements share a run_id, which means they
        # share a single SerialRunInfo.  Episode selection is a function of
        # (run, broadcast_day, catalog_size) — placement_time is identity
        # metadata, not a resolver input.
        shared_run = _make_run(anchor_date=MON_JAN_06, placement_days=DAILY)

        # Resolve for the same broadcast day.
        result_08 = _resolve(shared_run, WED_JAN_08)
        result_18 = _resolve(shared_run, WED_JAN_08)
        assert result_08 == result_18 == 2

    # Tier: 2 | Scheduling logic invariant
    def test_shared_run_time_shifted_same_episode(self) -> None:
        """EP-SHARED-001 (part 2): 06:00 and 18:00 blocks sharing run_id resolve
        identical episode; block start time does not influence selection."""
        # Validates INV-EPISODE-PROGRESSION-004, INV-EPISODE-PROGRESSION-012
        #
        # This is the time-shifted variant.  Even though the placements are at
        # different times of day, the resolver sees the same run record and
        # broadcast day.  The clock position within the day is irrelevant.
        run_06 = _make_run(
            anchor_date=MON_JAN_06,
            placement_days=DAILY,
            placement_time=time(6, 0),
        )
        run_18 = _make_run(
            anchor_date=MON_JAN_06,
            placement_days=DAILY,
            placement_time=time(18, 0),
        )

        # placement_time differs but does not participate in episode selection.
        for target in [MON_JAN_06, TUE_JAN_07, FRI_JAN_10, MON_JAN_13]:
            assert _resolve(run_06, target) == _resolve(run_18, target), (
                f"Time-shifted runs diverged on {target}"
            )


@pytest.mark.contract
class TestDayPatternFidelity:
    """Validates INV-EPISODE-PROGRESSION-005 — Day-pattern fidelity."""

    # Tier: 2 | Scheduling logic invariant
    def test_weekly_progression(self) -> None:
        """EP-DAYPATTERN-001: Weekly placement advances once per week."""
        # Validates INV-EPISODE-PROGRESSION-005
        run = _make_run(anchor_date=MON_JAN_06, placement_days=MONDAY)

        assert _resolve(run, MON_JAN_06) == 0
        assert _resolve(run, MON_JAN_13) == 1
        assert _resolve(run, MON_JAN_20) == 2

    # Tier: 2 | Scheduling logic invariant
    def test_weekday_only_skips_weekends(self) -> None:
        """EP-DAYPATTERN-002: Weekday placement: Fri→E4, next Mon→E5."""
        # Validates INV-EPISODE-PROGRESSION-005
        run = _make_run(anchor_date=MON_JAN_06, placement_days=WEEKDAY)

        assert _resolve(run, MON_JAN_06) == 0  # Mon
        assert _resolve(run, FRI_JAN_10) == 4   # Fri (5th weekday)
        # Sat and Sun are not occurrences.  Next Mon must be E5, not E7.
        assert _resolve(run, MON_JAN_13) == 5

    # Tier: 2 | Scheduling logic invariant
    def test_mwf_progression(self) -> None:
        """EP-DAYPATTERN-003: Mon/Wed/Fri placement skips Tue/Thu/Sat/Sun."""
        # Validates INV-EPISODE-PROGRESSION-005
        mwf = MONDAY | WEDNESDAY | FRIDAY
        run = _make_run(anchor_date=MON_JAN_06, placement_days=mwf)

        assert _resolve(run, MON_JAN_06) == 0  # Mon
        assert _resolve(run, WED_JAN_08) == 1  # Wed
        assert _resolve(run, FRI_JAN_10) == 2  # Fri
        # Next week: Mon → E3, Wed → E4, Fri → E5
        assert _resolve(run, MON_JAN_13) == 3
        assert _resolve(run, WED_JAN_15) == 4
        assert _resolve(run, FRI_JAN_17) == 5


@pytest.mark.contract
class TestExhaustionPolicies:
    """Validates INV-EPISODE-PROGRESSION-006 — Exhaustion policy correctness."""

    # Tier: 2 | Scheduling logic invariant
    def test_wrap_cycles_back(self) -> None:
        """EP-EXHAUST-001: `wrap` returns to episode 0 after catalog exhaustion."""
        # Validates INV-EPISODE-PROGRESSION-006
        catalog_size = 5
        run = _make_run(
            anchor_date=MON_JAN_06,
            placement_days=DAILY,
            wrap_policy="wrap",
        )

        # Episodes 0–4 for days 0–4.
        for d in range(5):
            assert _resolve(run, MON_JAN_06 + timedelta(days=d), catalog_size) == d

        # Day 5 wraps back to 0.
        assert _resolve(run, MON_JAN_06 + timedelta(days=5), catalog_size) == 0
        # Day 6 → 1.
        assert _resolve(run, MON_JAN_06 + timedelta(days=6), catalog_size) == 1

    # Tier: 2 | Scheduling logic invariant
    def test_hold_last_repeats_final(self) -> None:
        """EP-EXHAUST-002: `hold_last` repeats final episode indefinitely."""
        # Validates INV-EPISODE-PROGRESSION-006
        catalog_size = 5
        run = _make_run(
            anchor_date=MON_JAN_06,
            placement_days=DAILY,
            wrap_policy="hold_last",
        )

        # Last valid episode is index 4.
        assert _resolve(run, MON_JAN_06 + timedelta(days=4), catalog_size) == 4
        # Days beyond catalog size: all clamp to 4.
        assert _resolve(run, MON_JAN_06 + timedelta(days=5), catalog_size) == 4
        assert _resolve(run, MON_JAN_06 + timedelta(days=10), catalog_size) == 4
        assert _resolve(run, MON_JAN_06 + timedelta(days=100), catalog_size) == 4

    # Tier: 2 | Scheduling logic invariant
    def test_stop_returns_filler(self) -> None:
        """EP-EXHAUST-003: `stop` returns FILLER after last episode."""
        # Validates INV-EPISODE-PROGRESSION-006
        catalog_size = 5
        run = _make_run(
            anchor_date=MON_JAN_06,
            placement_days=DAILY,
            wrap_policy="stop",
        )

        # Last valid episode is index 4.
        assert _resolve(run, MON_JAN_06 + timedelta(days=4), catalog_size) == 4
        # Day 5 onward: FILLER.
        assert _resolve(run, MON_JAN_06 + timedelta(days=5), catalog_size) is FILLER
        assert _resolve(run, MON_JAN_06 + timedelta(days=100), catalog_size) is FILLER

    # Tier: 2 | Scheduling logic invariant
    def test_all_policies_agree_before_exhaustion(self) -> None:
        """EP-EXHAUST-004: Last valid episode is the same under all three policies."""
        # Validates INV-EPISODE-PROGRESSION-006
        catalog_size = 5
        last_valid_day = MON_JAN_06 + timedelta(days=4)  # Episode index 4

        for policy in ("wrap", "hold_last", "stop"):
            run = _make_run(
                anchor_date=MON_JAN_06,
                placement_days=DAILY,
                wrap_policy=policy,
            )
            assert _resolve(run, last_valid_day, catalog_size) == 4, (
                f"Policy {policy!r} disagrees on last valid episode"
            )


@pytest.mark.contract
class TestSeasonTransparency:
    """Validates derived property: Season boundary transparency.

    Season transparency is a consequence of the flat-index episode model
    (INV-EPISODE-PROGRESSION-003).  There is no season-aware code path.
    """

    # Tier: 2 | Scheduling logic invariant
    def test_season_boundary_rollover(self) -> None:
        """EP-SEASON-001: Episode index crosses S01→S02 without special handling.

        Simulates a show with S01 (22 episodes) + S02 (24 episodes) = 46 total.
        Day 22 (index 21) = last S01 episode.  Day 23 (index 22) = first S02
        episode.  No gap, no reset, no special handling.
        """
        # Validates INV-EPISODE-PROGRESSION-003 (derived: season transparency)
        catalog_size = 46  # S01=22 + S02=24
        run = _make_run(
            anchor_date=MON_JAN_06,
            placement_days=DAILY,
            wrap_policy="stop",
        )

        # S01 last episode: day index 21 → episode 21.
        assert _resolve(run, MON_JAN_06 + timedelta(days=21), catalog_size) == 21
        # S02 first episode: day index 22 → episode 22.
        assert _resolve(run, MON_JAN_06 + timedelta(days=22), catalog_size) == 22
        # No gap: episode 22 follows episode 21.
        assert (
            _resolve(run, MON_JAN_06 + timedelta(days=22), catalog_size)
            == _resolve(run, MON_JAN_06 + timedelta(days=21), catalog_size) + 1
        )


@pytest.mark.contract
class TestEPGStability:
    """Validates derived property: EPG identity stability.

    EPG stability is a consequence of determinism (INV-EPISODE-PROGRESSION-001)
    and calendar-only computation (INV-EPISODE-PROGRESSION-012).
    """

    # Tier: 2 | Scheduling logic invariant
    def test_epg_recomputation_stable(self) -> None:
        """EP-EPG-001: Recompiling same day produces same episode identity.

        Simulates two independent compilation passes for the same channel and
        broadcast day.  Both must produce the same episode index.
        """
        # Validates INV-EPISODE-PROGRESSION-001, INV-EPISODE-PROGRESSION-012
        #   (derived: EPG stability)
        run = _make_run(anchor_date=MON_JAN_06, placement_days=DAILY)

        # First compilation pass.
        first_pass = _resolve(run, FRI_JAN_10)
        # Second compilation pass — identical inputs.
        second_pass = _resolve(run, FRI_JAN_10)

        assert first_pass == second_pass


@pytest.mark.contract
class TestMultiExecutionSequencing:
    """Validates INV-EPISODE-PROGRESSION-009 — Multi-execution sequencing."""

    # Tier: 2 | Scheduling logic invariant
    def test_multi_execution_consecutive_episodes(self) -> None:
        """EP-MULTI-001: Block with 3 executions selects E_n, E_n+1, E_n+2.

        When a schedule block has slots=3 and grid_blocks=1, it produces
        3 program executions.  The base episode is resolved from the calendar;
        subsequent executions are base+1, base+2.
        """
        # Validates INV-EPISODE-PROGRESSION-009
        run = _make_run(anchor_date=MON_JAN_06, placement_days=DAILY)
        num_executions = 3

        # Day 3 (Thursday): base episode = 3.
        base_index = _resolve(run, THU_JAN_09)
        assert base_index == 3

        # Multi-execution: consecutive offsets from base raw index.
        occ = count_occurrences(run.anchor_date, THU_JAN_09, run.placement_days)
        raw_base = run.anchor_episode_index + occ

        execution_episodes = [
            apply_wrap_policy(raw_base + offset, EPISODE_COUNT, run.wrap_policy)
            for offset in range(num_executions)
        ]

        assert execution_episodes == [3, 4, 5]

    # Tier: 2 | Scheduling logic invariant
    def test_multi_execution_does_not_affect_next_day(self) -> None:
        """EP-MULTI-002: Next day base episode is from calendar, not offset.

        Day 1 has 3 executions (E0, E1, E2).  Day 2's base episode must be E1
        (1 occurrence from anchor), not E3 (continuation from day 1's last
        execution offset).
        """
        # Validates INV-EPISODE-PROGRESSION-009
        run = _make_run(anchor_date=MON_JAN_06, placement_days=DAILY)

        # Day 1 (Mon): 3 executions → E0, E1, E2.
        day1_base = _resolve(run, MON_JAN_06)
        assert day1_base == 0

        # Day 2 (Tue): base episode from calendar = E1 (not E3).
        day2_base = _resolve(run, TUE_JAN_07)
        assert day2_base == 1


@pytest.mark.contract
class TestScheduleEditContinuity:
    """Validates INV-EPISODE-PROGRESSION-010 — Schedule edit continuity."""

    # Tier: 2 | Scheduling logic invariant
    def test_schedule_edit_preserves_progression(self) -> None:
        """EP-EDIT-001: Changing start time with same run_id continues progression.

        An operator moves a strip from 10:00 to 10:30.  The run_id is unchanged,
        so the same SerialRunInfo is used.  Episode progression continues from
        the existing anchor — no reset.
        """
        # Validates INV-EPISODE-PROGRESSION-010
        run_before_edit = _make_run(
            anchor_date=MON_JAN_06,
            placement_days=DAILY,
            placement_time=time(10, 0),
        )

        # Compile 5 days before the edit.
        episodes_before = [
            _resolve(run_before_edit, MON_JAN_06 + timedelta(days=d))
            for d in range(5)
        ]
        assert episodes_before == [0, 1, 2, 3, 4]

        # Edit: time changes, but run identity (and therefore run record)
        # is preserved.  Same anchor, same placement_days, same policy.
        run_after_edit = _make_run(
            anchor_date=MON_JAN_06,
            placement_days=DAILY,
            placement_time=time(10, 30),
        )

        # Day 6 (Saturday): must be E5, not E0.
        assert _resolve(run_after_edit, SAT_JAN_11) == 5

    # Tier: 2 | Scheduling logic invariant
    def test_run_id_change_resets_progression(self) -> None:
        """EP-EDIT-002: Changing run_id creates new run with fresh anchor.

        When the operator changes the run_id, a new SerialRunInfo is created
        with a fresh anchor.  Progression restarts.
        """
        # Validates INV-EPISODE-PROGRESSION-010
        old_run = _make_run(
            anchor_date=MON_JAN_06,
            placement_days=DAILY,
            content_source_id="show-old",
            anchor_episode_index=0,
        )

        # Old run compiled through Friday → E4.
        assert _resolve(old_run, FRI_JAN_10) == 4

        # New run_id means new run, fresh anchor at Saturday.
        new_run = _make_run(
            anchor_date=SAT_JAN_11,
            placement_days=DAILY,
            content_source_id="show-new",
            anchor_episode_index=0,
        )

        # Saturday is anchor → E0 (fresh start).
        assert _resolve(new_run, SAT_JAN_11) == 0
        assert _resolve(new_run, SUN_JAN_12) == 1


@pytest.mark.contract
class TestAnchorValidation:
    """Validates INV-EPISODE-PROGRESSION-011 — Anchor validity."""

    # Tier: 2 | Scheduling logic invariant
    def test_anchor_on_non_matching_day_rejected(self) -> None:
        """EP-ANCHOR-001: Anchor on Saturday for weekday mask is rejected.

        Saturday (weekday=5) has bit 5 set.  WEEKDAY mask is 0b0011111 (bits
        0–4 only).  The anchor must be rejected.
        """
        # Validates INV-EPISODE-PROGRESSION-011
        with pytest.raises(ValueError, match="(?i)anchor.*does not match"):
            validate_anchor(SAT_JAN_11, WEEKDAY)

        # Positive case: Monday on WEEKDAY mask is valid.
        validate_anchor(MON_JAN_06, WEEKDAY)  # Must not raise.


@pytest.mark.contract
class TestCalendarMath:
    """Validates INV-EPISODE-PROGRESSION-012 — Calendar-only computation."""

    # Tier: 2 | Scheduling logic invariant
    def test_occurrence_counter_anchor_equals_target(self) -> None:
        """EP-CALENDAR-001: [anchor, anchor) returns 0."""
        # Validates INV-EPISODE-PROGRESSION-012
        assert count_occurrences(MON_JAN_06, MON_JAN_06, DAILY) == 0

    # Tier: 2 | Scheduling logic invariant
    def test_occurrence_counter_single_day(self) -> None:
        """EP-CALENDAR-002: [Mon, Tue) with daily mask returns 1."""
        # Validates INV-EPISODE-PROGRESSION-012
        assert count_occurrences(MON_JAN_06, TUE_JAN_07, DAILY) == 1

    # Tier: 2 | Scheduling logic invariant
    def test_occurrence_counter_full_week(self) -> None:
        """EP-CALENDAR-003: 7 days with daily mask returns 7."""
        # Validates INV-EPISODE-PROGRESSION-012
        assert count_occurrences(MON_JAN_06, MON_JAN_13, DAILY) == 7

    # Tier: 2 | Scheduling logic invariant
    def test_occurrence_counter_large_range(self) -> None:
        """EP-CALENDAR-004: 10-year range computed in bounded time."""
        # Validates INV-EPISODE-PROGRESSION-012
        anchor = date(2020, 1, 6)  # Monday
        target = date(2030, 1, 7)  # Monday, ~10 years later

        start = _time.monotonic()
        result = count_occurrences(anchor, target, DAILY)
        elapsed = _time.monotonic() - start

        # 10 years ≈ 3653 days.
        expected = (target - anchor).days
        assert result == expected

        # Must complete in bounded time — arithmetic, not iteration over days.
        # Allow generous 50ms to avoid flakiness; arithmetic should be <1ms.
        assert elapsed < 0.050, f"Took {elapsed:.4f}s — not O(1)"
