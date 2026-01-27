"""
Phase 2 — Mock SchedulePlan Contract tests.

Unit tests only: no clock math, no tune-in, no HTTP.
Asserts plan exists for any day, two items per grid (samplecontent, filler), duration-free.
"""

from __future__ import annotations

from datetime import date

import pytest

from retrovue.runtime.mock_schedule import (
    ITEM_A,
    ITEM_B,
    MockSchedulePlan,
    ScheduleDay,
    ScheduleItem,
    get_mock_channel_plan,
)


def test_phase2_plan_exists_for_any_given_day():
    """Phase 2: Plan exists for any given day."""
    plan = get_mock_channel_plan()
    for day in [
        date(2025, 1, 1),
        date(2025, 6, 15),
        date(2026, 12, 31),
    ]:
        schedule_day = plan.get_plan_for_day(day)
        assert schedule_day is not None
        assert schedule_day.plan_id == plan.name
        assert schedule_day.day == day


def test_phase2_each_grid_two_items_in_order():
    """Phase 2: Each grid has exactly two items in order (samplecontent, filler)."""
    plan = get_mock_channel_plan()
    items = plan.items_per_grid()
    assert len(items) == 2
    assert items[0].id == ITEM_A
    assert items[1].id == ITEM_B
    assert items[0].id == "samplecontent"
    assert items[1].id == "filler"

    # Same via ScheduleDay
    day = plan.get_plan_for_day(date(2025, 1, 1))
    day_items = day.items_per_grid()
    assert len(day_items) == 2
    assert day_items[0].id == "samplecontent"
    assert day_items[1].id == "filler"


def test_phase2_plan_is_duration_free():
    """Phase 2: Plan is duration-free: no duration or timing fields."""
    # ScheduleItem: only identity
    item = ScheduleItem(id="samplecontent")
    assert hasattr(item, "id")
    assert not hasattr(item, "duration")
    assert not hasattr(item, "duration_ms")
    assert not hasattr(item, "start_time")
    assert not hasattr(item, "end_time")
    assert not hasattr(item, "offset")

    # ScheduleDay: no duration/timing
    plan = get_mock_channel_plan()
    day = plan.get_plan_for_day(date(2025, 1, 1))
    assert hasattr(day, "plan_id") and hasattr(day, "day")
    assert not hasattr(day, "duration")
    assert not hasattr(day, "grid_duration")
    assert not hasattr(day, "start_offset")

    # MockSchedulePlan: no duration/timing
    assert not hasattr(plan, "duration")
    assert not hasattr(plan, "grid_duration")
    assert not hasattr(plan, "sample_duration")


def test_phase2_items_are_identical_for_every_grid():
    """Every grid has the same two items; no per-grid timing."""
    plan = get_mock_channel_plan()
    day1 = plan.get_plan_for_day(date(2025, 1, 1))
    day2 = plan.get_plan_for_day(date(2025, 12, 31))
    assert day1.items_per_grid()[0].id == day2.items_per_grid()[0].id
    assert day1.items_per_grid()[1].id == day2.items_per_grid()[1].id
