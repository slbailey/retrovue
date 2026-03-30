"""
Contract Tests: INV-HLS-READINESS-001

The HLS manifest endpoint MUST NOT serve a playlist until the SegmentRing
has produced a valid, playable playlist window.

SegmentRing owns the readiness signal and the definition of "playable
window."  The readiness signal is set when the ring first satisfies
the playable-window criteria and remains set for the lifetime of the
activation.

These tests verify the readiness signal lifecycle on SegmentRing directly.
They do NOT hardcode a segment count — the ring defines what "playable"
means via its own configuration.

Canonical contract:
    docs/contracts/invariants/core/runtime/INV-HLS-READINESS-001.md
"""

from __future__ import annotations

import pytest

from retrovue.runtime.hls.segment_ring import SegmentRing, LiveSegment

from .conftest import make_ring


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_segment(index: int, channel_id: str = "test-ch") -> LiveSegment:
    """Create a minimal valid LiveSegment at the given index."""
    return LiveSegment(
        channel_id=channel_id,
        index=index,
        data=b"\x47" * 188 * 10,
        byte_count=188 * 10,
        duration_ms=6000,
        wall_clock_start_utc_ms=1_700_000_000_000 + index * 6000,
        discontinuity=(index == 0),
    )


def _push_n(ring: SegmentRing, n: int, start_index: int = 0) -> None:
    """Push *n* segments to the ring starting at *start_index*."""
    for i in range(n):
        ring.push(_make_segment(start_index + i))


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------

@pytest.mark.contract
class TestInvHlsReadiness001:
    """INV-HLS-READINESS-001: SegmentRing readiness signal lifecycle."""

    # -- readiness signal exists ------------------------------------------

    def test_ring_exposes_ready_event(self):
        """SegmentRing MUST expose a ``ready`` attribute that is an
        event-compatible object with ``.is_set()`` and ``.set()``
        semantics.
        """
        ring = make_ring()
        # The readiness signal must exist as an attribute.
        ready = ring.ready
        # Must support is_set() (threading.Event / asyncio.Event compatible)
        assert hasattr(ready, "is_set"), (
            "ring.ready must expose is_set() for synchronous readiness checks"
        )

    # -- below playable window → not ready --------------------------------

    def test_below_threshold_not_ready(self):
        """A ring that has not yet reached its playable-window threshold
        MUST have readiness unset.
        """
        ring = make_ring()
        assert not ring.ready.is_set(), (
            "Empty ring must not be ready"
        )

        # Push one segment — still below any reasonable playable window.
        ring.push(_make_segment(0))
        assert not ring.ready.is_set(), (
            "A single segment is not a playable window"
        )

    # -- playable window reached → readiness signal set -------------------

    def test_threshold_reached_sets_signal(self):
        """When the ring crosses the playable-window threshold via push(),
        the readiness signal MUST be set.
        """
        ring = make_ring()

        # The ring defines what "playable" means.  Push segments one at a
        # time until readiness fires.  We don't assume a fixed count —
        # we just verify that it eventually fires and that it was NOT set
        # before the final push.
        max_segments = ring.capacity  # upper bound — must fire before full
        was_ready_before_last = False
        for i in range(max_segments):
            ring.push(_make_segment(i))
            if ring.ready.is_set():
                # Readiness achieved at segment i.  Verify it was NOT set
                # on the previous iteration (otherwise the threshold is 0
                # or 1, which is not a playable window).
                assert i > 0, (
                    "Readiness must not fire on the very first segment — "
                    "a single segment is not a playable window"
                )
                break
        else:
            pytest.fail(
                f"Readiness never set after pushing {max_segments} segments"
            )

    # -- readiness persists -----------------------------------------------

    def test_readiness_persists(self):
        """Once readiness is achieved, additional pushes MUST NOT unset it.

        The signal remains set for the lifetime of the activation.
        """
        ring = make_ring()

        # Fill to capacity to guarantee readiness.
        _push_n(ring, ring.capacity)
        assert ring.ready.is_set(), (
            "Ring at capacity must be ready"
        )

        # Push more (causes eviction) — readiness must persist.
        for i in range(5):
            ring.push(_make_segment(ring.capacity + i))
            assert ring.ready.is_set(), (
                f"Readiness must persist after push {i + 1} beyond capacity"
            )

    # -- reset on clear ---------------------------------------------------

    def test_clear_resets_readiness(self):
        """ring.clear() MUST reset the readiness signal so the next
        activation starts unready.
        """
        ring = make_ring()

        # Achieve readiness.
        _push_n(ring, ring.capacity)
        assert ring.ready.is_set()

        # Clear — simulates teardown.
        ring.clear()

        assert not ring.ready.is_set(), (
            "After clear(), readiness must be reset"
        )
        assert ring.count() == 0

    # -- warm channel: no await overhead ----------------------------------

    def test_warm_channel_no_await(self):
        """When readiness is already set, checking it MUST be a
        synchronous O(1) operation — no polling, no sleeping.

        This verifies that ``ring.ready.is_set()`` returns True
        immediately after the threshold has been crossed.
        """
        ring = make_ring()

        # Achieve readiness.
        _push_n(ring, ring.capacity)

        # is_set() must return True synchronously — if this call
        # blocked or raised, the warm path is broken.
        assert ring.ready.is_set() is True

    # -- fresh ring after clear can re-achieve readiness ------------------

    def test_re_readiness_after_clear(self):
        """After clear() and fresh pushes, readiness MUST fire again
        when the threshold is re-crossed.
        """
        ring = make_ring()

        # First activation: achieve readiness.
        _push_n(ring, ring.capacity)
        assert ring.ready.is_set()

        # Teardown.
        ring.clear()
        assert not ring.ready.is_set()

        # Second activation: push enough to cross threshold again.
        _push_n(ring, ring.capacity, start_index=ring.capacity)
        assert ring.ready.is_set(), (
            "Readiness must be achievable again after clear()"
        )
