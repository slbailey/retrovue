"""Contract tests for Pool Management — INV-POOL-NAME-UNIQUE-001.

Validates:
- Pool entity has correct schema (name unique, match_criteria NOT NULL)
- PoolAssignment entity has correct FK relationships
- Pool name uniqueness is enforced at DB constraint level
- Cascade-delete: deleting a Pool removes its PoolAssignments
"""

import uuid

import pytest
from sqlalchemy import inspect as sa_inspect
from unittest.mock import MagicMock

from retrovue.domain.entities import Pool, PoolAssignment


class TestPoolEntitySchema:
    """Pool entity matches the contract schema."""

    def test_pool_tablename_is_pools(self):
        assert Pool.__tablename__ == "pools"

    def test_pool_has_required_columns(self):
        mapper = sa_inspect(Pool)
        column_names = {c.key for c in mapper.columns}
        required = {"id", "name", "description", "match_criteria", "created_at", "updated_at"}
        assert required.issubset(column_names), f"Missing columns: {required - column_names}"

    def test_pool_name_column_is_not_nullable(self):
        mapper = sa_inspect(Pool)
        name_col = mapper.columns["name"]
        assert name_col.nullable is False

    def test_pool_match_criteria_column_is_not_nullable(self):
        mapper = sa_inspect(Pool)
        mc_col = mapper.columns["match_criteria"]
        assert mc_col.nullable is False

    def test_pool_description_column_is_nullable(self):
        mapper = sa_inspect(Pool)
        desc_col = mapper.columns["description"]
        assert desc_col.nullable is True

    def test_pool_has_unique_name_constraint(self):
        """INV-POOL-NAME-UNIQUE-001: Pool names enforce uniqueness at DB level."""
        table = Pool.__table__
        unique_constraints = [
            c for c in table.constraints
            if hasattr(c, "columns") and "name" in [col.name for col in c.columns]
        ]
        # Must have at least one unique constraint covering the name column
        has_unique = any(
            getattr(c, "name", None) == "uq_pools_name"
            for c in unique_constraints
        )
        assert has_unique, "Missing UniqueConstraint 'uq_pools_name' on Pool.name"

    def test_pool_id_is_uuid_primary_key(self):
        mapper = sa_inspect(Pool)
        id_col = mapper.columns["id"]
        assert id_col.primary_key is True


class TestPoolAssignmentEntitySchema:
    """PoolAssignment entity matches the contract schema."""

    def test_pool_assignment_tablename(self):
        assert PoolAssignment.__tablename__ == "pool_assignments"

    def test_pool_assignment_has_required_columns(self):
        mapper = sa_inspect(PoolAssignment)
        column_names = {c.key for c in mapper.columns}
        required = {"id", "pool_id", "channel_id", "created_at"}
        assert required.issubset(column_names), f"Missing columns: {required - column_names}"

    def test_pool_assignment_pool_id_is_fk(self):
        mapper = sa_inspect(PoolAssignment)
        pool_id_col = mapper.columns["pool_id"]
        assert pool_id_col.nullable is False
        fk_targets = [fk.target_fullname for fk in pool_id_col.foreign_keys]
        assert "pools.id" in fk_targets

    def test_pool_assignment_channel_id_is_fk(self):
        mapper = sa_inspect(PoolAssignment)
        channel_id_col = mapper.columns["channel_id"]
        assert channel_id_col.nullable is False
        fk_targets = [fk.target_fullname for fk in channel_id_col.foreign_keys]
        assert "channels.id" in fk_targets

    def test_pool_assignment_has_unique_pool_channel_constraint(self):
        """Prevent duplicate pool-channel assignments."""
        table = PoolAssignment.__table__
        unique_constraints = [
            c for c in table.constraints
            if hasattr(c, "columns")
            and {col.name for col in c.columns} == {"pool_id", "channel_id"}
        ]
        assert len(unique_constraints) == 1, (
            "Missing UniqueConstraint on (pool_id, channel_id)"
        )
        assert unique_constraints[0].name == "uq_pool_assignments_pool_channel"


class TestPoolRelationships:
    """Pool -> PoolAssignment relationship is correctly configured."""

    def test_pool_has_assignments_relationship(self):
        mapper = sa_inspect(Pool)
        rel_names = {r.key for r in mapper.relationships}
        assert "assignments" in rel_names

    def test_pool_assignments_cascade_delete_orphan(self):
        mapper = sa_inspect(Pool)
        assignments_rel = next(r for r in mapper.relationships if r.key == "assignments")
        cascade = assignments_rel.cascade
        assert cascade.delete is True
        assert cascade.delete_orphan is True


class TestPoolNameUniquenessWorkflow:
    """Workflow-level uniqueness enforcement for INV-POOL-NAME-UNIQUE-001."""

    def test_duplicate_name_leaves_original_unchanged(self):
        """POOL-MGMT-003: Original pool is unchanged after duplicate creation attempt."""
        from retrovue.workflows.pool_management import create_pool

        original_criteria = {"type": "movie", "tags": ["horror"]}
        original_pool = Pool(name="horror_movies", match_criteria=original_criteria)

        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = original_pool

        with pytest.raises(ValueError, match="already exists"):
            create_pool(db, name="horror_movies", match_criteria={"type": "episode"})

        # Original pool's match_criteria must not have been mutated
        assert original_pool.match_criteria == original_criteria
        assert original_pool.name == "horror_movies"
        # db.add should NOT have been called (no new entity created)
        db.add.assert_not_called()

    def test_case_sensitive_pool_names_are_distinct(self):
        """POOL-MGMT-004: Pool names differing only by case are allowed."""
        from retrovue.workflows.pool_management import create_pool

        db = MagicMock()
        # No existing pool found for 'Horror_Movies'
        db.execute.return_value.scalar_one_or_none.return_value = None

        pool = create_pool(db, name="Horror_Movies", match_criteria={"type": "movie"})

        assert pool.name == "Horror_Movies"
        db.add.assert_called_once()
