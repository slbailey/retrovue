"""
Tests for INV-TEST-DB-ISOLATION-001.

Proves that the test DB guard refuses to proceed when TEST_DATABASE_URL
is not explicitly configured, preventing silent fallback to production.
"""

import importlib

import pytest


def _get_real_get_engine():
    """Reload db module to bypass conftest monkeypatch and get the real get_engine."""
    from retrovue.infra import db as db_module

    reloaded = importlib.reload(db_module)
    return reloaded.get_engine


def test_force_test_db_raises_when_test_url_missing(monkeypatch):
    """INV-TEST-DB-ISOLATION-001: test suite MUST fail if TEST_DATABASE_URL is unset."""
    from retrovue.infra import settings as settings_mod

    # Simulate TEST_DATABASE_URL being absent
    monkeypatch.setattr(settings_mod.settings, "test_database_url", None)

    # Get the real get_engine (not the conftest-patched lambda)
    real_get_engine = _get_real_get_engine()

    # Attempting to create a test engine without TEST_DATABASE_URL must raise
    with pytest.raises(RuntimeError, match="TEST_DATABASE_URL"):
        real_get_engine(for_test=True)


def test_force_test_db_raises_when_test_url_equals_prod_url(monkeypatch):
    """INV-TEST-DB-ISOLATION-001: test suite MUST fail if TEST_DATABASE_URL == DATABASE_URL."""
    from retrovue.infra import settings as settings_mod

    prod_url = "postgresql://retrovue:pass@prod:5432/retrovue"
    monkeypatch.setattr(settings_mod.settings, "database_url", prod_url)
    monkeypatch.setattr(settings_mod.settings, "test_database_url", prod_url)

    real_get_engine = _get_real_get_engine()

    with pytest.raises(RuntimeError, match="identical to DATABASE_URL"):
        real_get_engine(for_test=True)


def test_force_test_db_succeeds_when_test_url_set(monkeypatch):
    """INV-TEST-DB-ISOLATION-001: test suite proceeds when TEST_DATABASE_URL is set."""
    from retrovue.infra import settings as settings_mod

    # Ensure TEST_DATABASE_URL is present
    monkeypatch.setattr(
        settings_mod.settings, "test_database_url", "sqlite:///:memory:"
    )

    real_get_engine = _get_real_get_engine()

    # Should succeed without raising
    engine = real_get_engine(for_test=True)
    assert engine is not None
