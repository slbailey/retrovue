"""
Test configuration and fixtures for RetroVue.

This module provides test fixtures for database operations using Postgres and Alembic migrations.
All tests use the same database configuration as the application to ensure consistency.
"""

import os
from collections.abc import Generator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from retrovue.infra.settings import settings


_TEST_SCHEMA = "retrovue_test"


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """
    Get the test database URL.

    Uses the same database as the application but with a dedicated test schema
    to avoid destroying production tables on teardown.
    """
    base_url = settings.database_url
    if "?" in base_url:
        base_url = base_url.split("?")[0]
    return f"{base_url}?options=-csearch_path={_TEST_SCHEMA},public"


@pytest.fixture(scope="session")
def test_engine(test_database_url: str):
    """Create a test database engine."""
    engine = create_engine(
        test_database_url,
        echo=False,
        pool_pre_ping=True,
        future=True,
    )
    return engine


@pytest.fixture(scope="session")
def test_session_factory(test_engine):
    """Create a test session factory."""
    return sessionmaker(bind=test_engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database(test_engine, test_database_url):
    """
    Set up the test database with Alembic migrations in a dedicated test schema.

    Uses _TEST_SCHEMA so that teardown never touches the production 'public' schema.
    """

    # Resolve pkg/core root (where alembic.ini lives) regardless of cwd.
    _this_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.normpath(os.path.join(_this_dir, "..", "..", ".."))

    alembic_ini_path = os.path.join(project_root, "alembic.ini")
    alembic_dir_path = os.path.join(project_root, "alembic")

    # Create the test schema (idempotent)
    with test_engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_TEST_SCHEMA}"))
        conn.commit()

    # Run Alembic migrations into the test schema
    alembic_cfg = Config(alembic_ini_path)
    alembic_cfg.set_main_option("sqlalchemy.url", test_database_url)
    alembic_cfg.set_main_option("script_location", alembic_dir_path)
    command.upgrade(alembic_cfg, "head")

    yield

    # Teardown: drop ONLY the test schema — never touch public
    with test_engine.connect() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {_TEST_SCHEMA} CASCADE"))
        conn.commit()


@pytest.fixture
def db_session(test_session_factory) -> Generator[Session, None, None]:
    """
    Provide a database session for tests.
    
    This fixture provides a clean database session for each test.
    It automatically rolls back any changes made during the test.
    """
    session = test_session_factory()
    try:
        yield session
        session.rollback()  # Always rollback to keep tests isolated
    finally:
        session.close()


@pytest.fixture
def clean_db(db_session: Session):
    """
    Provide a clean database state for tests.
    
    This fixture ensures that each test starts with a clean database state
    by cleaning up any data that might have been left from previous tests.
    """
    # Clean up any existing test data
    # We don't drop the schema, just clean the data
    with db_session.begin():
        # Delete in reverse dependency order to avoid foreign key constraints
        # Note: Broadcast tables (broadcast_*, catalog_asset) have been dropped and are not used
        db_session.execute(text("DELETE FROM path_mappings"))
        db_session.execute(text("DELETE FROM collections"))
        db_session.execute(text("DELETE FROM sources"))
        db_session.execute(text("DELETE FROM provider_refs"))  # Delete provider_refs first
        db_session.execute(text("DELETE FROM review_queue"))
        db_session.execute(text("DELETE FROM markers"))
        db_session.execute(text("DELETE FROM episode_assets"))
        db_session.execute(text("DELETE FROM assets"))
        db_session.execute(text("DELETE FROM episodes"))
        db_session.execute(text("DELETE FROM seasons"))
        db_session.execute(text("DELETE FROM titles"))
    
    yield db_session


@pytest.fixture
def sample_asset_data():
    """Provide sample asset data for testing."""
    return {
        "uri": "file:///test/path/sample.mp4",
        "size": 1024000,
        "duration_ms": 120000,
        "video_codec": "h264",
        "audio_codec": "aac",
        "container": "mp4",
        "hash_sha256": "abcd1234" * 8,  # 64 character hash
        "canonical": True,
        "is_deleted": False,
    }


# Note: Broadcast domain fixtures removed - tables have been dropped and will be re-added when functionality is implemented
