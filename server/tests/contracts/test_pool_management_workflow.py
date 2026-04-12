"""Contract tests for Pool Management Workflow operations.

Validates:
- create_pool enforces INV-POOL-NAME-UNIQUE-001
- list_pools returns all pools ordered by name
- inspect_pool resolves match criteria via query_with_diagnostics (INV-POOL-RESOLUTION-VISIBILITY-001)
- assign_pool creates advisory pool→channel association
- PoolInspectResult dataclass has correct shape
- Error cases: duplicate name, missing pool, missing channel, duplicate assignment
"""

from __future__ import annotations

import uuid
from dataclasses import fields as dc_fields
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from retrovue.domain.entities import Channel, Pool, PoolAssignment
from retrovue.runtime.asset_resolver import PoolDiagnostics


# ---------------------------------------------------------------------------
# PoolInspectResult shape
# ---------------------------------------------------------------------------

class TestPoolInspectResultShape:
    """PoolInspectResult is a frozen dataclass with the contract fields."""

    def test_pool_inspect_result_is_importable(self):
        from retrovue.workflows.pool_management import PoolInspectResult
        assert PoolInspectResult is not None

    def test_pool_inspect_result_is_frozen_dataclass(self):
        from retrovue.workflows.pool_management import PoolInspectResult
        result = PoolInspectResult(
            pool_name="test",
            match_criteria={"type": "episode"},
            matched_asset_ids=["a1"],
            matched_count=1,
            diagnostics=MagicMock(spec=PoolDiagnostics),
        )
        with pytest.raises(AttributeError):
            result.pool_name = "changed"  # type: ignore[misc]

    def test_pool_inspect_result_has_required_fields(self):
        from retrovue.workflows.pool_management import PoolInspectResult
        field_names = {f.name for f in dc_fields(PoolInspectResult)}
        required = {"pool_name", "match_criteria", "matched_asset_ids", "matched_count", "diagnostics"}
        assert required == field_names


# ---------------------------------------------------------------------------
# create_pool
# ---------------------------------------------------------------------------

class TestCreatePool:
    """create_pool creates a Pool entity and enforces uniqueness."""

    def test_create_pool_returns_pool_entity(self):
        from retrovue.workflows.pool_management import create_pool

        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None

        pool = create_pool(db, name="horror_movies", match_criteria={"type": "movie", "tags": ["horror"]})

        assert isinstance(pool, Pool)
        assert pool.name == "horror_movies"
        assert pool.match_criteria == {"type": "movie", "tags": ["horror"]}

    def test_create_pool_with_description(self):
        from retrovue.workflows.pool_management import create_pool

        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None

        pool = create_pool(
            db,
            name="comedies",
            match_criteria={"type": "episode"},
            description="All comedy episodes",
        )

        assert pool.description == "All comedy episodes"

    def test_create_pool_adds_to_session(self):
        from retrovue.workflows.pool_management import create_pool

        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None

        pool = create_pool(db, name="test_pool", match_criteria={"type": "movie"})

        db.add.assert_called_once_with(pool)
        db.flush.assert_called_once()

    def test_create_pool_duplicate_name_raises(self):
        """INV-POOL-NAME-UNIQUE-001: duplicate pool name raises error."""
        from retrovue.workflows.pool_management import create_pool

        existing_pool = Pool(name="existing_pool", match_criteria={"type": "movie"})
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = existing_pool

        with pytest.raises(ValueError, match="already exists"):
            create_pool(db, name="existing_pool", match_criteria={"type": "episode"})


# ---------------------------------------------------------------------------
# list_pools
# ---------------------------------------------------------------------------

class TestListPools:
    """list_pools returns all pools ordered by name."""

    def test_list_pools_returns_list(self):
        from retrovue.workflows.pool_management import list_pools

        pool_a = Pool(name="alpha", match_criteria={"type": "movie"})
        pool_b = Pool(name="beta", match_criteria={"type": "episode"})

        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [pool_a, pool_b]

        result = list_pools(db)

        assert result == [pool_a, pool_b]

    def test_list_pools_empty(self):
        from retrovue.workflows.pool_management import list_pools

        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = []

        result = list_pools(db)

        assert result == []


# ---------------------------------------------------------------------------
# inspect_pool
# ---------------------------------------------------------------------------

class TestInspectPool:
    """inspect_pool resolves match criteria and returns diagnostics."""

    def test_inspect_pool_returns_inspect_result(self):
        """INV-POOL-RESOLUTION-VISIBILITY-001: inspect returns diagnostics."""
        from retrovue.workflows.pool_management import inspect_pool, PoolInspectResult

        pool = Pool(name="horror", match_criteria={"type": "movie", "tags": ["horror"]})
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = pool

        diagnostics = PoolDiagnostics(
            total_considered=10,
            excluded_by_type=3,
            excluded_by_tags=2,
            excluded_by_rating=0,
            excluded_by_duration=0,
            excluded_by_editorial=0,
            matched=5,
            exclusion_reasons={},
        )
        resolver = MagicMock()
        resolver.query_with_diagnostics.return_value = (["a1", "a2", "a3", "a4", "a5"], diagnostics)

        result = inspect_pool(db, resolver, "horror")

        assert isinstance(result, PoolInspectResult)
        assert result.pool_name == "horror"
        assert result.match_criteria == {"type": "movie", "tags": ["horror"]}
        assert result.matched_asset_ids == ["a1", "a2", "a3", "a4", "a5"]
        assert result.matched_count == 5
        assert result.diagnostics is diagnostics

    def test_inspect_pool_calls_query_with_diagnostics(self):
        from retrovue.workflows.pool_management import inspect_pool

        pool = Pool(name="test", match_criteria={"type": "episode"})
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = pool

        diagnostics = PoolDiagnostics(
            total_considered=0, excluded_by_type=0, excluded_by_tags=0,
            excluded_by_rating=0, excluded_by_duration=0, excluded_by_editorial=0,
            matched=0, exclusion_reasons={},
        )
        resolver = MagicMock()
        resolver.query_with_diagnostics.return_value = ([], diagnostics)

        inspect_pool(db, resolver, "test")

        resolver.query_with_diagnostics.assert_called_once_with({"type": "episode"})

    def test_inspect_pool_not_found_raises(self):
        from retrovue.workflows.pool_management import inspect_pool

        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        resolver = MagicMock()

        with pytest.raises(ValueError, match="not found"):
            inspect_pool(db, resolver, "nonexistent")


# ---------------------------------------------------------------------------
# assign_pool
# ---------------------------------------------------------------------------

class TestAssignPool:
    """assign_pool creates advisory pool→channel association."""

    def test_assign_pool_returns_pool_assignment(self):
        from retrovue.workflows.pool_management import assign_pool

        pool = Pool(name="horror", match_criteria={"type": "movie"})
        pool.id = uuid.uuid4()
        channel_id = uuid.uuid4()
        channel = MagicMock(spec=Channel)
        channel.id = channel_id
        channel.slug = "retro-horror"

        db = MagicMock()
        # First call: pool lookup, Second call: channel lookup, Third call: existing assignment check
        db.execute.return_value.scalar_one_or_none.side_effect = [pool, channel, None]

        result = assign_pool(db, pool_name="horror", channel_name="retro-horror")

        assert isinstance(result, PoolAssignment)
        assert result.pool_id == pool.id
        assert result.channel_id == channel_id

    def test_assign_pool_adds_to_session(self):
        from retrovue.workflows.pool_management import assign_pool

        pool = Pool(name="horror", match_criteria={"type": "movie"})
        pool.id = uuid.uuid4()
        channel = MagicMock(spec=Channel)
        channel.id = uuid.uuid4()
        channel.slug = "retro-horror"

        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.side_effect = [pool, channel, None]

        assignment = assign_pool(db, pool_name="horror", channel_name="retro-horror")

        db.add.assert_called_once_with(assignment)
        db.flush.assert_called_once()

    def test_assign_pool_missing_pool_raises(self):
        from retrovue.workflows.pool_management import assign_pool

        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.side_effect = [None]

        with pytest.raises(ValueError, match="Pool.*not found"):
            assign_pool(db, pool_name="nonexistent", channel_name="ch1")

    def test_assign_pool_missing_channel_raises(self):
        from retrovue.workflows.pool_management import assign_pool

        pool = Pool(name="horror", match_criteria={"type": "movie"})
        pool.id = uuid.uuid4()

        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.side_effect = [pool, None]

        with pytest.raises(ValueError, match="Channel.*not found"):
            assign_pool(db, pool_name="horror", channel_name="nonexistent")

    def test_assign_pool_duplicate_raises(self):
        """Duplicate pool-channel assignment raises error."""
        from retrovue.workflows.pool_management import assign_pool

        pool = Pool(name="horror", match_criteria={"type": "movie"})
        pool.id = uuid.uuid4()
        channel_id = uuid.uuid4()
        channel = MagicMock(spec=Channel)
        channel.id = channel_id
        channel.slug = "retro-horror"
        existing = PoolAssignment(pool_id=pool.id, channel_id=channel_id)

        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.side_effect = [pool, channel, existing]

        with pytest.raises(ValueError, match="already assigned"):
            assign_pool(db, pool_name="horror", channel_name="retro-horror")
