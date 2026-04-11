"""
Shared test fixtures for runtime component tests.
"""

from datetime import UTC, datetime, timedelta

import pytest

from retrovue.runtime.clock import MasterClock, TimePrecision


@pytest.fixture
def master_clock():
    """Provide a MasterClock instance for testing."""
    return MasterClock()


@pytest.fixture
def master_clock_second_precision():
    """Provide a MasterClock instance with second precision for testing."""
    return MasterClock(TimePrecision.SECOND)


@pytest.fixture
def master_clock_millisecond_precision():
    """Provide a MasterClock instance with millisecond precision for testing."""
    return MasterClock(TimePrecision.MILLISECOND)


@pytest.fixture
def master_clock_microsecond_precision():
    """Provide a MasterClock instance with microsecond precision for testing."""
    return MasterClock(TimePrecision.MICROSECOND)


@pytest.fixture
def sample_utc_time():
    """Provide a sample UTC datetime for testing."""
    return datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def sample_naive_time():
    """Provide a sample naive datetime for testing."""
    return datetime(2024, 1, 15, 12, 0, 0)


@pytest.fixture
def future_time():
    """Provide a future datetime for testing."""
    return datetime.now(UTC) + timedelta(hours=1)


@pytest.fixture
def past_time():
    """Provide a past datetime for testing."""
    return datetime.now(UTC) - timedelta(hours=1)
