"""Fixtures for scheduling contract tests (PostgreSQL gate)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from retrovue.infra import db as db_module
from retrovue.runtime.schedule_revision_writer import (
    _register_schedule_item_immutability_guards,
)


@pytest.fixture(scope="module")
def postgres_engine():
    """Real engine from TEST_DATABASE_URL; skip if not PostgreSQL."""
    engine = db_module.get_engine(for_test=True)
    if engine.dialect.name != "postgresql":
        pytest.skip(
            "Scheduling invariant v1 tests require PostgreSQL "
            "(set TEST_DATABASE_URL to a Postgres URL, not SQLite)"
        )
    # INV-SCHEDULE-TIME-IMMUTABILITY-001: same before_execute guard as production (test engine
    # is distinct from retrovue.infra.db.engine, so import-time registration does not cover it).
    _register_schedule_item_immutability_guards(engine)
    return engine


@pytest.fixture
def pg_session(postgres_engine) -> Session:
    """Session per test; caller commits or rolls back."""
    SessionLocal = sessionmaker(bind=postgres_engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
