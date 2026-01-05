"""
Data contract tests for Asset Attention usecase.

Verifies filtering conditions and return shape for assets needing attention.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from retrovue.usecases.asset_attention import list_assets_needing_attention


def _asset(**kwargs):
    defaults = dict(
        uuid="11111111-1111-1111-1111-111111111111",
        collection_uuid="22222222-2222-2222-2222-222222222222",
        uri="/media/a.mp4",
        state="enriching",
        approved_for_broadcast=False,
        discovered_at=datetime(2025, 10, 30, 12, 0, tzinfo=UTC),
        is_deleted=False,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class _ScalarResult:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


def test_filters_include_enriching_and_not_approved():
    # Arrange: simulate DB returning a mix of assets
    enriching = _asset(uuid="a" * 36, state="enriching", approved_for_broadcast=False)
    ready_unapproved = _asset(uuid="b" * 36, state="ready", approved_for_broadcast=False)
    _ready_ok = _asset(uuid="c" * 36, state="ready", approved_for_broadcast=True)

    fake_db = MagicMock()
    fake_db.execute.return_value.scalars.return_value = _ScalarResult([enriching, ready_unapproved])

    # Act
    rows = list_assets_needing_attention(fake_db)

    # Assert: only enriching and not approved appear
    ids = {r["uuid"] for r in rows}
    assert "a" * 36 in ids
    assert "b" * 36 in ids
    assert "c" * 36 not in ids

    # Assert: shape
    for r in rows:
        assert set(r.keys()) == {
            "uuid",
            "collection_uuid",
            "uri",
            "state",
            "approved_for_broadcast",
            "discovered_at",
        }






