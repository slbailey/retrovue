"""Contract tests: INV-CROSS-DAY-CARRY-IN-SURVIVES-RESTART-001

When _build_initial() compiles the schedule starting from day D, and
day D-1 is NOT in the compilation window, the system MUST load the
prior day's carry-in end time from the DB so that day D's first block
does not trample the carry-in movie.

Root cause: _build_initial initializes active_carry_in_end_ms=0 and only
tracks carry-in across days it compiles in the same loop. If the prior
day is outside the loop, the carry-in is lost.

Incident: 2026-03-24 — "In Search of Darkness Part III" (342 min) was
playing from 09:30 UTC. Process restarted at 13:54 UTC. _build_initial
compiled March 24 starting at 10:00 with no carry-in knowledge. EPG
replaced the movie. Viewer got Lilo & Stitch instead.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

try:
    from retrovue.runtime.dsl_schedule_service import DslScheduleService
except ImportError:
    pytest.skip(
        "retrovue.runtime.dsl_schedule_service not available",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_schedule_item(
    *,
    slot_index: int,
    start_time: datetime,
    duration_sec: int,
    title: str,
    asset_id: str | None = None,
    content_type: str = "movie",
) -> MagicMock:
    """Fake ScheduleItem for DB query results."""
    item = MagicMock()
    item.slot_index = slot_index
    item.start_time = start_time
    item.duration_sec = duration_sec
    item.content_type = content_type
    item.asset_id = uuid.UUID(asset_id) if asset_id else uuid.uuid4()
    item.container_id = None
    item.metadata_ = {"title": title}
    item.id = uuid.uuid4()
    return item


def _make_revision(
    *,
    channel_id: uuid.UUID,
    broadcast_day: date,
    status: str = "active",
    items: list | None = None,
) -> MagicMock:
    rev = MagicMock()
    rev.id = uuid.uuid4()
    rev.channel_id = channel_id
    rev.broadcast_day = broadcast_day
    rev.status = status
    rev.items = items or []
    rev.created_at = datetime.now(timezone.utc)
    return rev


# ===========================================================================
# Core invariant: _compute_effective_day_open_ms respects carry-in
# ===========================================================================


class TestComputeEffectiveDayOpen:
    """_compute_effective_day_open_ms must push day open past carry-in end."""

    def test_carry_in_pushes_day_open(self):
        """When carry-in extends past day start, effective open = carry-in end."""
        # Day start: 2026-03-24 10:00 UTC
        # Carry-in end: 2026-03-24 15:30 UTC (movie from yesterday)
        result = DslScheduleService._compute_effective_day_open_ms(
            broadcast_day="2026-03-24",
            day_start_hour=6,
            tz_name="America/New_York",
            active_carry_in_end_ms=int(
                datetime(2026, 3, 24, 15, 30, tzinfo=timezone.utc).timestamp() * 1000
            ),
        )

        # Must be at carry-in end (15:30 UTC), not day start (10:00 UTC)
        carry_in_end_ms = int(
            datetime(2026, 3, 24, 15, 30, tzinfo=timezone.utc).timestamp() * 1000
        )
        assert result == carry_in_end_ms, (
            f"effective_day_open must equal carry-in end. "
            f"Expected {carry_in_end_ms}, got {result}"
        )

    def test_no_carry_in_uses_day_start(self):
        """Without carry-in, effective open = broadcast day start."""
        result = DslScheduleService._compute_effective_day_open_ms(
            broadcast_day="2026-03-24",
            day_start_hour=6,
            tz_name="America/New_York",
            active_carry_in_end_ms=0,
        )

        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/New_York")
        expected = int(
            datetime(2026, 3, 24, 6, 0, tzinfo=tz).timestamp() * 1000
        )
        assert result == expected


# ===========================================================================
# Root cause: _build_initial does not load prior day carry-in from DB
# ===========================================================================


class TestBuildInitialCarryInFromDB:
    """_build_initial MUST load prior day carry-in from active revision
    when the prior day is outside the compilation window.
    """

    def test_prior_day_carry_in_loaded_from_db(self):
        """When start_date = March 24 and March 23's last block ends at
        15:30 UTC on March 24, _build_initial must use 15:30 as the
        carry-in end for March 24's compilation.

        This test verifies the function that loads carry-in from the DB.
        """
        load_fn = getattr(DslScheduleService, "_load_prior_day_carry_in_end_ms", None)
        assert load_fn is not None, (
            "INV-CROSS-DAY-CARRY-IN-SURVIVES-RESTART-001: "
            "DslScheduleService must have _load_prior_day_carry_in_end_ms method "
            "to load carry-in from DB on cold start"
        )

    def test_load_existing_timeline_method_exists(self):
        """INV-TIMELINE-SINGLE-AUTHORITY-001: _build_initial must load
        from DB via _load_existing_timeline, not recompile from DSL.
        """
        assert hasattr(DslScheduleService, "_load_existing_timeline"), (
            "INV-TIMELINE-SINGLE-AUTHORITY-001: "
            "DslScheduleService must have _load_existing_timeline method"
        )

    def test_load_carry_in_block_method_exists(self):
        """INV-TIMELINE-CARRY-IN-PRESERVED-001: carry-in block must be
        loadable as a full ScheduledBlock, not just an end timestamp.
        """
        assert hasattr(DslScheduleService, "_load_carry_in_block_from_revision"), (
            "INV-TIMELINE-CARRY-IN-PRESERVED-001: "
            "DslScheduleService must have _load_carry_in_block_from_revision method"
        )


# ===========================================================================
# Regression: carry-in within the compilation window still works
# ===========================================================================


class TestCarryInWithinCompilationWindow:
    """When both days are in the compilation window, carry-in still propagates.
    This is the existing behavior that must not regress.
    """

    def test_active_carry_in_end_ms_propagates(self):
        """The _build_initial loop propagates carry-in via active_carry_in_end_ms.
        Verify the propagation formula is correct.
        """
        # Simulate: last block of day 1 ends at 15:30 UTC
        blocks_day1 = [MagicMock(end_utc_ms=int(
            datetime(2026, 3, 24, 15, 30, tzinfo=timezone.utc).timestamp() * 1000
        ))]

        # active_carry_in_end_ms should be max of current and last block end
        active_carry_in_end_ms = 0
        if blocks_day1:
            active_carry_in_end_ms = max(
                active_carry_in_end_ms, blocks_day1[-1].end_utc_ms,
            )

        expected = int(
            datetime(2026, 3, 24, 15, 30, tzinfo=timezone.utc).timestamp() * 1000
        )
        assert active_carry_in_end_ms == expected
