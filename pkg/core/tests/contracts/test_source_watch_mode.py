"""Contract tests for source watch mode.

Validates that the watch CLI delegates to SourceWatchService, that
debounce aggregates rapid events, that re-ingest uses the existing
SourceIngestService pipeline, and that graceful shutdown works.

Reference: docs/contracts/source_watch_mode.md
Invariants: INV-WATCH-DELEGATES-001, INV-WATCH-DEBOUNCE-001
"""

from __future__ import annotations

import threading

import pytest

from retrovue.workflows.source_watch import SourceWatchService


# ===========================================================================
# INV-WATCH-DELEGATES-001 — CLI delegates to workflow
# ===========================================================================


class TestWatchDelegation:
    """INV-WATCH-DELEGATES-001: watch CLI delegates all business logic to SourceWatchService."""

    @pytest.mark.contract
    def test_cli_imports_workflow(self):
        """The source watch CLI command imports from workflows.source_watch, not inline logic."""
        import inspect
        from retrovue.cli.commands.source import source_watch

        source_code = inspect.getsource(source_watch)
        # CLI must import and call run_watch from the workflow layer
        assert "run_watch" in source_code, (
            "CLI must delegate to run_watch from workflows.source_watch"
        )
        # CLI must not contain ingest logic directly
        assert "SourceIngestService" not in source_code, (
            "CLI must not import SourceIngestService directly — "
            "delegation happens via make_source_ingest_fn"
        )

    @pytest.mark.contract
    def test_make_source_ingest_fn_returns_callable(self):
        """make_source_ingest_fn returns a callable that wraps SourceIngestService."""
        from unittest.mock import MagicMock
        from retrovue.workflows.source_watch import make_source_ingest_fn

        mock_db = MagicMock()
        mock_source = MagicMock()
        fn = make_source_ingest_fn(mock_db, mock_source)
        assert callable(fn), "make_source_ingest_fn must return a callable"


# ===========================================================================
# INV-WATCH-DEBOUNCE-001 — debounce aggregation
# ===========================================================================


class TestWatchDebounce:
    """INV-WATCH-DEBOUNCE-001: file change events debounced before triggering re-ingest."""

    @pytest.mark.contract
    def test_debounce_sec_minimum_enforced(self):
        """Debounce interval must be >= 1 second."""
        with pytest.raises(ValueError, match="must be >= 1"):
            SourceWatchService(ingest_fn=lambda: None, debounce_sec=0.5)

    @pytest.mark.contract
    def test_debounce_sec_exactly_one_accepted(self):
        """debounce_sec=1 is the minimum valid value."""
        svc = SourceWatchService(ingest_fn=lambda: None, debounce_sec=1.0)
        svc.stop()

    @pytest.mark.contract
    def test_single_change_triggers_one_ingest(self):
        """A single file change triggers exactly one re-ingest after debounce."""
        call_count = 0
        event = threading.Event()

        def _ingest():
            nonlocal call_count
            call_count += 1
            event.set()

        svc = SourceWatchService(ingest_fn=_ingest, debounce_sec=1.0)
        try:
            svc.notify_change()
            assert event.wait(timeout=3.0), "Ingest should have been triggered"
            assert call_count == 1
        finally:
            svc.stop()

    @pytest.mark.contract
    def test_rapid_changes_aggregate_to_single_ingest(self):
        """Multiple rapid changes within debounce window trigger only one re-ingest."""
        call_count = 0
        event = threading.Event()

        def _ingest():
            nonlocal call_count
            call_count += 1
            event.set()

        svc = SourceWatchService(ingest_fn=_ingest, debounce_sec=1.0)
        try:
            # Rapid burst of 10 changes
            for _ in range(10):
                svc.notify_change()
            assert event.wait(timeout=3.0), "Ingest should have been triggered"
            # Allow a small window for any spurious extra calls
            threading.Event().wait(timeout=0.5)
            assert call_count == 1, (
                f"Expected exactly 1 ingest call, got {call_count}"
            )
        finally:
            svc.stop()

    @pytest.mark.contract
    def test_debounce_resets_on_new_change(self, contract_clock):
        """A new change within the debounce window resets the timer (delays ingest)."""
        call_count = 0
        ingest_event = threading.Event()

        def _ingest():
            nonlocal call_count
            call_count += 1
            ingest_event.set()

        # Use a short debounce for test speed
        svc = SourceWatchService(ingest_fn=_ingest, debounce_sec=1.0)
        try:
            svc.notify_change()
            # Wait less than debounce, then send another change
            threading.Event().wait(timeout=0.3)
            assert call_count == 0, "Ingest should not fire before debounce expires"
            svc.notify_change()  # Reset the timer
            # Now wait for debounce + margin
            assert ingest_event.wait(timeout=3.0), "Ingest should eventually fire"
            assert call_count == 1, "Only one ingest after timer reset"
        finally:
            svc.stop()


# ===========================================================================
# Re-ingest through existing SourceIngestService
# ===========================================================================


class TestWatchReingest:
    """Watch mode triggers re-ingest through the existing SourceIngestService pipeline."""

    @pytest.mark.contract
    def test_ingest_fn_called_on_debounce_expiry(self):
        """The ingest_fn callable is invoked when debounce timer expires."""
        results = []
        event = threading.Event()

        def _ingest():
            results.append("ingested")
            event.set()

        svc = SourceWatchService(ingest_fn=_ingest, debounce_sec=1.0)
        try:
            svc.notify_change()
            assert event.wait(timeout=3.0)
            assert results == ["ingested"]
        finally:
            svc.stop()

    @pytest.mark.contract
    def test_ingest_failure_does_not_crash_service(self):
        """Contract: ingest failure is logged and watch mode continues (error recovery)."""
        failure_count = 0
        success_event = threading.Event()
        calls = []

        def _flaky_ingest():
            nonlocal failure_count
            calls.append(1)
            if failure_count == 0:
                failure_count += 1
                raise RuntimeError("Simulated ingest failure")
            success_event.set()

        svc = SourceWatchService(ingest_fn=_flaky_ingest, debounce_sec=1.0)
        try:
            # First change — ingest will fail
            svc.notify_change()
            threading.Event().wait(timeout=2.0)
            # Service should still be running — send another change
            svc.notify_change()
            assert success_event.wait(timeout=3.0), (
                "Service should survive ingest failure and handle subsequent changes"
            )
        finally:
            svc.stop()


# ===========================================================================
# Graceful Shutdown
# ===========================================================================


class TestWatchGracefulShutdown:
    """Contract: graceful shutdown on stop() — discard pending re-ingest."""

    @pytest.mark.contract
    def test_stop_cancels_pending_ingest(self):
        """stop() cancels any pending debounce timer — no ingest fires after stop."""
        call_count = 0

        def _ingest():
            nonlocal call_count
            call_count += 1

        svc = SourceWatchService(ingest_fn=_ingest, debounce_sec=1.0)
        svc.notify_change()
        svc.stop()
        # Wait past what would have been the debounce window
        threading.Event().wait(timeout=2.0)
        assert call_count == 0, "No ingest should fire after stop()"

    @pytest.mark.contract
    def test_notify_after_stop_is_noop(self):
        """notify_change() after stop() does nothing."""
        call_count = 0

        def _ingest():
            nonlocal call_count
            call_count += 1

        svc = SourceWatchService(ingest_fn=_ingest, debounce_sec=1.0)
        svc.stop()
        svc.notify_change()
        threading.Event().wait(timeout=2.0)
        assert call_count == 0, "No ingest should fire after stop()"

    @pytest.mark.contract
    def test_double_stop_is_safe(self):
        """Calling stop() twice does not raise."""
        svc = SourceWatchService(ingest_fn=lambda: None, debounce_sec=1.0)
        svc.stop()
        svc.stop()  # Should not raise


# ===========================================================================
# run_watch integration shape
# ===========================================================================


class TestRunWatchShape:
    """Verify run_watch() function signature and basic wiring."""

    @pytest.mark.contract
    def test_run_watch_accepts_expected_args(self):
        """run_watch has the expected parameter signature."""
        import inspect
        from retrovue.workflows.source_watch import run_watch

        sig = inspect.signature(run_watch)
        params = set(sig.parameters.keys())
        assert "source_id" in params
        assert "source_name" in params
        assert "watch_paths" in params
        assert "ingest_fn" in params
        assert "debounce_sec" in params
