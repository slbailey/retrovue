"""
INV-NO-GHOST-METHODS-001 + INV-LIFECYCLE-PD-SOLE-TEARDOWN-001

Contract: ChannelManager must be constructed WITH on_linger_expired callback.
Construction without a callback is forbidden — the callback is how PD maintains
sole teardown authority (INV-LIFECYCLE-PD-SOLE-TEARDOWN-001).

This test ensures the error is raised eagerly at construction time, not lazily
when linger fires, so misuse is caught immediately.
"""

import pytest
from unittest.mock import MagicMock

from retrovue.runtime.channel_manager import ChannelManager
from tests.contracts.runtime.test_channel_manager_clock_authority import TEST_RESOLVED_CONFIG


pytestmark = pytest.mark.contract


@pytest.fixture
def minimal_deps():
    clock = MagicMock()
    clock.now_utc.return_value = MagicMock()
    return {
        "channel_id": "test-callback-required",
        "clock": clock,
        "schedule_service": MagicMock(),
        "program_director": MagicMock(),
        "resolved_config": TEST_RESOLVED_CONFIG,
    }


def test_channel_manager_requires_on_linger_expired_callback(minimal_deps):
    """
    INV-LIFECYCLE-PD-SOLE-TEARDOWN-001: ChannelManager must be constructed with
    on_linger_expired callback. Omitting it violates the teardown authority boundary.
    """
    with pytest.raises((AssertionError, TypeError, ValueError)):
        ChannelManager(**minimal_deps)  # no on_linger_expired


def test_channel_manager_with_callback_constructs_ok(minimal_deps):
    """Baseline: providing the callback allows construction."""
    cm = ChannelManager(**minimal_deps, on_linger_expired=lambda: None)
    assert cm is not None
