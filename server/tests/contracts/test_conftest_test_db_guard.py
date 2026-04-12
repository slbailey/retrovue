"""Contract test: _force_test_db fixture rejects missing TEST_DATABASE_URL.

Tests must never silently run against the production DATABASE_URL.
If TEST_DATABASE_URL is not set, the fixture must raise RuntimeError.

This test verifies the guard logic by inspecting the conftest source
and testing the settings dependency directly.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from retrovue.infra.settings import settings


# ---------------------------------------------------------------------------
# Structural test: conftest contains the guard
# ---------------------------------------------------------------------------

def test_conftest_contains_test_db_guard():
    """The _force_test_db fixture must contain a RuntimeError guard
    that fires when TEST_DATABASE_URL is not set.
    """
    conftest_path = Path(__file__).resolve().parents[1] / "conftest.py"
    source = conftest_path.read_text()

    # Parse the AST and find the _force_test_db function
    tree = ast.parse(source)
    func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_force_test_db":
            func = node
            break

    assert func is not None, "conftest.py must define _force_test_db fixture"

    # The function body must contain a raise RuntimeError
    func_source = ast.get_source_segment(source, func)
    assert "RuntimeError" in func_source, (
        "_force_test_db must raise RuntimeError when TEST_DATABASE_URL is missing"
    )
    assert "test_database_url" in func_source, (
        "_force_test_db must check settings.test_database_url"
    )

    # The old fallback pattern must NOT be present
    assert "use_test = bool(" not in func_source, (
        "_force_test_db must not silently fall back to DATABASE_URL "
        "(old pattern: use_test = bool(settings.test_database_url))"
    )


# ---------------------------------------------------------------------------
# Behavioral test: settings.test_database_url is currently set
# ---------------------------------------------------------------------------

def test_test_database_url_is_configured():
    """TEST_DATABASE_URL must be set in the test environment.
    If this test fails, the test suite would refuse to start.
    """
    assert settings.test_database_url, (
        "TEST_DATABASE_URL is not set in the current environment. "
        "All tests depend on this being configured."
    )
