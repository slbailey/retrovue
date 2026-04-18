from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest

from retrovue.runtime.clock import SystemClock
from retrovue.runtime.playlist_builder_daemon import PlaylistBuilderDaemon
from retrovue.runtime.test_playout_endpoint import EphemeralTestSession


def test_playlist_builder_daemon_requires_injected_clock():
    clock = SystemClock()
    daemon = PlaylistBuilderDaemon(channel_id="test-ch", clock=clock)
    assert daemon._now_utc_ms() == clock.now_utc_ms()


def test_ephemeral_test_session_requires_injected_clock():
    clock = SystemClock()
    session = EphemeralTestSession(block_id="block-1", session_id="session-1", clock=clock)
    assert session._clock is clock


def test_playlist_builder_now_helper_has_no_wall_clock_fallback():
    source = inspect.getsource(PlaylistBuilderDaemon._now_utc_ms)
    assert "datetime.now" not in source
    assert "datetime.utcnow" not in source
    assert "time.time" not in source


def test_ephemeral_test_session_start_has_no_wall_clock_fallback():
    source = inspect.getsource(EphemeralTestSession.start)
    assert "datetime.now" not in source
    assert "datetime.utcnow" not in source
    assert "time.time" not in source


# ---------------------------------------------------------------------------
# Phase 7D: control-plane clock authority enforcement.
#
# Invariant: control-plane modules must consume wall-clock time only via
# the injected AuthoritativeClock. Direct datetime.now / datetime.utcnow /
# time.time calls in these modules are contract violations.
# ---------------------------------------------------------------------------

from retrovue.domain import enricher as _enricher_module
from retrovue.runtime import cun_queue as _cun_queue_module
from retrovue.runtime import cun_synthesis_worker as _cun_worker_module
from retrovue.runtime import program_director as _program_director_module
from retrovue.usecases import channel_manager_launch as _launch_module

_CONTROL_PLANE_MODULES = [
    _program_director_module,
    _launch_module,
    _enricher_module,
    _cun_queue_module,
    _cun_worker_module,
]

_FORBIDDEN_WALL_CLOCK_CALLS = ("datetime.now(", "datetime.utcnow(", "time.time(")


@pytest.mark.parametrize(
    "module", _CONTROL_PLANE_MODULES, ids=lambda m: m.__name__
)
def test_control_plane_module_has_no_direct_wall_clock(module):
    """Phase 7D: no direct wall-clock reads in control-plane modules.

    Every call site must route through an injected AuthoritativeClock.
    Regression guard: adding any of the forbidden patterns to these modules
    re-introduces hidden time authority and must fail this test.
    """
    source = inspect.getsource(module)
    offenders = [p for p in _FORBIDDEN_WALL_CLOCK_CALLS if p in source]
    assert not offenders, (
        f"{module.__name__} contains forbidden wall-clock call(s) {offenders}. "
        "Thread AuthoritativeClock through the call site instead."
    )


# ---------------------------------------------------------------------------
# Phase 7E: monotonic-time unification.
#
# Invariant: elapsed-time and pacing logic in these modules must read monotonic
# time only via the injected AuthoritativeClock. Direct time.monotonic,
# time.monotonic_ns, and time.perf_counter calls are contract violations.
# The clock module itself is the sole permitted caller of time.* (it IS the
# authority).
# ---------------------------------------------------------------------------

from retrovue.runtime import channel_stream as _channel_stream_module
from retrovue.runtime import consumption_adapters as _consumption_adapters_module
from retrovue.runtime import pace as _pace_module
from retrovue.runtime import block_plan_producer as _block_plan_producer_module
from retrovue.runtime.hls import segmenter as _hls_segmenter_module

_MONOTONIC_TARGET_MODULES = [
    _program_director_module,
    _channel_stream_module,
    _consumption_adapters_module,
    _pace_module,
    _hls_segmenter_module,
    _launch_module,
    _block_plan_producer_module,
]

_FORBIDDEN_MONOTONIC_CALLS = (
    ".monotonic(",
    ".monotonic_ns(",
    ".perf_counter(",
)
# Clock-instance attribute accesses that are allowed (they ARE the replacement).
_ALLOWED_MONOTONIC_PREFIXES = (
    "clock.monotonic",
    "_clock.monotonic",
    "embedded_clock.monotonic",
    "self.clock.monotonic",
)


def _has_forbidden_monotonic(source: str) -> list[str]:
    """Return any forbidden monotonic-style calls not prefixed by a clock attribute."""
    offenders: list[str] = []
    for pattern in _FORBIDDEN_MONOTONIC_CALLS:
        # Scan every occurrence of the suffix and check its immediate prefix.
        start = 0
        while True:
            idx = source.find(pattern, start)
            if idx == -1:
                break
            # Look backwards for the call's attribute chain.
            line_start = source.rfind("\n", 0, idx) + 1
            prefix = source[line_start:idx]
            # An allowed prefix ends with a clock attribute (e.g. "self.clock",
            # "self._clock", "self._embedded_clock", or a local bound to a clock).
            allowed = any(prefix.rstrip().endswith(tag.rsplit(".", 1)[0])
                          for tag in _ALLOWED_MONOTONIC_PREFIXES)
            if not allowed:
                offenders.append(f"{pattern} @ col {idx - line_start}")
            start = idx + len(pattern)
    return offenders


@pytest.mark.parametrize(
    "module", _MONOTONIC_TARGET_MODULES, ids=lambda m: m.__name__
)
def test_phase7e_module_has_no_direct_monotonic(module):
    """Phase 7E: no direct time.monotonic / time.perf_counter in these modules.

    Elapsed-time reads must flow through AuthoritativeClock.monotonic() /
    AuthoritativeClock.monotonic_ns(). The clock module itself (runtime/clock.py)
    is the sole permitted caller of time.* primitives.
    """
    source = inspect.getsource(module)
    offenders = _has_forbidden_monotonic(source)
    assert not offenders, (
        f"{module.__name__} contains forbidden monotonic call(s): {offenders}. "
        "Use clock.monotonic() / clock.monotonic_ns() instead."
    )


def test_system_clock_monotonic_preserves_time_monotonic_semantics():
    """Phase 7E semantic-preservation: SystemClock.monotonic() must return the
    same underlying reading as time.monotonic() (the default monotonic_fn).

    This guarantees that replacing time.monotonic() with clock.monotonic() in
    a SystemClock-configured process does not alter timing behavior.
    """
    import time
    clock = SystemClock()
    a = time.monotonic()
    b = clock.monotonic()
    c = time.monotonic()
    # Clock reading must fall between two direct readings taken around it.
    assert a <= b <= c, (
        f"SystemClock.monotonic() drifted outside the bracketing time.monotonic() "
        f"readings: a={a!r} b={b!r} c={c!r}"
    )


def test_system_clock_monotonic_ns_preserves_time_monotonic_ns_semantics():
    """Phase 7E: SystemClock.monotonic_ns() preserves full nanosecond precision
    (delegates directly to time.monotonic_ns(), not int(monotonic() * 1e9))."""
    import time
    clock = SystemClock()
    a = time.monotonic_ns()
    b = clock.monotonic_ns()
    c = time.monotonic_ns()
    assert a <= b <= c
    # Type must be int (ns resolution preserved, no float rounding).
    assert isinstance(b, int)


def test_system_clock_ns_is_not_float_multiplication():
    """Regression guard: SystemClock.monotonic_ns() must not go through
    int(self.monotonic() * 1e9). That path silently loses low-order bits on
    long uptimes and would reintroduce drift.
    """
    source = inspect.getsource(SystemClock.monotonic_ns)
    assert "time.monotonic_ns" in source, (
        "SystemClock.monotonic_ns() must delegate to time.monotonic_ns() "
        "to preserve full nanosecond precision."
    )
    assert "* 1_000_000_000" not in source and "* 1e9" not in source, (
        "SystemClock.monotonic_ns() must not compute via float multiplication — "
        "that loses precision for typical monotonic-clock magnitudes."
    )
