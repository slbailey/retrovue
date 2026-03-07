"""
Contract test for INV-TEARDOWN-AIR-REAP-001.

Invariant:
    _finalize_teardown MUST call producer.stop() before dropping the
    reference, regardless of whether teardown completed gracefully or
    timed out.  Failure to do so orphans the AIR subprocess as a zombie.
"""

from unittest.mock import MagicMock, patch

import pytest

from retrovue.runtime.channel_manager import ChannelManager
from retrovue.runtime.producer.base import ProducerStatus


def _make_manager_with_mock_producer(*, teardown_completed: bool) -> tuple:
    """Build a ChannelManager with a mock producer in teardown state."""
    manager = ChannelManager.__new__(ChannelManager)

    # Minimal state to make _finalize_teardown work
    manager.channel_id = "test-ch"
    manager.runtime_state = MagicMock()
    manager._teardown_started_station = 1000.0
    manager._teardown_reason = "viewer_inactive"
    manager._logger = MagicMock()

    producer = MagicMock()
    producer.stop = MagicMock(return_value=True)
    if teardown_completed:
        producer.status = ProducerStatus.STOPPED
    else:
        producer.status = ProducerStatus.STOPPING
    manager.active_producer = producer

    # _station_now stub
    manager._station_now = lambda: 1005.0

    return manager, producer


class TestInvTeardownAirReap001:
    """INV-TEARDOWN-AIR-REAP-001: producer.stop() MUST be called before
    dropping the producer reference in _finalize_teardown."""

    def test_stop_called_on_graceful_completion(self):
        """TREAP-001: Graceful teardown (completed=True) still calls stop()."""
        manager, producer = _make_manager_with_mock_producer(teardown_completed=True)

        manager._finalize_teardown(completed=True)

        producer.stop.assert_called_once()
        assert manager.active_producer is None

    def test_stop_called_on_timeout(self):
        """TREAP-002: Timeout teardown (completed=False) calls stop()."""
        manager, producer = _make_manager_with_mock_producer(teardown_completed=False)

        manager._finalize_teardown(completed=False)

        producer.stop.assert_called_once()
        assert manager.active_producer is None

    def test_no_producer_is_safe(self):
        """TREAP-003: _finalize_teardown with no producer does not crash."""
        manager, _ = _make_manager_with_mock_producer(teardown_completed=True)
        manager.active_producer = None

        manager._finalize_teardown(completed=True)

        assert manager.active_producer is None
