"""
Test fixtures for application services.

This module provides test fixtures for database sessions and services.
"""

import os
import tempfile
from collections.abc import Generator

import pytest

pytestmark = pytest.mark.skip(reason="Legacy module quarantined in src_legacy/; do not depend on it.")
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from retrovue.content_manager.ingest_service import IngestService  # noqa: E402
from retrovue.content_manager.library_service import LibraryService  # noqa: E402
from retrovue.domain.entities import Base  # noqa: E402


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


@pytest.fixture
def library_service(temp_db_session: Session) -> LibraryService:
    """Create a library service with a test session."""
    return LibraryService(temp_db_session)


@pytest.fixture
def ingest_service(temp_db_session: Session) -> IngestService:
    """Create an ingest service with a test session."""
    return IngestService(temp_db_session)


@pytest.fixture
def sample_discovered_data() -> dict:
    """Sample discovered data for testing."""
    return {
        "path_uri": "file:///media/retro/Show.S01E01.mkv",
        "size": 123456789,
        "hash_sha256": "a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456",
        "provider": "filesystem",
        "raw_labels": {"title_guess": "Show", "season": 1, "episode": 1},
        "last_modified": "2025-01-01T12:00:00Z",
    }


@pytest.fixture
def sample_enrichment_data() -> dict:
    """Sample enrichment data for testing."""
    return {
        "duration_ms": 3600000,  # 1 hour
        "video_codec": "h264",
        "audio_codec": "aac",
        "container": "mkv",
    }
