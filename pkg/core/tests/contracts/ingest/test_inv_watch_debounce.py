"""
INV-WATCH-DEBOUNCE-001 — File changes debounced before re-ingest.

Contract requirements:
- File change events MUST be aggregated over a debounce window before triggering.
- The debounce timer MUST reset on each new event within the window.
- Debounce interval MUST be >= 1 second.
- Ingest failure during debounce cycle MUST NOT crash watch mode.

Tests use accelerated time (short debounce) for determinism.
"""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest


class TestInvWatchDebounce001:
    """Contract tests for INV-WATCH-DEBOUNCE-001."""

    def _make_service(self, debounce_sec: float = 1.0):
        """Create a SourceWatchService with a mock ingest callable."""
        from retrovue.workflows.source_watch import SourceWatchService

        mock_ingest = MagicMock()
        service = SourceWatchService(
            ingest_fn=mock_ingest,
            debounce_sec=debounce_sec,
        )
        return service, mock_ingest

    def test_twdb_001_burst_debounced(self):
        """10 file events within a burst produce exactly 1 ingest call."""
        service, mock_ingest = self._make_service(debounce_sec=1.0)

        # Simulate 10 rapid file events
        for _ in range(10):
            service.notify_change()

        # Wait for debounce to expire
        time.sleep(1.5)
        service.stop()

        assert mock_ingest.call_count == 1, (
            f"Expected 1 ingest call after burst, got {mock_ingest.call_count}"
        )

    def test_twdb_002_timer_reset(self):
        """Two events within debounce window reset the timer; 1 ingest call total."""
        service, mock_ingest = self._make_service(debounce_sec=1.0)

        service.notify_change()
        time.sleep(0.5)  # < debounce
        service.notify_change()  # resets timer

        # Wait for debounce from last event
        time.sleep(1.5)
        service.stop()

        assert mock_ingest.call_count == 1, (
            f"Expected 1 ingest call (timer reset), got {mock_ingest.call_count}"
        )

    def test_twdb_003_separate_triggers(self):
        """Two events separated by > debounce interval produce 2 ingest calls."""
        service, mock_ingest = self._make_service(debounce_sec=1.0)

        service.notify_change()
        time.sleep(1.5)  # > debounce, first ingest fires

        service.notify_change()
        time.sleep(1.5)  # > debounce, second ingest fires

        service.stop()

        assert mock_ingest.call_count == 2, (
            f"Expected 2 ingest calls (separate triggers), got {mock_ingest.call_count}"
        )

    def test_twdb_004_minimum_debounce_enforced(self):
        """Debounce interval < 1 second is rejected at construction."""
        from retrovue.workflows.source_watch import SourceWatchService

        with pytest.raises(ValueError, match="[Dd]ebounce"):
            SourceWatchService(
                ingest_fn=MagicMock(),
                debounce_sec=0.5,
            )

    def test_twdb_005_ingest_failure_recovers(self):
        """Ingest failure does not crash watch mode; returns to watching."""
        from retrovue.workflows.source_watch import SourceWatchService

        call_count = 0
        results = []

        def flaky_ingest():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Simulated ingest failure")
            results.append("ok")

        service = SourceWatchService(
            ingest_fn=flaky_ingest,
            debounce_sec=1.0,
        )

        # First trigger — will fail
        service.notify_change()
        time.sleep(1.5)

        # Second trigger — should succeed (watch mode recovered)
        service.notify_change()
        time.sleep(1.5)

        service.stop()

        assert call_count == 2, (
            f"Expected 2 ingest attempts, got {call_count}"
        )
        assert results == ["ok"], (
            "Second ingest should have succeeded after failure recovery"
        )
