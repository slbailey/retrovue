from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime, timedelta

import pytest

from retrovue.runtime.clock import MasterClock


def test_mc_001_timezone_awareness():
    """MC-001: now_* and conversion helpers must return timezone-aware datetimes."""
    clock = MasterClock()

    utc_now = clock.now_utc()
    local_now = clock.now_local()
    converted_local = clock.to_local(utc_now)
    converted_utc = clock.to_utc(local_now)

    for ts in (utc_now, local_now, converted_local, converted_utc):
        assert ts.tzinfo is not None
        assert ts.tzinfo.utcoffset(ts) is not None


def test_mc_002_monotonic_non_decreasing():
    """MC-002: Sequential now_utc() calls must be monotonic (non-decreasing)."""
    clock = MasterClock()
    samples = [clock.now_utc() for _ in range(5)]
    for earlier, later in zip(samples, samples[1:]):
        assert later >= earlier


def test_mc_003_seconds_since_future_clamps_to_zero():
    """MC-003: seconds_since() clamps future timestamps to zero."""
    clock = MasterClock()
    now = clock.now_utc()
    past = now - timedelta(seconds=2)
    future = now + timedelta(seconds=10)

    assert clock.seconds_since(past) >= 0.0
    assert clock.seconds_since(future) == pytest.approx(0.0)


def test_mc_004_naive_datetime_rejected():
    """MC-004: Naive datetimes must raise ValueError."""
    clock = MasterClock()
    naive = datetime.now()

    with pytest.raises(ValueError):
        clock.seconds_since(naive)
    with pytest.raises(ValueError):
        clock.to_local(naive.replace(tzinfo=None))
    with pytest.raises(ValueError):
        clock.to_utc(naive.replace(tzinfo=None))


def test_mc_005_round_trip_conversion_precision():
    """MC-005: Round-trip UTC -> local -> UTC stays within microseconds."""
    clock = MasterClock()
    utc_now = clock.now_utc()
    for tz in ("America/New_York", "Europe/London", "Asia/Tokyo", None):
        local = clock.to_local(utc_now, tz)
        round_trip = clock.to_utc(local)
        delta = abs((round_trip - utc_now).total_seconds())
        assert delta <= 1e-3  # within 1 millisecond


def test_mc_006_no_eventing_state():
    """MC-006: MasterClock exposes no eventing/ticking attributes."""
    clock = MasterClock()
    prohibited_attrs = ["_subscribers", "_step", "_tick", "_thread", "advance", "step"]
    for attr in prohibited_attrs:
        assert not hasattr(clock, attr)


def test_mc_007_single_source_of_truth(monkeypatch):
    """MC-007: Implementation must not rely on datetime.utcnow()."""
    import retrovue.tests.runtime.test_masterclock_validation as module

    original_datetime = module.datetime

    class PatchedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return original_datetime.now(tz)

        @classmethod
        def utcnow(cls):
            raise AssertionError("utcnow() should not be called")

    monkeypatch.setattr(module, "datetime", PatchedDateTime)

    clock = MasterClock()
    clock.now_utc()
    clock.now_local()

    source = inspect.getsource(MasterClock)
    tree = ast.parse(source)

    class UtcnowFinder(ast.NodeVisitor):
        def __init__(self) -> None:
            self.found = False

        def visit_Attribute(self, node: ast.Attribute) -> None:
            if node.attr == "utcnow":
                self.found = True
            self.generic_visit(node)

    finder = UtcnowFinder()
    finder.visit(tree)
    assert not finder.found, "MasterClock implementation should not reference datetime.utcnow()"

