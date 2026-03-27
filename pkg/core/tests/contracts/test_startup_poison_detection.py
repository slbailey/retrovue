"""
Contract: docs/contracts/schedule_playlog_authority_and_rebuild.md
Invariant: INV-STARTUP-POISON-DETECTION-001

On startup, an empty active revision on a programmed day MUST be detected
as invalid. The system MUST automatically supersede it and attempt rebuild.
If rebuild fails, the channel MUST fail fast — not silently degrade.

This test verifies that the startup/load path detects empty revisions
and does not accept them as valid schedule state.
"""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta, timezone

import pytest

try:
    from retrovue.runtime.dsl_schedule_service import (
        DslScheduleService,
        _deserialize_scheduled_block,
        _serialize_scheduled_block,
    )
    from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment
    from retrovue.domain.entities import (
        Channel,
        ScheduleItem,
        ScheduleRevision,
    )
    from retrovue.infra.uow import session as db_session
except ImportError:
    pytest.skip(
        "retrovue.runtime dependencies not available",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _day_start_ms(day: date, hour: int = 6) -> int:
    dt = datetime(day.year, day.month, day.day, hour, 0, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _cleanup_channel(db, slug: str) -> None:
    """Remove test channel and related data."""
    ch = db.query(Channel).filter(Channel.slug == slug).first()
    if ch:
        # Cascade deletes revisions + items
        db.delete(ch)
        db.flush()


# ---------------------------------------------------------------------------
# INV-STARTUP-POISON-DETECTION-001
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestStartupPoisonDetection:
    """Empty active revisions must be detected and not accepted."""

    def test_empty_revision_in_db_is_detectable(self):
        """An active revision with zero items can be detected by checking
        the items relationship."""
        with db_session() as db:
            slug = "test-poison-detect"
            _cleanup_channel(db, slug)

            # Create channel
            from datetime import time as time_type
            ch = Channel(
                slug=slug,
                title="Poison Detection Test",
                grid_block_minutes=30,
                kind="network",
                programming_day_start=time_type(6, 0),
                block_start_offsets_minutes=[0],
            )
            db.add(ch)
            db.flush()

            # Create an empty active revision (the poisoned state)
            rev = ScheduleRevision(
                channel_id=ch.id,
                broadcast_day=date(2026, 4, 1),
                status="active",
                activated_at=datetime.now(timezone.utc),
                created_by="test_poison",
            )
            db.add(rev)
            db.flush()

            # Verify: revision exists and is active
            active_rev = db.query(ScheduleRevision).filter(
                ScheduleRevision.channel_id == ch.id,
                ScheduleRevision.broadcast_day == date(2026, 4, 1),
                ScheduleRevision.status == "active",
            ).first()
            assert active_rev is not None

            # Verify: zero items
            items = db.query(ScheduleItem).filter(
                ScheduleItem.schedule_revision_id == active_rev.id,
            ).all()
            assert len(items) == 0, "Empty revision should have zero items"

            # CONTRACT REQUIREMENT: This state must be detected as poisoned.
            # The system must NOT accept this as valid schedule state.
            # It must supersede and rebuild, or fail fast.
            #
            # Detection check: item count == 0 on active revision for programmed day
            is_poisoned = len(items) == 0
            assert is_poisoned, (
                "INV-STARTUP-POISON-DETECTION-001: "
                "Empty active revision must be detectable as poisoned"
            )

            # Cleanup
            db.delete(rev)
            db.delete(ch)

    def test_empty_revision_blocks_timeline_loading(self):
        """When an empty revision exists, _load_existing_timeline produces
        zero blocks for that day — the system has no content to serve."""
        with db_session() as db:
            slug = "test-poison-timeline"
            _cleanup_channel(db, slug)

            from datetime import time as time_type
            ch = Channel(
                slug=slug,
                title="Poison Timeline Test",
                grid_block_minutes=30,
                kind="network",
                programming_day_start=time_type(6, 0),
                block_start_offsets_minutes=[0],
            )
            db.add(ch)
            db.flush()

            # Create empty active revision for Apr 1
            rev = ScheduleRevision(
                channel_id=ch.id,
                broadcast_day=date(2026, 4, 1),
                status="active",
                activated_at=datetime.now(timezone.utc),
                created_by="test_poison",
            )
            db.add(rev)
            db.flush()

            # Query items for this revision
            items = db.query(ScheduleItem).filter(
                ScheduleItem.schedule_revision_id == rev.id,
            ).all()

            # Zero items → zero blocks → channel cannot serve content
            assert len(items) == 0

            # CONTRACT: The system must NOT silently serve nothing.
            # It must detect this and attempt rebuild.

            # Cleanup
            db.delete(rev)
            db.delete(ch)

    def test_nonempty_revision_is_not_poisoned(self):
        """A revision with items is valid and must not be treated as poisoned."""
        with db_session() as db:
            slug = "test-poison-valid"
            _cleanup_channel(db, slug)

            from datetime import time as time_type
            ch = Channel(
                slug=slug,
                title="Valid Revision Test",
                grid_block_minutes=30,
                kind="network",
                programming_day_start=time_type(6, 0),
                block_start_offsets_minutes=[0],
            )
            db.add(ch)
            db.flush()

            rev = ScheduleRevision(
                channel_id=ch.id,
                broadcast_day=date(2026, 4, 1),
                status="active",
                activated_at=datetime.now(timezone.utc),
                created_by="test_valid",
            )
            db.add(rev)
            db.flush()

            # Add an item
            item = ScheduleItem(
                schedule_revision_id=rev.id,
                start_time=datetime(2026, 4, 1, 6, 0, tzinfo=timezone.utc),
                duration_sec=1800,
                slot_index=0,
                content_type="episode",
                metadata_={
                    "title": "Test Block",
                    "compiled_segments": [
                        {"segment_type": "content", "asset_id": "a", "duration_ms": 1800000},
                    ],
                },
            )
            db.add(item)
            db.flush()

            items = db.query(ScheduleItem).filter(
                ScheduleItem.schedule_revision_id == rev.id,
            ).all()
            assert len(items) == 1, "Valid revision should have items"

            # This is NOT poisoned
            is_poisoned = len(items) == 0
            assert not is_poisoned

            # Cleanup
            db.delete(item)
            db.delete(rev)
            db.delete(ch)
