"""
Test fixtures for API tests.

This module provides test fixtures for API testing with database sessions.
"""

import os
import tempfile
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from retrovue.domain.entities import Base


@pytest.fixture
def temp_db_path() -> str:
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = f.name
    yield temp_path
    # Cleanup
    if os.path.exists(temp_path):
        os.unlink(temp_path)


@pytest.fixture
def temp_db_engine(temp_db_path: str):
    """Create a temporary database engine."""
    engine = create_engine(f"sqlite:///{temp_db_path}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def temp_db_session(temp_db_engine) -> Generator[Session, None, None]:
    """Create a temporary database session."""
    SessionLocal = sessionmaker(bind=temp_db_engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
