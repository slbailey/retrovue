"""
INV-HTTP-UPSTREAM-SPIKE-001

UPSTREAM_LOOP WARNING fires only when the data-path work (recv+put) is slow.
OS scheduling / GC jitter that inflates select() wait time MUST NOT produce a
WARNING — it is absorbed by socket buffers and is not actionable.

Root cause of spurious warnings:
    A Python thread blocked in select() for up to UPSTREAM_POLL_TIMEOUT_S (50ms)
    can be preempted by the OS scheduler or GC for an additional 100-150ms.
    The old logic compared loop_duration_ms against the threshold, so scheduling
    jitter alone caused WARNING spam even though the actual data path was fast.

Fix:
    _classify_upstream_spike() classifies spikes by data-path work (recv+put),
    not by total loop duration.  Only "work_spike" produces a WARNING.
    "scheduling_jitter" (select-dominated) is downgraded to DEBUG.

Tests:
    test_scheduling_jitter_is_not_a_work_spike       [required]
        Invariant proof: select-dominated spike → "scheduling_jitter", not "work_spike".
        Fails before fix (function missing).  Passes after.

    test_slow_recv_is_a_work_spike                   [required]
        recv-dominated spike → "work_spike".

    test_fast_iteration_is_no_spike                  [required]
        Below-threshold → "no_spike".

    test_combined_recv_put_exceeding_threshold        [required]
        recv+put combined > threshold → "work_spike" even if select was also slow.
"""

from __future__ import annotations

import pytest

from retrovue.runtime.channel_stream import _classify_upstream_spike

_THRESHOLD_MS = 150.0


def test_scheduling_jitter_is_not_a_work_spike():
    """
    INV-HTTP-UPSTREAM-SPIKE-001  [required]

    A spike where select() dominates (OS scheduling / GC pause) but recv+put
    are fast MUST be classified as "scheduling_jitter", not "work_spike".

    Reproduces the exact pattern from production warnings:
        loop=175ms  select=165ms  recv=10ms  put=0ms
        loop=194ms  select=194ms  recv=0ms   put=0ms
    """
    cases = [
        # (duration_ms, select_ms, recv_ms, put_ms)
        (175.06, 164.78, 10.26, 0.02),
        (152.98, 129.64, 23.32, 0.03),
        (158.10, 147.42, 10.66, 0.01),
        (172.00, 158.41, 13.59, 0.01),
        (194.15, 193.87,  0.27, 0.01),
        (160.69, 154.88,  5.81, 0.01),
    ]
    for duration_ms, select_ms, recv_ms, put_ms in cases:
        result = _classify_upstream_spike(
            duration_ms=duration_ms,
            select_ms=select_ms,
            recv_ms=recv_ms,
            put_ms=put_ms,
            threshold_ms=_THRESHOLD_MS,
        )
        assert result == "scheduling_jitter", (
            f"Expected 'scheduling_jitter' for select-dominated spike "
            f"(duration={duration_ms}ms select={select_ms}ms recv={recv_ms}ms put={put_ms}ms), "
            f"got {result!r}.  INV-HTTP-UPSTREAM-SPIKE-001 violated."
        )


def test_slow_recv_is_a_work_spike():
    """recv-dominated spike MUST be classified as 'work_spike'."""
    result = _classify_upstream_spike(
        duration_ms=200.0,
        select_ms=10.0,
        recv_ms=185.0,
        put_ms=5.0,
        threshold_ms=_THRESHOLD_MS,
    )
    assert result == "work_spike"


def test_slow_put_is_a_work_spike():
    """put-dominated spike (ring buffer contention) MUST be classified as 'work_spike'."""
    result = _classify_upstream_spike(
        duration_ms=200.0,
        select_ms=5.0,
        recv_ms=5.0,
        put_ms=190.0,
        threshold_ms=_THRESHOLD_MS,
    )
    assert result == "work_spike"


def test_fast_iteration_is_no_spike():
    """Below-threshold iterations MUST be 'no_spike'."""
    result = _classify_upstream_spike(
        duration_ms=45.0,
        select_ms=44.0,
        recv_ms=1.0,
        put_ms=0.0,
        threshold_ms=_THRESHOLD_MS,
    )
    assert result == "no_spike"


def test_combined_recv_put_exceeding_threshold_is_work_spike():
    """recv+put combined exceeding threshold MUST be 'work_spike' even if select is also slow."""
    result = _classify_upstream_spike(
        duration_ms=400.0,
        select_ms=200.0,
        recv_ms=100.0,
        put_ms=100.0,
        threshold_ms=_THRESHOLD_MS,
    )
    assert result == "work_spike"


def test_work_just_below_threshold_is_scheduling_jitter():
    """recv+put just below threshold but total > threshold → 'scheduling_jitter'."""
    result = _classify_upstream_spike(
        duration_ms=300.0,
        select_ms=151.0,
        recv_ms=74.0,
        put_ms=75.0,
        threshold_ms=_THRESHOLD_MS,
    )
    assert result == "scheduling_jitter"
