"""
Contract: docs/contracts/schedule_playlog_authority_and_rebuild.md

INTEGRATION TESTS for scheduling authority invariants.

Exercises the REAL pipeline:
  DSL → compile_schedule → persist → reload → _build_initial → _blocks

Uses:
  - Real DslScheduleService
  - Real database (test DB, auto-patched by conftest)
  - Real CatalogAssetResolver (18k+ episodes in test DB)
  - Real ProgressionRun (auto-created on first compile)
  - Real DSL fixture: tests/fixtures/channels/test_integration.yaml

Invariants under test:
  INV-COMPILE-NO-FUTURE-INFLUENCE-001
  INV-COMPILE-NO-HORIZON-GLOBAL-001
  INV-COMPILE-CHRONOLOGICAL-ORDER-001
  INV-STARTUP-POISON-DETECTION-001
  INV-REVISION-NONEMPTY-PROGRAMMED-001

Some tests are EXPECTED TO FAIL against the current implementation.
They reproduce real outage conditions documented in
  docs/analysis/source_of_truth_current_state.md
"""

from __future__ import annotations

import os
import uuid as uuid_mod
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path

import pytest

try:
    from retrovue.config.testing import make_test_config
    from retrovue.domain.entities import (
        Channel,
        ChannelActiveRevision,
        ProgressionRun,
        ScheduleItem,
        ScheduleRevision,
    )
    from retrovue.infra.uow import session as db_session
    from retrovue.runtime.dsl_schedule_service import DslScheduleService
    from retrovue.runtime.schedule_types import ScheduledBlock
except ImportError:
    pytest.skip(
        "retrovue.runtime dependencies not available",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "channels"
_DSL_PATH = str(_FIXTURES_DIR / "test_integration.yaml")
_CHANNEL_SLUG = "test-integration"
_DAY_START_HOUR = 6
_SLOT_SEC = 1800  # 30 min


# ---------------------------------------------------------------------------
# Harness: channel + revision management
# ---------------------------------------------------------------------------


def _ensure_channel(db) -> Channel:
    """Create the test channel if it doesn't exist. Return it."""
    ch = db.query(Channel).filter(Channel.slug == _CHANNEL_SLUG).first()
    if ch is not None:
        return ch
    ch = Channel(
        slug=_CHANNEL_SLUG,
        title="Integration Test Channel",
        grid_block_minutes=30,
        kind="network",
        programming_day_start=dt_time(6, 0),
        block_start_offsets_minutes=[0],
    )
    db.add(ch)
    db.flush()
    return ch


def _purge_revisions(db, channel_id) -> None:
    """Delete all schedule revisions (and cascade items) for the channel."""
    db.query(ChannelActiveRevision).filter(
        ChannelActiveRevision.channel_id == channel_id,
    ).delete(synchronize_session=False)
    db.query(ScheduleRevision).filter(
        ScheduleRevision.channel_id == channel_id,
    ).delete(synchronize_session=False)
    db.flush()


def _purge_progression_runs(db) -> None:
    """Delete all ProgressionRun records for the test channel."""
    db.query(ProgressionRun).filter(
        ProgressionRun.channel_id == _CHANNEL_SLUG,
    ).delete(synchronize_session=False)
    db.flush()


def _insert_revision_with_items(
    db,
    channel: Channel,
    broadcast_day: date,
    num_items: int = 48,
) -> ScheduleRevision:
    """Insert a fully-populated active revision with compiled_segments.

    Each item gets a valid compiled_segments structure so that hydration
    succeeds. Segments sum to exactly slot_duration_ms (1800000ms).
    """
    rev = ScheduleRevision(
        channel_id=channel.id,
        broadcast_day=broadcast_day,
        status="active",
        activated_at=datetime.now(timezone.utc),
        created_by="integration_test",
    )
    db.add(rev)
    db.flush()

    day_start_dt = datetime(
        broadcast_day.year, broadcast_day.month, broadcast_day.day,
        _DAY_START_HOUR, 0, tzinfo=timezone.utc,
    )

    for i in range(num_items):
        start_time = day_start_dt + timedelta(seconds=i * _SLOT_SEC)
        asset_id = str(uuid_mod.uuid4())
        db.add(ScheduleItem(
            schedule_revision_id=rev.id,
            start_time=start_time,
            duration_sec=_SLOT_SEC,
            slot_index=i,
            content_type="episode",
            metadata_={
                "title": f"Test {broadcast_day.isoformat()} Block {i}",
                "asset_id_raw": asset_id,
                "compiled_segments": [
                    {
                        "segment_type": "content",
                        "asset_id": asset_id,
                        "duration_ms": 1_320_000,
                        "asset_start_offset_ms": 0,
                        "transition_in": "TRANSITION_NONE",
                        "transition_in_duration_ms": 0,
                        "transition_out": "TRANSITION_NONE",
                        "transition_out_duration_ms": 0,
                        "gain_db": 0.0,
                        "is_primary": False,
                    },
                    {
                        "segment_type": "filler",
                        "asset_id": "",
                        "duration_ms": 480_000,
                        "asset_start_offset_ms": 0,
                        "transition_in": "TRANSITION_NONE",
                        "transition_in_duration_ms": 0,
                        "transition_out": "TRANSITION_NONE",
                        "transition_out_duration_ms": 0,
                        "gain_db": 0.0,
                        "is_primary": False,
                    },
                ],
                "episode_duration_sec": 1320,
            },
        ))
    db.flush()

    # Upsert active-revision pointer
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    db.execute(
        pg_insert(ChannelActiveRevision.__table__).values(
            channel_id=channel.id,
            broadcast_day=broadcast_day,
            schedule_revision_id=rev.id,
            updated_at=datetime.now(timezone.utc),
        ).on_conflict_do_update(
            index_elements=["channel_id", "broadcast_day"],
            set_={
                "schedule_revision_id": rev.id,
                "updated_at": datetime.now(timezone.utc),
            },
        )
    )
    db.flush()
    return rev


def _insert_empty_revision(db, channel: Channel, broadcast_day: date) -> ScheduleRevision:
    """Insert an active revision with ZERO items (the poisoned state)."""
    rev = ScheduleRevision(
        channel_id=channel.id,
        broadcast_day=broadcast_day,
        status="active",
        activated_at=datetime.now(timezone.utc),
        created_by="integration_test_poison",
    )
    db.add(rev)
    db.flush()

    from sqlalchemy.dialects.postgresql import insert as pg_insert
    db.execute(
        pg_insert(ChannelActiveRevision.__table__).values(
            channel_id=channel.id,
            broadcast_day=broadcast_day,
            schedule_revision_id=rev.id,
            updated_at=datetime.now(timezone.utc),
        ).on_conflict_do_update(
            index_elements=["channel_id", "broadcast_day"],
            set_={
                "schedule_revision_id": rev.id,
                "updated_at": datetime.now(timezone.utc),
            },
        )
    )
    db.flush()
    return rev


# ---------------------------------------------------------------------------
# Harness: service construction
# ---------------------------------------------------------------------------


def _make_service(broadcast_day: str, horizon_days: int = 3) -> DslScheduleService:
    """Construct a real DslScheduleService pointing at the test DSL.

    Parameters:
        broadcast_day: ISO date string, e.g. "2026-03-27"
        horizon_days: how many days to load/compile (default 3)

    The service uses:
        - Real DSL file at tests/fixtures/channels/test_integration.yaml
        - Real test database (patched by conftest autouse fixture)
        - Real CatalogAssetResolver (built lazily on first compile)
        - broadcast_day override to control the startup date
        - channel_slug = "test-integration"
    """
    config = dict(make_test_config())
    # Override horizon to control test scope
    config["scheduling"] = dict(config["scheduling"])
    config["scheduling"]["horizon"] = {
        "days": horizon_days,
        "recompile_threshold_hours": 6,
    }

    return DslScheduleService(
        dsl_path=_DSL_PATH,
        filler_path="/dev/null",
        filler_duration_ms=30_000,
        broadcast_day=broadcast_day,
        programming_day_start_hour=_DAY_START_HOUR,
        channel_slug=_CHANNEL_SLUG,
        channel_type="network",
        resolved_config=config,
    )


# ---------------------------------------------------------------------------
# Harness: time helpers
# ---------------------------------------------------------------------------


def _day_start_ms(day: date) -> int:
    """UTC milliseconds for broadcast day start at 06:00."""
    dt = datetime(day.year, day.month, day.day, _DAY_START_HOUR, 0, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _day_end_ms(day: date) -> int:
    """UTC milliseconds for broadcast day end (next day 06:00)."""
    return _day_start_ms(day + timedelta(days=1))


def _blocks_in_range(blocks: list[ScheduledBlock], start_ms: int, end_ms: int) -> list[ScheduledBlock]:
    """Filter blocks whose start falls within [start_ms, end_ms)."""
    return [b for b in blocks if start_ms <= b.start_utc_ms < end_ms]


# ===========================================================================
# TEST 1: Future-Day Contamination (REAL BUG REPRODUCTION)
# ===========================================================================
#
# DB state BEFORE test:
#   Mar 26 (D-1): NO revision
#   Mar 27 (D):   NO revision       ← target day
#   Mar 28 (D+1): NO revision
#   Mar 29 (D+2): 48-item revision  ← loaded by _load_existing_timeline
#
# What _build_initial does:
#   1. _load_existing_timeline loads Mar 29 (48 blocks ending Mar 30 06:00)
#   2. loaded_blocks[-1].end_utc_ms = Mar 30 06:00 UTC
#   3. missing_days = ["2026-03-27", "2026-03-28"]
#   4. Compiles Mar 27 with carry-in = Mar 30 06:00 → ALL 48 blocks dropped
#   5. Compiles Mar 28 with carry-in = Mar 30 06:00 → ALL 48 blocks dropped
#   6. _blocks contains only Mar 29's blocks
#
# Expected CURRENT behavior: FAIL (Mar 27 has zero blocks)
# Expected FIXED behavior: PASS (Mar 27 has 48 blocks)
# ===========================================================================


@pytest.mark.contract
class TestFutureContamination:
    """INV-COMPILE-NO-FUTURE-INFLUENCE-001: Future-loaded schedule data
    must not suppress compilation of earlier days."""

    def test_future_revision_does_not_suppress_target_day(self):
        mar_27 = date(2026, 3, 27)
        mar_29 = date(2026, 3, 29)

        with db_session() as db:
            ch = _ensure_channel(db)
            _purge_revisions(db, ch.id)
            _purge_progression_runs(db)
            # Only Mar 29 exists in DB
            _insert_revision_with_items(db, ch, mar_29, num_items=48)

        svc = _make_service("2026-03-27", horizon_days=3)
        svc._build_initial(_CHANNEL_SLUG)

        mar_27_blocks = _blocks_in_range(
            svc._blocks, _day_start_ms(mar_27), _day_end_ms(mar_27),
        )

        # Clean up before assertion (so DB isn't dirty on failure)
        with db_session() as db:
            ch = _ensure_channel(db)
            _purge_revisions(db, ch.id)
            _purge_progression_runs(db)

        assert len(mar_27_blocks) > 0, (
            "INV-COMPILE-NO-FUTURE-INFLUENCE-001 VIOLATION: "
            f"Mar 27 has {len(mar_27_blocks)} blocks in _blocks. "
            f"Total _blocks: {len(svc._blocks)}. "
            "Future-day revision (Mar 29) suppressed target day compilation."
        )


# ===========================================================================
# TEST 2: Horizon Global Carry-In
# ===========================================================================
#
# DB state BEFORE test:
#   Mar 26 (D-1): 48-item revision  ← carry-in source for Mar 27
#   Mar 27 (D):   NO revision       ← target day
#   Mar 29 (D+2): 48-item revision  ← should NOT affect Mar 27
#
# Correct carry-in for Mar 27: end of Mar 26's last block = Mar 27 06:00
# Bug carry-in for Mar 27:     end of Mar 29's last block = Mar 30 06:00
#
# Expected CURRENT behavior: FAIL (global accumulator contaminates)
# Expected FIXED behavior: PASS (per-day carry-in used)
# ===========================================================================


@pytest.mark.contract
class TestHorizonGlobalCarryIn:
    """INV-COMPILE-NO-HORIZON-GLOBAL-001: Carry-in must be derived from
    D-1 only, not from a global horizon accumulator."""

    def test_d_minus_1_and_future_day_do_not_cross_contaminate(self):
        mar_26 = date(2026, 3, 26)
        mar_27 = date(2026, 3, 27)
        mar_29 = date(2026, 3, 29)

        with db_session() as db:
            ch = _ensure_channel(db)
            _purge_revisions(db, ch.id)
            _purge_progression_runs(db)
            # D-1 exists: Mar 26 (48 items, ending Mar 27 06:00)
            _insert_revision_with_items(db, ch, mar_26, num_items=48)
            # D+2 exists: Mar 29 (48 items, ending Mar 30 06:00)
            _insert_revision_with_items(db, ch, mar_29, num_items=48)
            # D (Mar 27) is MISSING — must be compiled

        svc = _make_service("2026-03-26", horizon_days=4)
        svc._build_initial(_CHANNEL_SLUG)

        mar_27_blocks = _blocks_in_range(
            svc._blocks, _day_start_ms(mar_27), _day_end_ms(mar_27),
        )
        total = len(svc._blocks)

        with db_session() as db:
            ch = _ensure_channel(db)
            _purge_revisions(db, ch.id)
            _purge_progression_runs(db)

        # D-1 (Mar 26) ends at Mar 27 06:00 → carry-in = day start → no blocks dropped
        # D+2 (Mar 29) must NOT influence Mar 27's carry-in
        assert len(mar_27_blocks) > 0, (
            "INV-COMPILE-NO-HORIZON-GLOBAL-001 VIOLATION: "
            f"Mar 27 has {len(mar_27_blocks)} blocks. Total: {total}. "
            "Carry-in from Mar 29 (global horizon) suppressed Mar 27."
        )


# ===========================================================================
# TEST 3: Chronological Compilation Order
# ===========================================================================
#
# DB state BEFORE test:
#   Mar 27 (D):   NO revision
#   Mar 28 (D+1): NO revision
#   Mar 29 (D+2): 48-item revision
#
# Missing days = ["2026-03-27", "2026-03-28"]
#
# Correct order: compile Mar 27 first, use its output as carry-in for Mar 28
# Wrong order: compile both with the same global carry-in
#
# Expected CURRENT behavior: FAIL (both days get future carry-in)
# Expected FIXED behavior: PASS (chronological, each day uses D-1 output)
# ===========================================================================


@pytest.mark.contract
class TestChronologicalOrder:
    """INV-COMPILE-CHRONOLOGICAL-ORDER-001: Missing days must be compiled
    in ascending order. Each day's output provides carry-in for the next."""

    def test_both_missing_days_get_blocks(self):
        mar_27 = date(2026, 3, 27)
        mar_28 = date(2026, 3, 28)
        mar_29 = date(2026, 3, 29)

        with db_session() as db:
            ch = _ensure_channel(db)
            _purge_revisions(db, ch.id)
            _purge_progression_runs(db)
            # Only Mar 29 in DB
            _insert_revision_with_items(db, ch, mar_29, num_items=48)

        svc = _make_service("2026-03-27", horizon_days=3)
        svc._build_initial(_CHANNEL_SLUG)

        mar_27_blocks = _blocks_in_range(
            svc._blocks, _day_start_ms(mar_27), _day_end_ms(mar_27),
        )
        mar_28_blocks = _blocks_in_range(
            svc._blocks, _day_start_ms(mar_28), _day_end_ms(mar_28),
        )

        with db_session() as db:
            ch = _ensure_channel(db)
            _purge_revisions(db, ch.id)
            _purge_progression_runs(db)

        # Both missing days must have blocks
        assert len(mar_27_blocks) > 0, (
            "INV-COMPILE-CHRONOLOGICAL-ORDER-001 VIOLATION: "
            f"Mar 27 has {len(mar_27_blocks)} blocks."
        )
        assert len(mar_28_blocks) > 0, (
            "INV-COMPILE-CHRONOLOGICAL-ORDER-001 VIOLATION: "
            f"Mar 28 has {len(mar_28_blocks)} blocks."
        )


# ===========================================================================
# TEST 4: Empty Revision Blocking Channel (Poison Detection)
# ===========================================================================
#
# DB state BEFORE test:
#   Mar 27: EMPTY active revision (0 items) ← poisoned state
#   Mar 28: NO revision
#
# What _build_initial does:
#   1. _load_existing_timeline: Mar 27's revision loaded but produces 0 blocks
#      (compiled_segments list is empty or absent → items skipped)
#   2. Mar 27 not in loaded_days → added to missing_days
#   3. _compile_day(Mar 27): _get_cached_schedule finds the empty revision →
#      may return None (cache miss) or empty segmented_blocks → may compile
#      fresh but write refused (active revision already exists)
#   4. _blocks has zero blocks for Mar 27
#
# Contract requirement: System must detect the empty revision, supersede it,
# and rebuild. If rebuild fails, fail fast.
#
# Expected CURRENT behavior: FAIL (empty revision blocks recovery)
# Expected FIXED behavior: PASS (auto-supersede + rebuild)
# ===========================================================================


@pytest.mark.contract
class TestEmptyRevisionPoisoning:
    """INV-STARTUP-POISON-DETECTION-001: Empty active revisions on
    programmed days must be detected and not accepted as valid."""

    def test_empty_revision_does_not_produce_working_channel(self):
        mar_27 = date(2026, 3, 27)

        with db_session() as db:
            ch = _ensure_channel(db)
            _purge_revisions(db, ch.id)
            _purge_progression_runs(db)
            # Insert poisoned (empty) revision
            _insert_empty_revision(db, ch, mar_27)

        svc = _make_service("2026-03-27", horizon_days=2)
        svc._build_initial(_CHANNEL_SLUG)

        mar_27_blocks = _blocks_in_range(
            svc._blocks, _day_start_ms(mar_27), _day_end_ms(mar_27),
        )

        with db_session() as db:
            ch = _ensure_channel(db)
            _purge_revisions(db, ch.id)
            _purge_progression_runs(db)

        # CONTRACT: System must either:
        # a) Automatically supersede the empty revision and rebuild → blocks > 0
        # b) Fail fast with explicit error
        #
        # MUST NOT: Silently accept 0 blocks and serve nothing
        assert len(mar_27_blocks) > 0, (
            "INV-STARTUP-POISON-DETECTION-001 VIOLATION: "
            f"Mar 27 has {len(mar_27_blocks)} blocks after startup with "
            "empty active revision. System did not detect poison and rebuild. "
            f"Total _blocks: {len(svc._blocks)}"
        )

    def test_empty_revision_is_superseded_after_recovery(self):
        """After successful recovery from an empty revision, the empty
        revision must be superseded and a new non-empty revision active."""
        mar_27 = date(2026, 3, 27)

        with db_session() as db:
            ch = _ensure_channel(db)
            _purge_revisions(db, ch.id)
            _purge_progression_runs(db)
            _insert_empty_revision(db, ch, mar_27)

        svc = _make_service("2026-03-27", horizon_days=2)
        svc._build_initial(_CHANNEL_SLUG)

        # Check DB state: the active revision for Mar 27 should now
        # have items (if recovery worked)
        with db_session() as db:
            ch = _ensure_channel(db)
            active_rev = db.query(ScheduleRevision).filter(
                ScheduleRevision.channel_id == ch.id,
                ScheduleRevision.broadcast_day == mar_27,
                ScheduleRevision.status == "active",
            ).first()

            item_count = 0
            if active_rev:
                item_count = db.query(ScheduleItem).filter(
                    ScheduleItem.schedule_revision_id == active_rev.id,
                ).count()

            # Cleanup
            _purge_revisions(db, ch.id)
            _purge_progression_runs(db)

        assert item_count > 0, (
            "INV-STARTUP-POISON-DETECTION-001 VIOLATION: "
            f"Active revision for Mar 27 has {item_count} items after startup. "
            "Empty revision was not superseded and rebuilt."
        )


# ===========================================================================
# TEST 5: Non-Empty Revision Persistence Guard
# ===========================================================================
#
# This test verifies that the persistence layer rejects empty schedules
# for programmed days. It compiles a schedule that produces blocks, then
# verifies the revision has items. Then it checks what happens when
# _apply_overlap_push_forward drops all blocks (simulating the bug).
# ===========================================================================


@pytest.mark.contract
class TestRevisionNonemptyGuard:
    """INV-REVISION-NONEMPTY-PROGRAMMED-001: Active revisions on programmed
    days must have at least one ScheduleItem."""

    def test_normal_compile_produces_nonempty_revision(self):
        """Baseline: compiling a programmed day produces a non-empty revision."""
        mar_27 = date(2026, 3, 27)

        with db_session() as db:
            ch = _ensure_channel(db)
            _purge_revisions(db, ch.id)
            _purge_progression_runs(db)

        svc = _make_service("2026-03-27", horizon_days=1)
        svc._build_initial(_CHANNEL_SLUG)

        with db_session() as db:
            ch = _ensure_channel(db)
            rev = db.query(ScheduleRevision).filter(
                ScheduleRevision.channel_id == ch.id,
                ScheduleRevision.broadcast_day == mar_27,
                ScheduleRevision.status == "active",
            ).first()

            item_count = 0
            if rev:
                item_count = db.query(ScheduleItem).filter(
                    ScheduleItem.schedule_revision_id == rev.id,
                ).count()

            _purge_revisions(db, ch.id)
            _purge_progression_runs(db)

        assert rev is not None, "Compilation should produce a revision"
        assert item_count > 0, (
            f"Active revision has {item_count} items. "
            "A programmed day must produce a non-empty revision."
        )
