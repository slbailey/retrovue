"""
Pytest configuration and fixtures for contract tests.

Provides database session fixtures and other common test utilities
for contract-based testing.

Contract tests must not use time.sleep. Use contract_clock for deterministic
time advancement (advance_ms, pump_until).

Labels: All tests in tests/contracts/ are marked "contract" (run in CI).
Long-running tests should be marked "soak" (nightly only); add a fast
deterministic counterpart that validates the same invariant(s) via simulated time.
CI runs: pytest tests/contracts -m "contract and not soak"

Database: Some contract tests (e.g. test_processor_metadata_contract,
test_processor_execution_contract) use the real session() from infra.uow and
commit. That creates "Test Container" and "Test Source" rows in whatever
database DATABASE_URL points to. To avoid polluting your main DB, run contract
tests against a test database, e.g.:
  DATABASE_URL=postgresql+psycopg://user:pass@host/test_db pytest tests/contracts/
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from unittest.mock import MagicMock

import pytest
import structlog


# -----------------------------------------------------------------------------
# Deterministic clock for contract tests (no time.sleep)
# -----------------------------------------------------------------------------


class FakeAdvancingClock:
    """Deterministic clock for contract tests; advance_ms() controls time."""

    def __init__(self, start_ms: int = 0) -> None:
        self._ms = start_ms
        self._lock = threading.Lock()

    def now_utc(self) -> datetime:
        with self._lock:
            return datetime.fromtimestamp(self._ms / 1000.0, tz=timezone.utc)

    def now_utc_ms(self) -> int:
        with self._lock:
            return self._ms

    def advance(self, delta_ms: int) -> None:
        with self._lock:
            self._ms += delta_ms

    def advance_ms(self, n: int) -> None:
        """Alias for advance(n)."""
        self.advance(n)


@dataclass
class ContractClockFixture:
    """Fixture providing a fake clock and helpers. Do not use time.sleep in contract tests."""

    clock: FakeAdvancingClock

    def now_utc_ms(self) -> int:
        """Return current clock time in epoch milliseconds."""
        return self.clock.now_utc_ms()

    def advance_ms(self, n: int) -> None:
        """Advance the clock by n milliseconds (deterministic)."""
        self.clock.advance_ms(n)

    def pump_until(
        self,
        predicate: Callable[[], bool],
        max_ms: int,
        step_ms: int = 50,
    ) -> bool:
        """Advance the clock in steps and yield to other threads until predicate() is true or max_ms simulated time elapsed.

        Uses threading.Event.wait(timeout=0.01) to yield so background threads can run;
        does not use time.sleep.
        Returns True if predicate() became true, False if max_ms exceeded.
        """
        elapsed = 0
        event = threading.Event()
        while elapsed < max_ms:
            if predicate():
                return True
            self.clock.advance_ms(step_ms)
            elapsed += step_ms
            event.wait(timeout=0.01)
        return predicate()


def pytest_collection_modifyitems(items):
    """Add 'contract' marker to tests in tests/contracts/ only (CI default)."""
    contracts_dir = str(__import__("pathlib").Path(__file__).resolve().parent)
    for item in items:
        if str(item.fspath).startswith(contracts_dir):
            item.add_marker(pytest.mark.contract)


@pytest.fixture
def contract_clock() -> ContractClockFixture:
    """Provide a deterministic fake clock and advance_ms / pump_until helpers for contract tests."""
    clock = FakeAdvancingClock(start_ms=100_000_000_000)  # Start far in past for stability
    return ContractClockFixture(clock=clock)


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


@pytest.fixture
def suppress_structlog_stdout():
    """Suppress structlog debug output that contaminates CLI stdout capture.

    structlog's default PrintLogger writes to stdout, which corrupts JSON
    output captured by typer's CliRunner.  Re-configure structlog to route
    through stdlib logging (with level=WARNING) so debug/info lines do not
    leak into captured stdout.
    """
    logging.basicConfig(level=logging.WARNING, force=True)
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    yield
    structlog.reset_defaults()
