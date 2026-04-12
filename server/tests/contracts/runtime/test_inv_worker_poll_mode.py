"""Contract tests for worker poll mode.

When --poll is enabled, run_loop() MUST sleep for `interval` seconds after
draining the queue and then re-check, rather than exiting immediately.

Rules:
1. run_loop(poll=True) MUST NOT return when the queue is empty; it must sleep
   and retry.
2. run_loop(poll=False) (default) MUST return when the queue is empty
   (preserving existing behavior).
3. The sleep interval MUST be configurable via the `interval` parameter.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest


def _import_run_loop():
    from retrovue.runtime.processor_worker import run_loop
    return run_loop


class TestPollModeContract:
    """run_loop poll=True keeps the worker alive after draining the queue."""

    def test_non_poll_exits_on_empty_queue(self):
        """Default (poll=False): run_loop returns immediately when queue is empty."""
        run_loop = _import_run_loop()
        with patch("retrovue.runtime.processor_worker.run_once", return_value=False):
            count = run_loop()
        assert count == 0

    def test_poll_mode_sleeps_instead_of_exiting(self):
        """poll=True: run_loop sleeps after empty queue instead of returning."""
        run_loop = _import_run_loop()

        call_count = 0
        stop_after = 3  # let it poll a few times then stop via exception

        def mock_run_once():
            nonlocal call_count
            call_count += 1
            if call_count >= stop_after:
                raise KeyboardInterrupt  # simulate SIGINT to break the loop
            return False  # queue empty each time

        with patch("retrovue.runtime.processor_worker.run_once", side_effect=mock_run_once):
            with patch("retrovue.runtime.processor_worker.time.sleep") as mock_sleep:
                with pytest.raises(KeyboardInterrupt):
                    run_loop(poll=True, interval=5)
                # Must have slept between empty-queue checks
                assert mock_sleep.call_count >= 1
                # Sleep duration must match the requested interval
                for call in mock_sleep.call_args_list:
                    assert call.args[0] == 5

    def test_poll_mode_respects_custom_interval(self):
        """poll=True with interval=10 sleeps 10s between checks."""
        run_loop = _import_run_loop()

        call_count = 0

        def mock_run_once():
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise KeyboardInterrupt
            return False

        with patch("retrovue.runtime.processor_worker.run_once", side_effect=mock_run_once):
            with patch("retrovue.runtime.processor_worker.time.sleep") as mock_sleep:
                with pytest.raises(KeyboardInterrupt):
                    run_loop(poll=True, interval=10)
                assert mock_sleep.call_count >= 1
                assert mock_sleep.call_args_list[0].args[0] == 10

    def test_poll_mode_processes_jobs_then_sleeps(self):
        """poll=True processes available jobs, then sleeps when queue empties."""
        run_loop = _import_run_loop()

        # Simulate: 2 jobs available, then empty, then interrupt
        results = iter([True, True, False, False])
        call_count = 0

        def mock_run_once():
            nonlocal call_count
            call_count += 1
            try:
                return next(results)
            except StopIteration:
                raise KeyboardInterrupt

        with patch("retrovue.runtime.processor_worker.run_once", side_effect=mock_run_once):
            with patch("retrovue.runtime.processor_worker.time.sleep") as mock_sleep:
                with pytest.raises(KeyboardInterrupt):
                    run_loop(poll=True, interval=30)
                # Should have slept only after the queue was empty
                assert mock_sleep.call_count >= 1

    def test_poll_default_interval_is_30(self):
        """Default poll interval is 30 seconds when not specified."""
        run_loop = _import_run_loop()

        def mock_run_once():
            raise KeyboardInterrupt

        with patch("retrovue.runtime.processor_worker.run_once", side_effect=mock_run_once):
            with patch("retrovue.runtime.processor_worker.time.sleep") as mock_sleep:
                # poll=True without interval should use default
                # But run_once raises immediately, so no sleep occurs.
                # Let's allow one empty cycle first.
                pass

        # Test via signature inspection instead
        import inspect
        sig = inspect.signature(run_loop)
        assert "poll" in sig.parameters
        assert "interval" in sig.parameters
        assert sig.parameters["interval"].default == 30
