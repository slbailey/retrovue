"""
Pytest configuration and fixtures for contract tests.

Provides database session fixtures and other common test utilities
for contract-based testing.
"""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def db_session():
    """
    Mock database session fixture for contract tests.
    
    Provides a mock database session that can be used to verify
    database operations without requiring a real database connection.
    """
    mock_session = MagicMock()
    mock_session.add = MagicMock()
    mock_session.commit = MagicMock()
    mock_session.rollback = MagicMock()
    mock_session.query = MagicMock()
    mock_session.flush = MagicMock()
    
    return mock_session


@pytest.fixture
def cli_runner():
    """
    CLI runner fixture for contract tests.
    
    Provides a Typer CliRunner instance for testing CLI commands.
    """
    from typer.testing import CliRunner
    return CliRunner()
