"""
Contract tests for INV-EPG-READS-CANONICAL-SCHEDULE-001.

EPG data MUST be derived from the canonical compiled schedule — the same
DB-cached ScheduleRevision/ScheduleItems that playout uses. EPG endpoints
MUST NOT call compile_schedule() directly.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from retrovue.runtime.dsl_schedule_service import DslScheduleService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SRC_ROOT = Path(__file__).parents[3] / "src" / "retrovue"
UTC = timezone.utc


def _mock_db_for_epg(
    channel_id: int,
    items: list[MagicMock],
    *,
    pointers: list[MagicMock] | None = None,
    revisions: list[MagicMock] | None = None,
):
    """Build a MagicMock db that handles the multi-query chain in get_canonical_epg.

    The code does:
      1. db.query(Channel).filter(slug==...).first() → Channel row
      2. db.query(ChannelActiveRevision).filter(...).order_by(...).all() → pointers
      3. db.query(ScheduleRevision).filter(id.in_(...)).all() → revisions
      4. db.query(ScheduleItem).filter(...).order_by(...).all() → items
    """
    from retrovue.domain.entities import (
        Channel, ChannelActiveRevision, ScheduleItem, ScheduleRevision,
    )

    mock_channel = MagicMock()
    mock_channel.id = channel_id

    # Default: one revision with id=1
    if revisions is None:
        rev = MagicMock()
        rev.id = 1
        revisions = [rev]

    # Default: one pointer per revision
    if pointers is None:
        pointers = []
        for rev in revisions:
            ptr = MagicMock()
            ptr.schedule_revision_id = rev.id
            pointers.append(ptr)

    db = MagicMock()

    def _query_dispatch(entity):
        chain = MagicMock()
        if entity is Channel:
            chain.filter.return_value.first.return_value = mock_channel
        elif entity is ChannelActiveRevision:
            chain.filter.return_value.order_by.return_value.all.return_value = pointers
        elif entity is ScheduleRevision:
            chain.filter.return_value.all.return_value = revisions
        elif entity is ScheduleItem:
            chain.filter.return_value.order_by.return_value.all.return_value = items
        return chain

    db.query.side_effect = _query_dispatch
    return db


def _make_schedule_item(
    title: str,
    start_time: datetime,
    duration_sec: int,
    *,
    asset_id: str = "",
    content_type: str = "movie",
    revision_id: int = 1,
) -> MagicMock:
    """Build a mock ScheduleItem matching what get_canonical_epg reads."""
    item = MagicMock()
    item.schedule_revision_id = revision_id
    item.start_time = start_time
    item.duration_sec = duration_sec
    item.asset_id = asset_id
    item.collection_id = None
    item.content_type = content_type
    item.metadata_ = {"asset_id_raw": asset_id}
    item.slot_index = 0
    return item


# ---------------------------------------------------------------------------
# Contract Tests
# ---------------------------------------------------------------------------


class TestInvEpgReadsCanonical001:
    """INV-EPG-READS-CANONICAL-SCHEDULE-001 contract tests."""

    # Tier: 2 | Scheduling logic invariant
    def test_epg_module_does_not_import_compile_schedule(self):
        """The /api/epg handler in program_director.py MUST NOT call
        compile_schedule(). Verified via AST inspection."""
        pd_path = SRC_ROOT / "runtime" / "program_director.py"
        source = pd_path.read_text()
        tree = ast.parse(source, filename=str(pd_path))

        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "get_epg_all":
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        func = child.func
                        if isinstance(func, ast.Name) and func.id == "compile_schedule":
                            violations.append(
                                f"program_director.py:{child.lineno} — "
                                f"compile_schedule() in get_epg_all"
                            )
                        elif isinstance(func, ast.Attribute) and func.attr == "compile_schedule":
                            violations.append(
                                f"program_director.py:{child.lineno} — "
                                f"compile_schedule() in get_epg_all"
                            )

        assert violations == [], (
            f"EPG handler calls compile_schedule() directly:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    # Tier: 2 | Scheduling logic invariant
    def test_get_canonical_epg_returns_cached_blocks(self):
        """get_canonical_epg reads from active ScheduleRevision/ScheduleItems
        without calling compile_schedule()."""
        window_start = datetime(2026, 3, 1, 6, 0, tzinfo=UTC)
        window_end = datetime(2026, 3, 2, 6, 0, tzinfo=UTC)

        items = [
            _make_schedule_item(
                f"Movie {i+1}",
                window_start + timedelta(hours=i),
                3600,
                asset_id=f"asset.movie_{i+1}",
            )
            for i in range(24)
        ]

        mock_db = _mock_db_for_epg(channel_id=1, items=items)

        with patch("retrovue.runtime.dsl_schedule_service.session") as mock_session:
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)

            result = DslScheduleService.get_canonical_epg(
                "showtime-cinema", window_start, window_end
            )

        assert result is not None
        assert len(result) == 24
        assert result[0]["asset_id"] == "asset.movie_1"

    # Tier: 2 | Scheduling logic invariant
    def test_get_canonical_epg_returns_none_when_not_cached(self):
        """When no channel exists, get_canonical_epg() returns None."""
        window_start = datetime(2026, 3, 1, 6, 0, tzinfo=UTC)
        window_end = datetime(2026, 3, 2, 6, 0, tzinfo=UTC)

        with patch("retrovue.runtime.dsl_schedule_service.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            # Channel query returns None
            mock_db.query.return_value.filter.return_value.first.return_value = None

            result = DslScheduleService.get_canonical_epg(
                "showtime-cinema", window_start, window_end
            )

        assert result is None

    # Tier: 2 | Scheduling logic invariant
    def test_get_canonical_epg_includes_carry_in_block(self):
        """A ScheduleItem from the previous day that overlaps the window
        MUST be included in the EPG output."""
        window_start = datetime(2026, 3, 1, 6, 0, tzinfo=UTC)
        window_end = datetime(2026, 3, 2, 6, 0, tzinfo=UTC)

        # Carry-in: starts 04:00 (before window), 4h duration → ends 08:00 (inside window)
        carry_in = _make_schedule_item(
            "Late Night Movie",
            datetime(2026, 3, 1, 4, 0, tzinfo=UTC),
            14400,
            asset_id="asset.late_movie",
            revision_id=1,
        )
        # Day N block: starts 08:00
        day_block = _make_schedule_item(
            "Morning Show",
            datetime(2026, 3, 1, 8, 0, tzinfo=UTC),
            3600,
            asset_id="asset.morning",
            revision_id=2,
        )

        rev1 = MagicMock()
        rev1.id = 1
        rev2 = MagicMock()
        rev2.id = 2

        # We need items to be returned for each revision query.
        # Since the mock dispatches all ScheduleItem queries the same way,
        # return both items — the code filters by window overlap.
        mock_db = _mock_db_for_epg(
            channel_id=1,
            items=[carry_in, day_block],
            revisions=[rev1, rev2],
        )

        with patch("retrovue.runtime.dsl_schedule_service.session") as mock_session:
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)

            result = DslScheduleService.get_canonical_epg(
                "showtime-cinema", window_start, window_end
            )

        assert result is not None
        asset_ids = [b["asset_id"] for b in result]
        assert "asset.late_movie" in asset_ids, (
            "Carry-in block from previous day not included"
        )
