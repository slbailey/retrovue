"""Contract tests for INV-DAEMON-FRONTIER-ACTUAL-001.

PlaylistBuilderDaemon._farthest_end_utc_ms MUST reflect the actual playlog
plan frontier in the database at the start of each evaluate_once() cycle.
When PlaylistEvent rows are deleted, the daemon MUST detect the regression
and re-fill the gap on the next tick.

Rules:
1. evaluate_once() MUST assign _farthest_end_utc_ms = frontier_ms (direct,
   not monotonic max).
2. After PlaylistEvent row deletion mid-window, the next evaluate_once()
   cycle MUST detect reduced depth and trigger _extend_to_target().
"""

from unittest.mock import MagicMock, patch

import pytest
from retrovue.runtime.clock import SystemClock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_daemon(min_hours: int = 2):
    from retrovue.runtime.playlist_builder_daemon import PlaylistBuilderDaemon
    return PlaylistBuilderDaemon(
        channel_id="test-ch",
        clock=SystemClock(),
        min_hours=min_hours,
        programming_day_start_hour=6,
        channel_tz="UTC",
    )


class _FakeSession:
    """Minimal mock that quacks like a SQLAlchemy Session."""

    def query(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return None

    def scalar(self):
        return 0

    def count(self):
        return 0

    def delete(self):
        return 0

    def add(self, obj):
        pass

    def merge(self, obj):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class _SessionFactory:
    """Context manager that returns a FakeSession."""

    def __init__(self, session=None):
        self._session = session or _FakeSession()

    def __call__(self):
        session = self._session

        class _Ctx:
            def __enter__(self_ctx):
                return session

            def __exit__(self_ctx, *args):
                pass

        return _Ctx()


# ---------------------------------------------------------------------------
# FRONTIER-ACTUAL-001: After deletion, evaluate_once() detects reduced frontier
# ---------------------------------------------------------------------------

class TestFrontierActual001:
    """After PlaylistEvent rows are deleted (frontier regresses), the next
    evaluate_once() cycle MUST detect reduced depth and trigger extension."""

    def test_deleted_rows_trigger_extension(self):
        """When _get_frontier_utc_ms returns a value LOWER than the previously
        cached _farthest_end_utc_ms, evaluate_once() MUST detect the reduced
        depth and call _extend_to_target().

        BUG (before fix): monotonic max keeps _farthest_end_utc_ms at old high
        value, depth looks healthy, extension is skipped.
        """
        daemon = _make_daemon(min_hours=2)
        now_ms = 1_000_000_000_000  # some fixed now

        # Simulate: daemon previously saw frontier at now + 4h (well beyond 2h target)
        daemon._farthest_end_utc_ms = now_ms + 4 * 3_600_000

        # Now rows were deleted — actual DB frontier is only now + 30min
        regressed_frontier_ms = now_ms + 30 * 60_000

        extend_called = False
        original_extend = None

        def _tracking_extend(now, target, *, db=None):
            nonlocal extend_called
            extend_called = True
            return 0

        session_factory = _SessionFactory()

        with (
            patch("retrovue.runtime.playlist_builder_daemon.PlaylistBuilderDaemon._now_utc_ms", return_value=now_ms),
            patch("retrovue.infra.uow.session", session_factory),
            patch.object(daemon, "_get_frontier_utc_ms", return_value=regressed_frontier_ms),
            patch.object(daemon, "_ensure_playlog_plan_covers_now", return_value=0),
            patch.object(daemon, "_extend_to_target", side_effect=_tracking_extend) as mock_extend,
            patch.object(daemon, "_purge_expired_playlog_plan", return_value=0),
        ):
            daemon.evaluate_once()

        # After the fix, _farthest_end_utc_ms MUST track the actual (lower) frontier
        assert daemon._farthest_end_utc_ms == regressed_frontier_ms, (
            f"_farthest_end_utc_ms should be {regressed_frontier_ms} (actual frontier), "
            f"got {daemon._farthest_end_utc_ms}"
        )

        # Since depth (30min) < target (2h), _extend_to_target MUST have been called
        assert extend_called, (
            "_extend_to_target was not called despite depth (30min) < target (2h). "
            "This means the stale high-water mark masked the gap."
        )


# ---------------------------------------------------------------------------
# FRONTIER-ACTUAL-002: Direct assignment, not monotonic max
# ---------------------------------------------------------------------------

class TestFrontierActual002:
    """evaluate_once() MUST assign _farthest_end_utc_ms directly from
    _get_frontier_utc_ms, not via max()."""

    def test_frontier_decreases_when_db_regresses(self):
        """If _get_frontier_utc_ms returns X < _farthest_end_utc_ms,
        _farthest_end_utc_ms MUST become X."""
        daemon = _make_daemon(min_hours=2)
        now_ms = 1_000_000_000_000

        # Set high-water mark high enough that depth > target (skip extension path)
        high_frontier = now_ms + 10 * 3_600_000
        daemon._farthest_end_utc_ms = high_frontier

        # DB frontier also high (so extension is not triggered), but lower than cache
        lower_but_sufficient = now_ms + 5 * 3_600_000

        session_factory = _SessionFactory()

        with (
            patch("retrovue.runtime.playlist_builder_daemon.PlaylistBuilderDaemon._now_utc_ms", return_value=now_ms),
            patch("retrovue.infra.uow.session", session_factory),
            patch.object(daemon, "_get_frontier_utc_ms", return_value=lower_but_sufficient),
            patch.object(daemon, "_ensure_playlog_plan_covers_now", return_value=0),
            patch.object(daemon, "_purge_expired_playlog_plan", return_value=0),
        ):
            daemon.evaluate_once()

        # _farthest_end_utc_ms MUST track actual, even when actual < cached
        assert daemon._farthest_end_utc_ms == lower_but_sufficient, (
            f"Expected _farthest_end_utc_ms={lower_but_sufficient}, "
            f"got {daemon._farthest_end_utc_ms}. "
            "Monotonic max prevented frontier from decreasing."
        )
