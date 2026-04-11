"""
Contract: docs/contracts/schedule_playlog_authority_and_rebuild.md
Invariant: INV-REVISION-NONEMPTY-PROGRAMMED-001

An active ScheduleRevision for a non-dark programmed day MUST contain
at least one ScheduleItem. Persisting a zero-item revision on a
programmed day is a contract violation.

This test verifies that the schedule revision writer does not persist
empty revisions when the DSL defines programming.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch
import uuid as uuid_mod

import pytest

try:
    from retrovue.domain.entities import (
        Channel,
        ChannelActiveRevision,
        ScheduleItem,
        ScheduleRevision,
    )
    from retrovue.runtime.schedule_revision_writer import (
        write_active_revision_from_compiled_schedule,
    )
except ImportError:
    pytest.skip(
        "retrovue.runtime dependencies not available",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Fake DB for isolated testing
# ---------------------------------------------------------------------------


class _FakeQuery:
    """Minimal query mock for write_active_revision_from_compiled_schedule."""

    def __init__(self, results=None):
        self._results = results or []

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._results[0] if self._results else None

    def update(self, values, **kwargs):
        return 0


class _FakeDB:
    """Minimal DB session mock."""

    def __init__(self, channel=None):
        self._channel = channel
        self.added: list = []
        self._executed: list = []

    def query(self, model):
        if model is Channel:
            return _FakeQuery([self._channel] if self._channel else [])
        if model is ScheduleRevision:
            return _FakeQuery()
        if model is ScheduleItem:
            return _FakeQuery()
        return _FakeQuery()

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        # Simulate ID assignment
        for obj in self.added:
            if isinstance(obj, ScheduleRevision) and not hasattr(obj, 'id'):
                obj.id = uuid_mod.uuid4()

    def execute(self, stmt):
        self._executed.append(stmt)


# ---------------------------------------------------------------------------
# INV-REVISION-NONEMPTY-PROGRAMMED-001
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestRevisionNonemptyProgrammed:
    """Empty revisions must not be persisted for programmed days."""

    def test_empty_program_blocks_still_creates_revision(self):
        """CURRENT BEHAVIOR (violates contract): The writer accepts an empty
        program_blocks list and creates a revision with zero items.

        This test documents the violation. The contract requires the writer
        to reject this.
        """
        channel = Channel(
            id=uuid_mod.uuid4(), slug="test-ch", title="Test",
        )
        db = _FakeDB(channel=channel)

        # Schedule with zero program blocks (the bug scenario)
        empty_schedule = {
            "program_blocks": [],
            "source": {"compiler_version": "test"},
        }

        with patch(
            "retrovue.runtime.schedule_revision_writer._clock"
        ) as mock_clock:
            mock_clock.now_utc.return_value = datetime(
                2026, 4, 1, 12, 0, tzinfo=timezone.utc,
            )
            result = write_active_revision_from_compiled_schedule(
                db,
                channel_slug="test-ch",
                broadcast_day=date(2026, 4, 1),
                schedule=empty_schedule,
                created_by="test",
            )

        revisions = [x for x in db.added if isinstance(x, ScheduleRevision)]
        items = [x for x in db.added if isinstance(x, ScheduleItem)]

        # CURRENT: writer creates a revision with zero items (BUG)
        # CONTRACT: writer MUST reject empty schedules for programmed days
        #
        # When the fix is applied, change this test to:
        #   assert result is False  (write rejected)
        #   assert len(revisions) == 0  (no revision created)
        if len(revisions) > 0 and len(items) == 0:
            pytest.fail(
                "INV-REVISION-NONEMPTY-PROGRAMMED-001 VIOLATION: "
                f"Revision created with {len(items)} items on a programmed day. "
                "An active revision for a programmed day MUST contain >= 1 item."
            )

    def test_nonempty_schedule_creates_revision_with_items(self):
        """Normal case: non-empty schedule creates revision with items."""
        channel = Channel(
            id=uuid_mod.uuid4(), slug="test-ch", title="Test",
        )
        db = _FakeDB(channel=channel)

        schedule = {
            "program_blocks": [
                {
                    "title": "Test Block",
                    "start_at": "2026-04-01T06:00:00+00:00",
                    "slot_duration_sec": 1800,
                    "asset_id": str(uuid_mod.uuid4()),
                    "episode_duration_sec": 1320,
                    "compiled_segments": [
                        {"segment_type": "content", "asset_id": "a", "duration_ms": 1320000},
                        {"segment_type": "filler", "asset_id": "", "duration_ms": 480000},
                    ],
                },
            ],
            "source": {"compiler_version": "test"},
        }

        with patch(
            "retrovue.runtime.schedule_revision_writer._clock"
        ) as mock_clock:
            mock_clock.now_utc.return_value = datetime(
                2026, 4, 1, 5, 0, tzinfo=timezone.utc,  # before day start
            )
            result = write_active_revision_from_compiled_schedule(
                db,
                channel_slug="test-ch",
                broadcast_day=date(2026, 4, 1),
                schedule=schedule,
                created_by="test",
            )

        assert result is True
        revisions = [x for x in db.added if isinstance(x, ScheduleRevision)]
        items = [x for x in db.added if isinstance(x, ScheduleItem)]
        assert len(revisions) == 1
        assert len(items) == 1
        assert items[0].slot_index == 0
