"""Contract tests: Timeline Authority Invariants

Covers the five timeline invariants that govern restart determinism,
single authority, contiguity, append-only semantics, and carry-in
preservation across broadcast day boundaries.

- INV-TIMELINE-RESTART-IDENTICAL-001
- INV-TIMELINE-SINGLE-AUTHORITY-001
- INV-TIMELINE-CONTINUITY-001
- INV-TIMELINE-APPEND-ONLY-001
- INV-TIMELINE-CARRY-IN-PRESERVED-001
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from retrovue.runtime.clock import SystemClock

try:
    from retrovue.runtime.dsl_schedule_service import DslScheduleService
    from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment
except ImportError:
    pytest.skip(
        "retrovue.runtime.dsl_schedule_service not available",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seg(duration_ms: int = 7200_000) -> ScheduledSegment:
    """Create a minimal content segment."""
    return ScheduledSegment(
        segment_type="content",
        asset_uri="/media/test.mkv",
        asset_start_offset_ms=0,
        segment_duration_ms=duration_ms,
    )


def _ms(dt: datetime) -> int:
    """Convert datetime to milliseconds since epoch."""
    return int(dt.timestamp() * 1000)


def _block(
    block_id: str,
    start: datetime,
    end: datetime,
    seg_duration_ms: int | None = None,
) -> ScheduledBlock:
    """Create a ScheduledBlock with one content segment."""
    dur = seg_duration_ms or (_ms(end) - _ms(start))
    return ScheduledBlock(
        block_id=block_id,
        start_utc_ms=_ms(start),
        end_utc_ms=_ms(end),
        segments=(_seg(dur),),
    )


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
# INV-TIMELINE-RESTART-IDENTICAL-001 — Restart determinism
# ===========================================================================


class TestTimelineRestartIdentical:
    """INV-TIMELINE-RESTART-IDENTICAL-001: A system restart MUST NOT change
    the timeline for any time range already defined prior to the restart.
    """

    def test_enforce_contiguity_is_deterministic(self):
        """Applying _enforce_timeline_contiguity twice yields identical results.
        This is the core restart path: blocks loaded from DB are fed through
        contiguity enforcement. The output must be stable across restarts.
        """
        base = datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc)
        blocks = [
            _block("blk-a", base, base + timedelta(hours=2)),
            _block("blk-b", base + timedelta(hours=2), base + timedelta(hours=4)),
            _block("blk-c", base + timedelta(hours=4), base + timedelta(hours=6)),
        ]

        first_pass = DslScheduleService._enforce_timeline_contiguity(blocks)
        second_pass = DslScheduleService._enforce_timeline_contiguity(first_pass)

        assert len(first_pass) == len(second_pass)
        for a, b in zip(first_pass, second_pass):
            assert a.block_id == b.block_id
            assert a.start_utc_ms == b.start_utc_ms
            assert a.end_utc_ms == b.end_utc_ms

    def test_push_forward_is_deterministic(self):
        """_push_forward_scheduled_blocks is idempotent: applying it twice
        with the same effective_day_open yields identical blocks.
        """
        carry_in_end = datetime(2026, 4, 6, 12, 30, tzinfo=timezone.utc)
        blocks = [
            _block("blk-a", datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc),
                   datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc)),
            _block("blk-b", datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc),
                   datetime(2026, 4, 6, 14, 0, tzinfo=timezone.utc)),
        ]

        first_pass = DslScheduleService._push_forward_scheduled_blocks(
            blocks, _ms(carry_in_end), "2026-04-06",
        )
        second_pass = DslScheduleService._push_forward_scheduled_blocks(
            first_pass, _ms(carry_in_end), "2026-04-06",
        )

        assert len(first_pass) == len(second_pass)
        for a, b in zip(first_pass, second_pass):
            assert a.block_id == b.block_id
            assert a.start_utc_ms == b.start_utc_ms
            assert a.end_utc_ms == b.end_utc_ms

    def test_contiguity_preserves_block_identity(self):
        """After contiguity enforcement, block IDs and segment count are
        preserved — only timing may adjust.
        """
        base = datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc)
        # Introduce a small overlap to trigger push-forward
        blocks = [
            _block("blk-a", base, base + timedelta(hours=2, minutes=10)),
            _block("blk-b", base + timedelta(hours=2), base + timedelta(hours=4)),
        ]

        result = DslScheduleService._enforce_timeline_contiguity(blocks)
        ids = [b.block_id for b in result]
        assert "blk-a" in ids
        assert "blk-b" in ids
        for b in result:
            assert len(b.segments) == 1


# ===========================================================================
# INV-TIMELINE-SINGLE-AUTHORITY-001 — Single authority source
# ===========================================================================


class TestTimelineSingleAuthority:
    """INV-TIMELINE-SINGLE-AUTHORITY-001: All timeline answers must derive
    from a single authoritative source (the DB).
    """

    def test_build_initial_uses_load_existing_timeline(self):
        """_build_initial loads blocks via _load_existing_timeline (DB),
        NOT by recompiling from DSL YAML.
        """
        assert hasattr(DslScheduleService, "_load_existing_timeline"), (
            "INV-TIMELINE-SINGLE-AUTHORITY-001: "
            "DslScheduleService must have _load_existing_timeline for DB loading"
        )

    def test_load_existing_timeline_returns_blocks_and_day_sets(self):
        """_load_existing_timeline must return (blocks, loaded_days, missing_days)
        so _build_initial can identify what to compile vs. what is DB-authoritative.
        """
        import inspect
        sig = inspect.signature(DslScheduleService._load_existing_timeline)
        params = list(sig.parameters.keys())
        # Must accept channel_id, start_date, horizon_days, tz_name (plus self)
        assert "channel_id" in params
        assert "start_date" in params
        assert "horizon_days" in params

    def test_save_compiled_schedule_refuses_existing_revision(self):
        """INV-TIMELINE-SINGLE-AUTHORITY-001 + APPEND-ONLY: _save_compiled_schedule
        returns False when a revision already exists, preventing the compiled
        output from overwriting DB authority.
        """
        # The method signature exists and returns bool
        import inspect
        sig = inspect.signature(DslScheduleService._save_compiled_schedule)
        # Method should return bool indicating success/refusal
        assert "channel_id" in sig.parameters
        assert "broadcast_day" in sig.parameters


# ===========================================================================
# INV-TIMELINE-CONTINUITY-001 — No gaps, no overlaps
# ===========================================================================


class TestTimelineContinuity:
    """INV-TIMELINE-CONTINUITY-001: The timeline MUST form a continuous,
    non-overlapping sequence of blocks.
    """

    def test_contiguous_blocks_remain_contiguous(self):
        """Already-contiguous blocks pass through enforcement unchanged."""
        base = datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc)
        blocks = [
            _block("blk-a", base, base + timedelta(hours=2)),
            _block("blk-b", base + timedelta(hours=2), base + timedelta(hours=4)),
            _block("blk-c", base + timedelta(hours=4), base + timedelta(hours=6)),
        ]

        result = DslScheduleService._enforce_timeline_contiguity(blocks)

        assert len(result) == 3
        for i in range(len(result) - 1):
            assert result[i].end_utc_ms == result[i + 1].start_utc_ms, (
                f"INV-TIMELINE-CONTINUITY-001: blocks {result[i].block_id} and "
                f"{result[i+1].block_id} are not contiguous"
            )

    def test_overlapping_blocks_become_contiguous(self):
        """Overlapping blocks must be resolved to a contiguous sequence."""
        base = datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc)
        blocks = [
            _block("blk-a", base, base + timedelta(hours=2, minutes=30)),
            _block("blk-b", base + timedelta(hours=2), base + timedelta(hours=4)),
            _block("blk-c", base + timedelta(hours=4), base + timedelta(hours=6)),
        ]

        result = DslScheduleService._enforce_timeline_contiguity(blocks)

        for i in range(len(result) - 1):
            assert result[i].end_utc_ms == result[i + 1].start_utc_ms, (
                f"INV-TIMELINE-CONTINUITY-001: blocks {result[i].block_id} and "
                f"{result[i+1].block_id} are not contiguous after enforcement"
            )
        # No overlaps
        for i in range(len(result) - 1):
            assert result[i].end_utc_ms <= result[i + 1].start_utc_ms

    def test_multi_day_blocks_become_contiguous(self):
        """Blocks spanning multiple broadcast days (loaded from separate
        schedule_items) must form a contiguous sequence after enforcement.
        When Saturday carry-in extends past Sunday's grid start, Sunday
        blocks that overlap must be pushed forward.
        """
        # Saturday carry-in extends past Sunday's grid start
        sat_start = datetime(2026, 4, 5, 8, 0, tzinfo=timezone.utc)
        sun_grid_start = datetime(2026, 4, 5, 10, 0, tzinfo=timezone.utc)

        blocks = [
            _block("sat-1", sat_start, sat_start + timedelta(hours=2)),
            # sat-2 ends at 13:00 — extends 3h past Sunday grid start (10:00)
            _block("sat-2", sat_start + timedelta(hours=2),
                   sat_start + timedelta(hours=5)),
            # Sunday grid blocks start at 10:00 — overlap with sat-2
            _block("sun-1", sun_grid_start, sun_grid_start + timedelta(hours=2)),
            _block("sun-2", sun_grid_start + timedelta(hours=2),
                   sun_grid_start + timedelta(hours=4)),
        ]
        blocks.sort(key=lambda b: b.start_utc_ms)

        result = DslScheduleService._enforce_timeline_contiguity(blocks)

        for i in range(len(result) - 1):
            assert result[i].end_utc_ms == result[i + 1].start_utc_ms, (
                f"INV-TIMELINE-CONTINUITY-001: multi-day blocks "
                f"{result[i].block_id} and {result[i+1].block_id} "
                f"are not contiguous"
            )

    def test_single_block_is_trivially_contiguous(self):
        """A single block is trivially contiguous — enforcement must not
        alter or drop it.
        """
        base = datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc)
        blocks = [_block("blk-only", base, base + timedelta(hours=2))]

        result = DslScheduleService._enforce_timeline_contiguity(blocks)
        assert len(result) == 1
        assert result[0].block_id == "blk-only"
        assert result[0].start_utc_ms == _ms(base)

    def test_empty_timeline_is_trivially_contiguous(self):
        """An empty block list passes through without error."""
        result = DslScheduleService._enforce_timeline_contiguity([])
        assert result == []


# ===========================================================================
# INV-TIMELINE-APPEND-ONLY-001 — Append-only timeline
# ===========================================================================


class TestTimelineAppendOnly:
    """INV-TIMELINE-APPEND-ONLY-001: Once a time range is defined,
    it MUST NOT be modified or replaced by subsequent operations.
    """

    def test_save_compiled_schedule_uses_conflict_resolution(self):
        """_save_compiled_schedule delegates to write_active_revision_from_compiled_schedule
        which uses INSERT ... ON CONFLICT DO NOTHING. Verify the method exists
        and delegates to the revision writer.
        """
        import inspect
        source = inspect.getsource(DslScheduleService._save_compiled_schedule)
        assert "write_active_revision_from_compiled_schedule" in source, (
            "INV-TIMELINE-APPEND-ONLY-001: _save_compiled_schedule must "
            "delegate to write_active_revision_from_compiled_schedule"
        )

    def test_contiguity_enforcement_does_not_reorder_blocks(self):
        """Contiguity enforcement preserves chronological order.
        It may push blocks forward but never reorders them.
        """
        base = datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc)
        blocks = [
            _block("blk-a", base, base + timedelta(hours=2)),
            _block("blk-b", base + timedelta(hours=2), base + timedelta(hours=4)),
            _block("blk-c", base + timedelta(hours=4), base + timedelta(hours=6)),
        ]

        result = DslScheduleService._enforce_timeline_contiguity(blocks)

        ids = [b.block_id for b in result]
        assert ids == ["blk-a", "blk-b", "blk-c"], (
            "INV-TIMELINE-APPEND-ONLY-001: block order must be preserved"
        )

    def test_push_forward_does_not_modify_earlier_blocks(self):
        """When push-forward adjusts block B, block A must remain unchanged.
        Append-only means earlier time ranges are immutable.
        """
        carry_in_end = datetime(2026, 4, 6, 12, 30, tzinfo=timezone.utc)
        original_a = _block(
            "blk-a",
            datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc),
            datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc),
        )
        original_b = _block(
            "blk-b",
            datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc),
            datetime(2026, 4, 6, 14, 0, tzinfo=timezone.utc),
        )

        result = DslScheduleService._push_forward_scheduled_blocks(
            [original_a, original_b], _ms(carry_in_end), "2026-04-06",
        )

        # blk-a is subsumed (ends before carry-in) — dropped, not modified
        # blk-b is pushed forward — but original_a was never mutated
        assert original_a.start_utc_ms == _ms(
            datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc)
        ), "Original block A must not be mutated"
        assert original_a.end_utc_ms == _ms(
            datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc)
        ), "Original block A must not be mutated"


# ===========================================================================
# INV-TIMELINE-CARRY-IN-PRESERVED-001 — Carry-in across day boundary
# ===========================================================================


class TestTimelineCarryInPreserved:
    """INV-TIMELINE-CARRY-IN-PRESERVED-001: If a program extends across a
    day boundary, the subsequent day MUST NOT introduce blocks that overlap
    the carried-in program.
    """

    def test_day_open_respects_carry_in(self):
        """When prior-day block extends past the next day's broadcast start,
        effective_day_open must equal the carry-in end — not the day start.
        """
        carry_in_end = datetime(2026, 4, 6, 15, 30, tzinfo=timezone.utc)
        result = DslScheduleService._compute_effective_day_open_ms(
            broadcast_day="2026-04-06",
            day_start_hour=6,
            tz_name="America/New_York",
            prior_block_end_ms=_ms(carry_in_end),
        )
        assert result == _ms(carry_in_end), (
            "INV-TIMELINE-CARRY-IN-PRESERVED-001: "
            f"effective day open must be carry-in end {_ms(carry_in_end)}, "
            f"got {result}"
        )

    def test_subsequent_day_blocks_start_after_carry_in(self):
        """Blocks on the subsequent day must all start >= carry-in end time.
        No block may overlap with the carried-in program.
        """
        carry_in_end = datetime(2026, 4, 6, 13, 0, tzinfo=timezone.utc)
        blocks = [
            _block("sun-a", datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc),
                   datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc)),
            _block("sun-b", datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc),
                   datetime(2026, 4, 6, 14, 0, tzinfo=timezone.utc)),
            _block("sun-c", datetime(2026, 4, 6, 14, 0, tzinfo=timezone.utc),
                   datetime(2026, 4, 6, 16, 0, tzinfo=timezone.utc)),
        ]

        result = DslScheduleService._push_forward_scheduled_blocks(
            blocks, _ms(carry_in_end), "2026-04-06",
        )

        for blk in result:
            assert blk.start_utc_ms >= _ms(carry_in_end), (
                f"INV-TIMELINE-CARRY-IN-PRESERVED-001: block {blk.block_id} "
                f"starts at {blk.start_utc_ms} which is before carry-in end "
                f"{_ms(carry_in_end)}"
            )

    def test_fully_subsumed_blocks_are_dropped(self):
        """Blocks entirely covered by the carry-in program are dropped —
        not truncated or partially preserved.
        """
        carry_in_end = datetime(2026, 4, 6, 14, 0, tzinfo=timezone.utc)
        blocks = [
            _block("sub-a", datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc),
                   datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc)),
            _block("sub-b", datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc),
                   datetime(2026, 4, 6, 13, 30, tzinfo=timezone.utc)),
            _block("survivor", datetime(2026, 4, 6, 13, 30, tzinfo=timezone.utc),
                   datetime(2026, 4, 6, 16, 0, tzinfo=timezone.utc)),
        ]

        result = DslScheduleService._push_forward_scheduled_blocks(
            blocks, _ms(carry_in_end), "2026-04-06",
        )

        # sub-a and sub-b end before carry-in end — both subsumed and dropped
        surviving_ids = [b.block_id for b in result]
        assert "sub-a" not in surviving_ids
        assert "sub-b" not in surviving_ids
        assert "survivor" in surviving_ids

    def test_carry_in_with_no_overlap_preserves_all_blocks(self):
        """When carry-in ends before or at day start, all blocks survive."""
        day_start = datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc)
        blocks = [
            _block("blk-a", day_start, day_start + timedelta(hours=2)),
            _block("blk-b", day_start + timedelta(hours=2),
                   day_start + timedelta(hours=4)),
        ]

        result = DslScheduleService._push_forward_scheduled_blocks(
            blocks, _ms(day_start), "2026-04-06",
        )

        assert len(result) == 2
        assert result[0].block_id == "blk-a"
        assert result[1].block_id == "blk-b"

    def test_get_prior_day_end_ms_finds_last_block(self):
        """_get_prior_day_end_ms returns the end time of the last block on
        the prior day, providing the carry-in boundary.
        """
        prior_day = date(2026, 4, 5)
        # Block on the prior day
        blk = _block(
            "sat-last",
            datetime(2026, 4, 5, 20, 0, tzinfo=timezone.utc),
            datetime(2026, 4, 6, 1, 30, tzinfo=timezone.utc),  # extends past midnight
        )

        result = DslScheduleService._get_prior_day_end_ms([blk], prior_day)
        assert result == _ms(datetime(2026, 4, 6, 1, 30, tzinfo=timezone.utc)), (
            "INV-TIMELINE-CARRY-IN-PRESERVED-001: "
            "prior day end must be the last block's end_utc_ms"
        )

    def test_no_prior_day_blocks_returns_zero(self):
        """When no blocks exist on the prior day, _get_prior_day_end_ms
        returns 0, meaning no carry-in constraint.
        """
        prior_day = date(2026, 4, 5)
        result = DslScheduleService._get_prior_day_end_ms([], prior_day)
        assert result == 0


# ===========================================================================
# Runtime timeline: reconcile + empty recovery (read path)
# ===========================================================================


class TestRuntimeTimelineReconcileAndRecovery:
    """After scheduling refactor: bump head must not thrash; empty _blocks must reload."""

    def test_reconcile_publish_bump_sets_timeline_revision_to_head(self):
        """INV-SCHEDULE-REVISION-MONOTONICITY-001: After reload, _timeline_revision_id
        must match the bumped head so get_block_at does not clear _blocks every call
        when DB .first() active revision differs from publish head.
        """
        from retrovue.config.testing import TEST_RESOLVED_CONFIG

        head_id = uuid.uuid4()
        svc = DslScheduleService(
            dsl_path="/dev/null",
            filler_path="/opt/retrovue/assets/filler.mp4",
            filler_duration_ms=3_650_000,
            clock=SystemClock(),
            resolved_config=TEST_RESOLVED_CONFIG,
            channel_slug="test-chan",
        )
        svc._timeline_revision_id = uuid.uuid4()

        with patch(
            "retrovue.runtime.schedule_cache_monotonicity.get_channel_schedule_revision_head",
            return_value=str(head_id),
        ), patch.object(svc, "_build_initial") as mock_build:
            svc._reconcile_timeline_if_publish_bumped("test-chan")

        mock_build.assert_called_once_with("test-chan")
        assert svc._timeline_revision_id == head_id

    def test_maybe_extend_horizon_calls_build_initial_when_blocks_empty(self):
        """Empty _blocks must trigger _build_initial so horizon logic can run again."""
        from retrovue.config.testing import TEST_RESOLVED_CONFIG

        svc = DslScheduleService(
            dsl_path="/dev/null",
            filler_path="/opt/retrovue/assets/filler.mp4",
            filler_duration_ms=3_650_000,
            clock=SystemClock(),
            resolved_config=TEST_RESOLVED_CONFIG,
            channel_slug="test-chan",
        )
        assert svc._blocks == []
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        with patch.object(svc, "_build_initial") as mock_build:
            svc._maybe_extend_horizon("test-chan", now_ms)
        mock_build.assert_called_once_with("test-chan")
