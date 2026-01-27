"""
Phase 2 — Mock SchedulePlan: duration-free, static structure for the mock channel.

Describes intent only: what runs in each grid (item identity and order).
No clock math, no offsets, no durations, no playout.
Phase 3 adds a separate duration config to resolve which item is active.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

# Item identities for the mock channel (order: A then B per grid)
ScheduleItemId = Literal["samplecontent", "filler"]


@dataclass(frozen=True)
class ScheduleItem:
    """A single item in the plan: identity only. No duration or timing."""

    id: ScheduleItemId


# Canonical order per grid: Item A, then Item B
ITEM_A: ScheduleItemId = "samplecontent"
ITEM_B: ScheduleItemId = "filler"


@dataclass(frozen=True)
class ScheduleDay:
    """A day's plan view: same structure every day. No duration or timing fields."""

    plan_id: str
    day: date

    def items_per_grid(self) -> list[ScheduleItem]:
        """Exactly two items per grid, in order: A (samplecontent), B (filler)."""
        return [ScheduleItem(ITEM_A), ScheduleItem(ITEM_B)]


@dataclass(frozen=True)
class MockSchedulePlan:
    """
    Mock channel schedule plan: static, duration-free.
    For every grid segment: Item A (samplecontent), Item B (filler). Order only.
    """

    channel_id: str
    name: str

    def get_plan_for_day(self, day: date) -> ScheduleDay:
        """Return plan for any given day. Structure is identical every day."""
        return ScheduleDay(plan_id=self.name, day=day)

    def items_per_grid(self) -> list[ScheduleItem]:
        """Exactly two items per grid, in order: samplecontent, filler."""
        return [ScheduleItem(ITEM_A), ScheduleItem(ITEM_B)]


def get_mock_channel_plan(channel_id: str = "mock", name: str = "phase2-mock") -> MockSchedulePlan:
    """Return the singleton mock plan for the Phase 2 mock channel."""
    return MockSchedulePlan(channel_id=channel_id, name=name)
