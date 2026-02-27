"""
Contract tests: INV-SWITCH-BOUNDARY-TIMING.

Core declares the authoritative switch boundary; the protocol (SwitchToLiveRequest)
must include target_boundary_time_ms and issued_at_time_ms so AIR can execute
the switch within one frame of the declared boundary.

Tests are deterministic (no wall-clock sleep). See also AIR:
pkg/air/tests/contracts/DeadlineSwitchTests.cpp for execution-side verification.
"""

from __future__ import annotations

import pytest


def test_inv_switch_boundary_timing_protocol_includes_boundary_fields():
    """SwitchToLiveRequest must include target_boundary_time_ms and issued_at_time_ms (Core declares boundary)."""
    from retrovue.runtime.playout_session import playout_pb2

    req = playout_pb2.SwitchToLiveRequest(
        channel_id=1,
        target_boundary_time_ms=100_000,
        issued_at_time_ms=99_500,
    )
    assert req.target_boundary_time_ms == 100_000
    assert req.issued_at_time_ms == 99_500
    # Boundary is declared; AIR contract is to complete switch within boundary + one frame
    assert req.target_boundary_time_ms >= req.issued_at_time_ms
