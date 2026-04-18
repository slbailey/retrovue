"""
Phase 8 Step 4 — post-migration: the linger-expired callback slot on
ChannelManager is gone.

Prior contract (pre-Step-4): ChannelManager required an
``on_linger_expired`` callback at construction time; this preserved
INV-LIFECYCLE-PD-SOLE-TEARDOWN-001 in the presence of the callback-
inversion path. Phase 8 Step 4 removed the inversion: the linger timer
lives on ProgramDirector, which fires its own expiry handler directly.

This file keeps a single residual check: ChannelManager must NOT accept
an ``on_linger_expired`` kwarg any longer. The teardown authority
invariant is now enforced by PD owning the timer (see
``tests/runtime/test_phase8_step4_linger_ownership.py``).
"""

import pytest
from unittest.mock import MagicMock

from retrovue.runtime.channel_manager import ChannelManager
from retrovue.config.testing import TEST_RESOLVED_CONFIG


pytestmark = pytest.mark.contract


@pytest.fixture
def minimal_deps():
    clock = MagicMock()
    clock.now_utc.return_value = MagicMock()
    return {
        "channel_id": "test-step4-no-callback",
        "clock": clock,
        "execution_reader": MagicMock(),
        "program_director": MagicMock(),
        "resolved_config": TEST_RESOLVED_CONFIG,
    }


def test_channel_manager_rejects_on_linger_expired_kwarg(minimal_deps):
    """Phase 8 Step 4: passing ``on_linger_expired=`` must raise TypeError —
    the kwarg has been removed from the constructor signature."""
    with pytest.raises(TypeError):
        ChannelManager(**minimal_deps, on_linger_expired=lambda: None)


def test_channel_manager_constructs_without_any_linger_callback(minimal_deps):
    """Baseline: construction succeeds without a linger-expired callback.
    Linger policy is PD's job now; CM is a pure command executor."""
    cm = ChannelManager(**minimal_deps)
    assert cm is not None
    assert not hasattr(cm, "on_linger_expired")
