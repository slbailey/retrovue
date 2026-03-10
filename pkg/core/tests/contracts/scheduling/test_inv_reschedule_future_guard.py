from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from retrovue.usecases.schedule_reschedule import RescheduleRejectedError, reschedule_by_id
from retrovue.domain.entities import ScheduleRevision, ScheduleItem, PlaylistEvent

NOW = datetime(2026, 3, 3, 12, 0, 0, tzinfo=timezone.utc)
NOW_UTC_MS = int(NOW.timestamp() * 1000)


def _mk_revision(start_time: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        channel=SimpleNamespace(slug="test-channel"),
        broadcast_day=date(2026, 3, 4),
        status="active",
        metadata_={},
        superseded_at=None,
        start_time=start_time,
    )


def _mk_item(rev_id, slot=0, start=None):
    st = start or (NOW + timedelta(hours=1))
    return SimpleNamespace(
        schedule_revision_id=rev_id,
        start_time=st,
        duration_sec=1800,
        asset_id=None,
        collection_id=None,
        content_type="episode",
        window_uuid=None,
        slot_index=slot,
        metadata_={},
    )


def _mock_db(tier1_revision=None, tier1_items=None, tier2_row=None):
    db = MagicMock()
    tier1_items = tier1_items or []

    def q(entity):
        m = MagicMock()
        mf = MagicMock()
        m.filter.return_value = mf
        mf.filter.return_value = mf
        mf.order_by.return_value = mf
        if entity is ScheduleRevision:
            mf.first.return_value = tier1_revision
        elif entity is ScheduleItem:
            # first() for guard, all() for clone
            mf.first.return_value = tier1_items[0] if tier1_items else None
            mf.all.return_value = tier1_items
        elif entity is PlaylistEvent:
            mf.first.return_value = tier2_row
            mf.delete.return_value = 0
        return m

    db.query.side_effect = q
    return db


class TestInvRescheduleFutureGuard001:
    # Tier: 2 | Scheduling logic invariant
    def test_tier1_past_revision_rejected(self):
        rev = _mk_revision(NOW - timedelta(hours=1))
        db = _mock_db(tier1_revision=rev, tier1_items=[_mk_item(rev.id, start=NOW - timedelta(hours=1))])
        with pytest.raises(RescheduleRejectedError, match="INV-RESCHEDULE-FUTURE-GUARD-001"):
            reschedule_by_id(db, identifier=str(rev.id), now=NOW)

    # Tier: 2 | Scheduling logic invariant
    def test_tier1_future_revision_accepted(self):
        rev = _mk_revision(NOW + timedelta(hours=1))
        items = [_mk_item(rev.id, slot=0, start=NOW + timedelta(hours=1))]
        db = _mock_db(tier1_revision=rev, tier1_items=items)
        result = reschedule_by_id(db, identifier=str(rev.id), now=NOW)
        assert result["status"] == "ok"
        assert result["tier"] == "1"

    # Tier: 2 | Scheduling logic invariant
    def test_tier1_missing_items_rejected(self):
        rev = _mk_revision(NOW + timedelta(hours=1))
        db = _mock_db(tier1_revision=rev, tier1_items=[])
        with pytest.raises(RescheduleRejectedError, match="INV-RESCHEDULE-FUTURE-GUARD-001"):
            reschedule_by_id(db, identifier=str(rev.id), now=NOW)

    # Tier: 2 | Scheduling logic invariant
    def test_tier2_past_block_rejected(self):
        row = SimpleNamespace(
            block_id="b1", channel_slug="test-channel", broadcast_day=date(2026, 3, 4),
            start_utc_ms=NOW_UTC_MS - 1000, end_utc_ms=NOW_UTC_MS + 1000
        )
        db = _mock_db(tier2_row=row)
        with pytest.raises(RescheduleRejectedError, match="INV-RESCHEDULE-FUTURE-GUARD-001"):
            reschedule_by_id(db, identifier="b1", now=NOW)

    # Tier: 2 | Scheduling logic invariant
    def test_tier2_future_block_accepted(self):
        row = SimpleNamespace(
            block_id="b2", channel_slug="test-channel", broadcast_day=date(2026, 3, 4),
            start_utc_ms=NOW_UTC_MS + 1000, end_utc_ms=NOW_UTC_MS + 5000
        )
        db = _mock_db(tier2_row=row)
        result = reschedule_by_id(db, identifier="b2", now=NOW)
        assert result["status"] == "ok"
        assert result["tier"] == "2"
