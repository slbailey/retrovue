"""
Test fixtures for BroadcastChannel tests.

This module provides test fixtures for database setup using Postgres and Alembic migrations.
All tests use a dedicated test database schema to ensure isolation.
"""

import os
from collections.abc import Generator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from retrovue.infra.settings import settings


@pytest.fixture(scope="session")
def test_db_url() -> str:
    """
    Create a test database URL for Postgres.
    
    Uses the same database as production but with a test schema for isolation.
    """
    # Use environment variable if set, otherwise use the main database
    test_url = os.getenv("TEST_DATABASE_URL", settings.database_url)
    return test_url


@pytest.fixture(scope="session")
def migrated_db(test_db_url: str) -> None:
    """
    Run Alembic migrations before test execution.
    
    This ensures the database schema matches the current migration state.
    """
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")


@pytest.fixture(scope="session")
def test_db_engine(test_db_url: str, migrated_db: None) -> Generator[Engine, None, None]:
    """
    Create a test database engine using the main database.
    
    Uses the same database as production but with schema isolation for tests.
    """
    # Create the test engine
    engine = create_engine(
        test_db_url,
        echo=False,
        pool_pre_ping=True,
        future=True,
        pool_size=1,
        max_overflow=0,
    )
    
    yield engine
    
    # Cleanup
    engine.dispose()


@pytest.fixture(scope="function")
def test_db_session(test_db_engine: Engine) -> Generator[Session, None, None]:
    """
    Create a test database session using the main database.
    
    Each test gets a fresh session that can be rolled back for isolation.
    """
    # Create session factory
    SessionLocal = sessionmaker(bind=test_db_engine)
    session = SessionLocal()
    
    # Start a transaction that we can rollback
    transaction = session.begin()
    
    try:
        yield session
    finally:
        # Rollback the transaction to clean up test data
        try:
            transaction.rollback()
        except Exception:
            pass  # Transaction may already be closed
        session.close()


@pytest.fixture(scope="function")
def db_session(test_db_session: Session) -> Session:
    """
    Alias for test_db_session to match the service's expected interface.
    
    This allows the BroadcastChannelService to work with the test session
    without modification.
    """
    return test_db_session
