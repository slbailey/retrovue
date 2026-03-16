"""Shared pytest configuration for tests/contracts/ tree."""

import pytest


def pytest_collection_modifyitems(items):
    """Add 'contract' marker to every test in tests/contracts/."""
    for item in items:
        item.add_marker(pytest.mark.contract)
