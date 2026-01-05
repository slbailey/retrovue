"""
Global test configuration for RetroVue.

This module provides global pytest configuration and fixtures.
"""

import pytest
from sqlalchemy.orm import sessionmaker

import sys
from pathlib import Path

# Ensure the project src directory is importable without relying on external environment.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from retrovue.infra import db as db_module
from retrovue.infra.settings import settings


def pytest_ignore_collect(collection_path, config):
    """
    Ignore collection of test files in the _legacy directory.
    
    This ensures that legacy tests are never collected or run,
    preventing import errors from outdated modules.
    """
    if "_legacy" in str(collection_path):
        return True
    return False


@pytest.fixture(autouse=True)
def _force_test_db(monkeypatch):
    """
    Automatically point DB at TEST_DATABASE_URL during pytest.

    If TEST_DATABASE_URL is not set, we fall back to DATABASE_URL so tests still run.
    """
    use_test = bool(settings.test_database_url)

    # rebuild engine for tests
    engine = db_module.get_engine(for_test=use_test)

    # override the module-level SessionLocal with a test-bound one
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

    monkeypatch.setattr(db_module, "SessionLocal", TestSessionLocal)

    # optional: make get_engine() return the test engine when called again
    monkeypatch.setattr(db_module, "get_engine", lambda for_test=False, db_url=None: engine)
