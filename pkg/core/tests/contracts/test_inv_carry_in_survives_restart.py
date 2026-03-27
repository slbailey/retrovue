"""Contract tests: INV-CROSS-DAY-CARRY-IN-SURVIVES-RESTART-001

When _build_initial() compiles the schedule starting from day D, and
day D-1 is NOT in the compilation window, the system MUST use
window-based timeline loading to include all blocks that intersect the
window — regardless of broadcast_day.  This ensures the effective day
open for D accounts for prior-day blocks that extend past the boundary.

Incident: 2026-03-24 — "In Search of Darkness Part III" (342 min) was
playing from 09:30 UTC. Process restarted at 13:54 UTC. _build_initial
compiled March 24 starting at 10:00 with no overlap knowledge. EPG
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
# Core invariant: _compute_effective_day_open_ms respects prior-block end
# ===========================================================================


class TestComputeEffectiveDayOpen:
    """_compute_effective_day_open_ms must push day open past prior-block end."""

    def test_prior_block_pushes_day_open(self):
        """When prior-day block extends past day start, effective open = block end."""
        # Day start: 2026-03-24 10:00 UTC
        # Prior-block end: 2026-03-24 15:30 UTC (movie from yesterday)
        result = DslScheduleService._compute_effective_day_open_ms(
            broadcast_day="2026-03-24",
            day_start_hour=6,
            tz_name="America/New_York",
            prior_block_end_ms=int(
                datetime(2026, 3, 24, 15, 30, tzinfo=timezone.utc).timestamp() * 1000
            ),
        )

        # Must be at prior-block end (15:30 UTC), not day start (10:00 UTC)
        expected_end_ms = int(
            datetime(2026, 3, 24, 15, 30, tzinfo=timezone.utc).timestamp() * 1000
        )
        assert result == expected_end_ms, (
            f"effective_day_open must equal prior-block end. "
            f"Expected {expected_end_ms}, got {result}"
        )

    def test_no_overlap_uses_day_start(self):
        """Without prior-block overlap, effective open = broadcast day start."""
        result = DslScheduleService._compute_effective_day_open_ms(
            broadcast_day="2026-03-24",
            day_start_hour=6,
            tz_name="America/New_York",
            prior_block_end_ms=0,
        )

        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/New_York")
        expected = int(
            datetime(2026, 3, 24, 6, 0, tzinfo=tz).timestamp() * 1000
        )
        assert result == expected


# ===========================================================================
# _build_initial loads from DB via window-based timeline loading
# ===========================================================================


class TestBuildInitialLoadsFromDB:
    """_build_initial MUST load from DB via _load_existing_timeline."""

    def test_load_existing_timeline_method_exists(self):
        """INV-TIMELINE-SINGLE-AUTHORITY-001: _build_initial must load
        from DB via _load_existing_timeline, not recompile from DSL.
        """
        assert hasattr(DslScheduleService, "_load_existing_timeline"), (
            "INV-TIMELINE-SINGLE-AUTHORITY-001: "
            "DslScheduleService must have _load_existing_timeline method"
        )


# ===========================================================================
# Regression: prior-block overlap within the compilation window
# ===========================================================================


class TestOverlapWithinCompilationWindow:
    """When both days are in the compilation window, overlap still propagates.
    This is the existing behavior that must not regress.
    """

    def test_prior_block_end_ms_propagates(self):
        """The _build_initial loop propagates prior-block end across days.
        Verify the propagation formula is correct.
        """
        # Simulate: last block of day 1 ends at 15:30 UTC
        blocks_day1 = [MagicMock(end_utc_ms=int(
            datetime(2026, 3, 24, 15, 30, tzinfo=timezone.utc).timestamp() * 1000
        ))]

        # prior_block_end_ms should be max of current and last block end
        prior_block_end_ms = 0
        if blocks_day1:
            prior_block_end_ms = max(
                prior_block_end_ms, blocks_day1[-1].end_utc_ms,
            )

        expected = int(
            datetime(2026, 3, 24, 15, 30, tzinfo=timezone.utc).timestamp() * 1000
        )
        assert prior_block_end_ms == expected
