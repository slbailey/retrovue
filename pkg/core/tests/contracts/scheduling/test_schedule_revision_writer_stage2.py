from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import uuid as uuid_mod

from retrovue.domain.entities import Channel, ScheduleItem, ScheduleRevision
from retrovue.runtime.schedule_revision_writer import (
    write_active_revision_from_compiled_schedule,
)


@dataclass
class _UpdateCall:
    values: dict


class _FakeQuery:
    def __init__(self, db: "_FakeDB", model):
        self._db = db
        self._model = model

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        if self._model is Channel:
            return self._db.channel
        return None

    def update(self, values, synchronize_session=False):
        self._db.update_calls.append(_UpdateCall(values=values))
        return 1


class _FakeDB:
    def __init__(self, channel: Channel | None):
        self.channel = channel
        self.added: list[object] = []
        self.update_calls: list[_UpdateCall] = []
        self.executed: list[object] = []

    def query(self, model):
        return _FakeQuery(self, model)

    def add(self, obj):
        self.added.append(obj)

    def execute(self, stmt):
        self.executed.append(stmt)

    def flush(self):
        # Mimic DB-assigned PK availability after flush.
        for obj in self.added:
            if isinstance(obj, ScheduleRevision) and obj.id is None:
                obj.id = uuid_mod.uuid4()


def _sample_schedule() -> dict:
    return {
        "version": "program-schedule.v2",
        "source": {"compiler_version": "2.2.0"},
        "hash": "sha256:test",
        "program_blocks": [
            {
                "title": "Show A",
                "asset_id": "not-a-uuid",
                "start_at": "2026-03-04T06:00:00+00:00",
                "slot_duration_sec": 1800,
                "episode_duration_sec": 1320,
            },
            {
                "title": "Show B",
                "asset_id": "also-not-a-uuid",
                "start_at": "2026-03-04T06:30:00+00:00",
                "slot_duration_sec": 1800,
                "episode_duration_sec": 1320,
            },
        ],
    }


def test_stage2_dual_write_supersedes_then_writes_deterministic_slot_indices():
    channel = Channel(id=uuid_mod.uuid4(), slug="retro1", title="Retro 1")
    db = _FakeDB(channel=channel)

    ok = write_active_revision_from_compiled_schedule(
        db,
        channel_slug="retro1",
        broadcast_day=date(2026, 3, 4),
        schedule=_sample_schedule(),
        created_by="test",
    )

    assert ok is True
    assert len(db.update_calls) == 1, "Expected supersede update before insert"

    revisions = [x for x in db.added if isinstance(x, ScheduleRevision)]
    items = [x for x in db.added if isinstance(x, ScheduleItem)]

    assert len(revisions) == 1
    assert len(items) == 2

    # Deterministic ordering from enumerate(program_blocks)
    assert [i.slot_index for i in items] == [0, 1]

    # All items belong to exactly one new revision
    assert len({i.schedule_revision_id for i in items}) == 1
    assert items[0].schedule_revision_id == revisions[0].id


def test_stage2_dual_write_skips_unknown_channel_for_backward_compat():
    db = _FakeDB(channel=None)

    ok = write_active_revision_from_compiled_schedule(
        db,
        channel_slug="missing-channel",
        broadcast_day=date(2026, 3, 4),
        schedule=_sample_schedule(),
    )

    assert ok is False
    assert db.added == []


def test_channel_active_pointer_upserted_on_activation():
    channel = Channel(id=uuid_mod.uuid4(), slug="retro1", title="Retro 1")
    db = _FakeDB(channel=channel)

    ok = write_active_revision_from_compiled_schedule(
        db,
        channel_slug="retro1",
        broadcast_day=date(2026, 3, 4),
        schedule=_sample_schedule(),
        created_by="test",
    )

    assert ok is True
    assert len(db.executed) == 1, "Expected channel_active_revisions upsert execute"
