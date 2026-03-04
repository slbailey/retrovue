from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from retrovue.usecases.schedule_reschedule import reschedule_by_id
from retrovue.domain.entities import ScheduleRevision, ScheduleItem, PlaylistEvent

NOW = datetime(2026, 3, 3, 12, 0, 0, tzinfo=timezone.utc)


def _rev():
    return SimpleNamespace(
        id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        channel=SimpleNamespace(slug="hbo-classics"),
        broadcast_day=date(2026, 3, 4),
        status="active",
        metadata_={},
    )


def _item(rev_id):
    return SimpleNamespace(
        schedule_revision_id=rev_id,
        start_time=NOW + timedelta(hours=1),
        duration_sec=1800,
        asset_id=None,
        collection_id=None,
        content_type="episode",
        window_uuid=None,
        slot_index=0,
        metadata_={},
    )


def _db(revision, deleted_count):
    db = MagicMock()

    def q(entity):
        m = MagicMock()
        f = MagicMock()
        m.filter.return_value = f
        f.filter.return_value = f
        f.order_by.return_value = f
        if entity is ScheduleRevision:
            f.first.return_value = revision
        elif entity is ScheduleItem:
            f.first.return_value = _item(revision.id)
            f.all.return_value = [_item(revision.id)]
        elif entity is PlaylistEvent:
            f.delete.return_value = deleted_count
        return m

    db.query.side_effect = q
    return db


class TestInvRescheduleCascadeTier2001:
    def test_cascade_deletes_future_tier2_rows(self):
        r = _rev()
        db = _db(r, deleted_count=3)
        result = reschedule_by_id(db, identifier=str(r.id), now=NOW)
        assert result["deleted_tier2"] == 3

    def test_cascade_preserves_past_tier2_rows(self):
        r = _rev()
        db = _db(r, deleted_count=0)
        result = reschedule_by_id(db, identifier=str(r.id), now=NOW)
        assert result["deleted_tier2"] == 0

    def test_revision_lifecycle_supersedes_old(self):
        r = _rev()
        db = _db(r, deleted_count=0)
        reschedule_by_id(db, identifier=str(r.id), now=NOW)
        assert r.status == "superseded"

    def test_revision_lifecycle_creates_new_active(self):
        r = _rev()
        db = _db(r, deleted_count=0)
        reschedule_by_id(db, identifier=str(r.id), now=NOW)
        # new revision + copied item were added
        assert db.add.call_count >= 2
