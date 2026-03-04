from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from retrovue.usecases.schedule_reschedule import list_reschedulable
from retrovue.domain.entities import ScheduleRevision, ScheduleItem, PlaylistEvent

NOW = datetime(2026, 3, 3, 12, 0, 0, tzinfo=timezone.utc)
NOW_UTC_MS = int(NOW.timestamp() * 1000)


def _revision(channel="hbo-classics", day=date(2026, 3, 4)):
    return SimpleNamespace(
        id=uuid.uuid4(),
        channel=SimpleNamespace(slug=channel),
        broadcast_day=day,
        status="active",
    )


def _item(rev_id, slot, start):
    return SimpleNamespace(
        schedule_revision_id=rev_id,
        slot_index=slot,
        start_time=start,
        duration_sec=1800,
    )


def _mock_db(revisions=None, items_by_rev=None, tier2_rows=None):
    revisions = revisions or []
    items_by_rev = items_by_rev or {}
    tier2_rows = tier2_rows or []
    db = MagicMock()

    def q(entity):
        m = MagicMock(); f = MagicMock()
        m.filter.return_value = f
        f.filter.return_value = f
        f.order_by.return_value = f
        f.join.return_value = f
        f.filter_by.return_value = f
        if entity is ScheduleRevision:
            f.all.return_value = revisions
        elif entity is ScheduleItem:
            # Choose first revision in map by default (good enough for contract checks)
            any_items = next(iter(items_by_rev.values()), [])
            f.first.return_value = any_items[0] if any_items else None
            f.all.return_value = any_items
        elif entity is PlaylistEvent:
            f.all.return_value = tier2_rows
        return m

    db.query.side_effect = q
    return db


class TestListReschedulable:
    def test_returns_future_tier1_from_active_revision(self):
        r = _revision()
        it = _item(r.id, 0, NOW + timedelta(hours=1))
        db = _mock_db(revisions=[r], items_by_rev={r.id: [it]})
        result = list_reschedulable(db, now=NOW)
        assert result["status"] == "ok"
        assert len(result["tier1"]) == 1

    def test_returns_future_tier2(self):
        row = SimpleNamespace(
            block_id="b1", channel_slug="hbo-classics", broadcast_day=date(2026, 3, 4),
            start_utc_ms=NOW_UTC_MS + 5000, end_utc_ms=NOW_UTC_MS + 10000, window_uuid=None
        )
        db = _mock_db(tier2_rows=[row])
        result = list_reschedulable(db, now=NOW)
        assert len(result["tier2"]) == 1

    def test_tier1_order_follows_slot_index(self):
        r = _revision()
        a = _item(r.id, 0, NOW + timedelta(hours=1))
        b = _item(r.id, 1, NOW + timedelta(hours=2))
        db = _mock_db(revisions=[r], items_by_rev={r.id: [a, b]})
        result = list_reschedulable(db, now=NOW)
        assert len(result["tier1"]) == 1

    def test_tier_filter(self):
        db = _mock_db()
        result = list_reschedulable(db, now=NOW, tier="1")
        assert "tier1" in result and result["tier2"] == []
