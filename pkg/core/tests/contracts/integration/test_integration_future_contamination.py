"""
Contract: docs/contracts/schedule_playlog_authority_and_rebuild.md
Invariant: INV-COMPILE-NO-FUTURE-INFLUENCE-001
           INV-COMPILE-NO-HORIZON-GLOBAL-001

INTEGRATION TEST: Reproduces the exact outage class where future-loaded
schedule data contaminates earlier-day compilation.

Uses real DslScheduleService, real DB, real compilation pipeline.
No mocking of core scheduling logic.

Expected behavior against CURRENT code: FAIL (bug reproduction)
Expected behavior after fix: PASS
"""

from __future__ import annotations

import os
import tempfile
import uuid as uuid_mod
from datetime import date, datetime, time as dt_time, timedelta, timezone

import pytest

try:
    from retrovue.config.testing import make_test_config
    from retrovue.domain.entities import (
        Channel,
        ChannelActiveRevision,
        ScheduleItem,
        ScheduleRevision,
    )
    from retrovue.infra.uow import session as db_session
    from retrovue.runtime.dsl_schedule_service import DslScheduleService
except ImportError:
    pytest.skip(
        "retrovue.runtime dependencies not available",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Minimal DSL that defines a 24-hour schedule (48 x 30min blocks)
_MINIMAL_DSL = """\
channel: {slug}
number: 999
name: "Integration Test Channel"
channel_type: network
timezone: UTC

format:
  video: {{ width: 720, height: 480, frame_rate: "30000/1001" }}
  audio: {{ sample_rate: 48000, channels: 2 }}
  grid_minutes: 30

pools:
  test_content:
    select:
      where:
        type:
          eq: episode

programs:
  test_show:
    pool: test_content
    grid_blocks: 1
    fill_mode: single

schedule:
  all_day:
    - start: "06:00"
      slots: 48
      program: [test_show]
      progression: sequential
"""


def _make_channel(db, slug: str) -> Channel:
    """Create a minimal channel in DB."""
    ch = Channel(
        slug=slug,
        title="Integration Test Channel",
        grid_block_minutes=30,
        kind="network",
        programming_day_start=dt_time(6, 0),
        block_start_offsets_minutes=[0],
    )
    db.add(ch)
    db.flush()
    return ch


def _make_revision_with_items(
    db,
    channel: Channel,
    broadcast_day: date,
    num_items: int = 48,
    day_start_hour: int = 6,
) -> ScheduleRevision:
    """Create an active revision with items spanning a full day."""
    rev = ScheduleRevision(
        channel_id=channel.id,
        broadcast_day=broadcast_day,
        status="active",
        activated_at=datetime.now(timezone.utc),
        created_by="test_integration",
    )
    db.add(rev)
    db.flush()

    day_start = datetime(
        broadcast_day.year, broadcast_day.month, broadcast_day.day,
        day_start_hour, 0, tzinfo=timezone.utc,
    )
    slot_sec = 1800  # 30 min

    for i in range(num_items):
        start_time = day_start + timedelta(seconds=i * slot_sec)
        db.add(ScheduleItem(
            schedule_revision_id=rev.id,
            start_time=start_time,
            duration_sec=slot_sec,
            slot_index=i,
            content_type="episode",
            metadata_={
                "title": f"Test Block {i}",
                "asset_id_raw": str(uuid_mod.uuid4()),
                "compiled_segments": [
                    {
                        "segment_type": "content",
                        "asset_id": str(uuid_mod.uuid4()),
                        "duration_ms": 1320000,
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
                        "duration_ms": 480000,
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
    return rev


def _cleanup(db, slug: str) -> None:
    """Remove all test data for a channel slug."""
    ch = db.query(Channel).filter(Channel.slug == slug).first()
    if ch:
        # Delete revisions (cascade deletes items)
        db.query(ScheduleRevision).filter(
            ScheduleRevision.channel_id == ch.id,
        ).delete(synchronize_session=False)
        # Delete active revision pointers
        db.query(ChannelActiveRevision).filter(
            ChannelActiveRevision.channel_id == ch.id,
        ).delete(synchronize_session=False)
        db.delete(ch)
        db.flush()


def _make_dsl_file(slug: str) -> str:
    """Write a temporary DSL YAML file and return the path."""
    content = _MINIMAL_DSL.format(slug=slug)
    fd, path = tempfile.mkstemp(suffix=".yaml", prefix="test_dsl_")
    os.write(fd, content.encode())
    os.close(fd)
    return path


def _make_service(dsl_path: str, slug: str, broadcast_day: str) -> DslScheduleService:
    """Create a DslScheduleService for testing."""
    config = dict(make_test_config())
    return DslScheduleService(
        dsl_path=dsl_path,
        filler_path="/dev/null",
        filler_duration_ms=30000,
        broadcast_day=broadcast_day,
        programming_day_start_hour=6,
        channel_slug=slug,
        channel_type="network",
        resolved_config=config,
    )


# ---------------------------------------------------------------------------
# INTEGRATION TESTS
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestIntegrationFutureContamination:
    """Reproduces the real outage: future-day blocks contaminate
    earlier-day compilation via global carry-in accumulator."""

    def test_future_day_revision_suppresses_target_day_blocks(self):
        """BUG REPRODUCTION:
        - DB has revision for D+2 (Mar 29) with 48 items
        - DB has NO revision for D (Mar 27) or D+1 (Mar 28)
        - Service starts with broadcast_day=Mar 27, horizon=3 days

        CURRENT BEHAVIOR (BUG):
        - _load_existing_timeline loads Mar 29 blocks
        - loaded_blocks[-1].end_utc_ms = Mar 30 06:00
        - Missing days = [Mar 27, Mar 28]
        - Mar 27 compile: carry-in = Mar 30 06:00 → ALL blocks dropped
        - Mar 28 compile: carry-in = Mar 30 06:00 → ALL blocks dropped
        - Channel has zero blocks → 503

        CORRECT BEHAVIOR (after fix):
        - Mar 27 compile: carry-in from Mar 26 (none → 0) → 48 blocks
        - Mar 28 compile: carry-in from Mar 27 (ending Mar 28 06:00) → 48 blocks
        """
        slug = f"test-future-contam-{uuid_mod.uuid4().hex[:8]}"
        dsl_path = _make_dsl_file(slug)

        try:
            with db_session() as db:
                _cleanup(db, slug)
                ch = _make_channel(db, slug)

                # Create revision for Mar 29 only (the future day)
                _make_revision_with_items(db, ch, date(2026, 3, 29), num_items=48)

                # No revision for Mar 27 or Mar 28

            # Create service with broadcast_day=Mar 27
            svc = _make_service(dsl_path, slug, "2026-03-27")

            # Trigger startup
            svc._build_initial(slug)

            # Check what _blocks contains
            blocks = svc._blocks

            # Find blocks that cover Mar 27
            mar_27_start = int(
                datetime(2026, 3, 27, 6, 0, tzinfo=timezone.utc).timestamp() * 1000
            )
            mar_27_end = int(
                datetime(2026, 3, 28, 6, 0, tzinfo=timezone.utc).timestamp() * 1000
            )
            mar_27_blocks = [
                b for b in blocks
                if b.start_utc_ms >= mar_27_start and b.start_utc_ms < mar_27_end
            ]

            # CONTRACT REQUIREMENT: Mar 27 must have blocks.
            # The future-day (Mar 29) must NOT suppress them.
            #
            # CURRENT BUG: mar_27_blocks will be 0 because the global
            # carry-in from Mar 29 drops everything.
            assert len(mar_27_blocks) > 0, (
                "INV-COMPILE-NO-FUTURE-INFLUENCE-001 VIOLATION: "
                f"Mar 27 has {len(mar_27_blocks)} blocks. "
                "Future-day revision (Mar 29) suppressed target day compilation. "
                f"Total _blocks: {len(blocks)}"
            )

        finally:
            # Cleanup
            os.unlink(dsl_path)
            with db_session() as db:
                _cleanup(db, slug)

    def test_target_day_with_d_minus_1_and_future_day(self):
        """Correct scenario: D-1 exists, D+2 exists, D is missing.
        D must use D-1 carry-in, not D+2."""
        slug = f"test-d-minus-1-future-{uuid_mod.uuid4().hex[:8]}"
        dsl_path = _make_dsl_file(slug)

        try:
            with db_session() as db:
                _cleanup(db, slug)
                ch = _make_channel(db, slug)

                # D-1 (Mar 26) with 48 items ending at Mar 27 06:00
                _make_revision_with_items(db, ch, date(2026, 3, 26), num_items=48)
                # D+2 (Mar 29) with 48 items ending at Mar 30 06:00
                _make_revision_with_items(db, ch, date(2026, 3, 29), num_items=48)
                # D (Mar 27) is missing

            svc = _make_service(dsl_path, slug, "2026-03-27")
            svc._build_initial(slug)
            blocks = svc._blocks

            mar_27_start = int(
                datetime(2026, 3, 27, 6, 0, tzinfo=timezone.utc).timestamp() * 1000
            )
            mar_27_end = int(
                datetime(2026, 3, 28, 6, 0, tzinfo=timezone.utc).timestamp() * 1000
            )
            mar_27_blocks = [
                b for b in blocks
                if b.start_utc_ms >= mar_27_start and b.start_utc_ms < mar_27_end
            ]

            # D-1 (Mar 26) ends at Mar 27 06:00 → carry-in = Mar 27 06:00
            # Effective open for Mar 27 = max(Mar 27 06:00, Mar 27 06:00) = Mar 27 06:00
            # No blocks should be dropped.
            assert len(mar_27_blocks) > 0, (
                "INV-COMPILE-NO-FUTURE-INFLUENCE-001 VIOLATION: "
                f"Mar 27 has {len(mar_27_blocks)} blocks despite D-1 existing. "
                "Future-day (Mar 29) contaminated carry-in."
            )

        finally:
            os.unlink(dsl_path)
            with db_session() as db:
                _cleanup(db, slug)


@pytest.mark.contract
class TestIntegrationHorizonCarryIn:
    """Verifies that carry-in is per-day, not horizon-global."""

    def test_loaded_blocks_from_multiple_days_do_not_cross_contaminate(self):
        """When DB has days D-1 and D+2 but not D,
        the carry-in for D must come from D-1 only."""
        slug = f"test-horizon-carry-{uuid_mod.uuid4().hex[:8]}"
        dsl_path = _make_dsl_file(slug)

        try:
            with db_session() as db:
                _cleanup(db, slug)
                ch = _make_channel(db, slug)

                # D-1 (Mar 26): full day, ends Mar 27 06:00
                _make_revision_with_items(db, ch, date(2026, 3, 26), num_items=48)
                # D+2 (Mar 29): full day, ends Mar 30 06:00
                _make_revision_with_items(db, ch, date(2026, 3, 29), num_items=48)

            svc = _make_service(dsl_path, slug, "2026-03-27")
            svc._build_initial(slug)

            # After startup, check total block count
            total_blocks = len(svc._blocks)

            # Should have blocks for at least 3 days:
            # D-1 (loaded: 48), D (compiled: 48), D+2 (loaded: 48)
            # Plus D+1 if it was compiled too
            # Minimum: 48 (D-1) + some blocks for D
            assert total_blocks >= 48 + 1, (
                "INV-COMPILE-NO-HORIZON-GLOBAL-001 VIOLATION: "
                f"Only {total_blocks} blocks in timeline. "
                "Expected at least 49 (48 from D-1 + blocks for D). "
                "Horizon-global carry-in likely suppressed missing days."
            )

            # Specifically check D (Mar 27) has blocks
            mar_27_start = int(
                datetime(2026, 3, 27, 6, 0, tzinfo=timezone.utc).timestamp() * 1000
            )
            mar_27_end = int(
                datetime(2026, 3, 28, 6, 0, tzinfo=timezone.utc).timestamp() * 1000
            )
            mar_27_blocks = [
                b for b in svc._blocks
                if b.start_utc_ms >= mar_27_start and b.start_utc_ms < mar_27_end
            ]
            assert len(mar_27_blocks) > 0, (
                "INV-COMPILE-NO-HORIZON-GLOBAL-001 VIOLATION: "
                f"Mar 27 has {len(mar_27_blocks)} blocks. "
                "Global carry-in from Mar 29 suppressed compilation."
            )

        finally:
            os.unlink(dsl_path)
            with db_session() as db:
                _cleanup(db, slug)
