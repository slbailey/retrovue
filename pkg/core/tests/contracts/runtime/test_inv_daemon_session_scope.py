"""Contract tests for INV-DAEMON-SESSION-SCOPE-001.

Each PlaylogHorizonDaemon.evaluate_once() cycle MUST acquire at most one
database session for its entire execution. Daemon threads MUST NOT open
multiple sessions per evaluation cycle, as cumulative checkout storms across
N concurrent daemons cause QueuePool exhaustion under multi-channel load.

Rules:
1. evaluate_once() MUST open at most one database session and pass it to
   all sub-methods within that cycle.
2. All database helper methods MUST accept an optional `db` parameter.
   When provided, they MUST reuse it instead of opening a new session.
3. _extend_to_target() MUST NOT open any sessions internally; it MUST
   receive the session from evaluate_once().
4. With N active channels, peak daemon connection demand MUST be at most N.
"""

import threading
from datetime import date
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_daemon():
    from retrovue.runtime.playlog_horizon_daemon import PlaylogHorizonDaemon
    return PlaylogHorizonDaemon(
        channel_id="test-ch",
        min_hours=2,
        programming_day_start_hour=6,
        channel_tz="UTC",
    )


def _fake_block_dict(block_id: str, start_ms: int, end_ms: int, segments_count: int = 3):
    """Minimal Tier-1 segmented block dict."""
    seg_dur = (end_ms - start_ms) // segments_count if segments_count else 0
    return {
        "block_id": block_id,
        "start_utc_ms": start_ms,
        "end_utc_ms": end_ms,
        "segments": [
            {
                "segment_type": "content" if i == 0 else "filler",
                "asset_uri": "/path/to/asset.mp4" if i == 0 else "",
                "asset_start_offset_ms": 0,
                "segment_duration_ms": seg_dur,
                "transition_in": "TRANSITION_NONE",
                "transition_in_duration_ms": 0,
                "transition_out": "TRANSITION_NONE",
                "transition_out_duration_ms": 0,
            }
            for i in range(segments_count)
        ],
    }


class _SessionCounter:
    """Instrument session() factory to count total checkouts during a scope."""

    def __init__(self):
        self.total_checkouts = 0
        self.peak_concurrent = 0
        self._active = 0
        self._lock = threading.Lock()

    class _FakeSession:
        """Minimal mock that quacks like a SQLAlchemy Session."""

        def __init__(self):
            self._items = []

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

    def __call__(self):
        """Return a context manager that tracks checkout/return."""
        counter = self

        class _Ctx:
            def __enter__(self_ctx):
                with counter._lock:
                    counter.total_checkouts += 1
                    counter._active += 1
                    if counter._active > counter.peak_concurrent:
                        counter.peak_concurrent = counter._active
                return _SessionCounter._FakeSession()

            def __exit__(self_ctx, *args):
                with counter._lock:
                    counter._active -= 1

        return _Ctx()


# ---------------------------------------------------------------------------
# Rule 1: evaluate_once() MUST open at most one session
# ---------------------------------------------------------------------------

class TestRule1SingleSessionPerCycle:
    """Rule 1: evaluate_once() MUST open at most one database session."""

    def test_evaluate_once_opens_at_most_one_session(self):
        """When evaluate_once() runs an evaluation cycle that fills blocks,
        the total number of session checkouts MUST be at most 1.

        VIOLATION (before fix): Each helper (_get_frontier_utc_ms,
        _tier2_row_covers_now, _load_tier1_blocks, _batch_block_exists_in_txlog,
        _fill_ads, _write_to_txlog, _purge_expired_tier2) opens its own session.
        With 4 blocks to fill, this results in 10+ checkouts per cycle.
        """
        daemon = _make_daemon()
        now_ms = 1_000_000

        # 4 blocks spanning 2 hours, none in txlog → all will be filled
        blocks = [
            _fake_block_dict(
                f"blk-{i}",
                now_ms + i * 1_800_000,
                now_ms + (i + 1) * 1_800_000,
            )
            for i in range(4)
        ]

        counter = _SessionCounter()

        with (
            patch(
                "retrovue.infra.uow.session",
                counter,
            ),
            patch.object(daemon, "_load_tier1_blocks", return_value=blocks),
            patch.object(daemon, "_batch_block_exists_in_txlog", return_value=set()),
            patch.object(daemon, "_fill_ads", side_effect=lambda b, db=None: b),
            patch.object(daemon, "_write_to_txlog"),
            patch("retrovue.runtime.playlog_horizon_daemon.time.sleep"),
        ):
            daemon._farthest_end_utc_ms = now_ms
            daemon.evaluate_once()

        assert counter.total_checkouts <= 1, (
            f"INV-DAEMON-SESSION-SCOPE-001 Rule 1: evaluate_once() opened "
            f"{counter.total_checkouts} sessions — MUST be at most 1. "
            f"Each daemon thread must hold a single session per cycle to "
            f"prevent QueuePool exhaustion under multi-channel load."
        )


# ---------------------------------------------------------------------------
# Rule 2: helper methods MUST accept optional db parameter
# ---------------------------------------------------------------------------

class TestRule2HelpersAcceptDbParam:
    """Rule 2: DB helpers MUST accept an optional `db` parameter."""

    @pytest.mark.parametrize("method_name", [
        "_tier2_row_covers_now",
        "_get_frontier_utc_ms",
        "_load_tier1_blocks",
        "_batch_block_exists_in_txlog",
        "_fill_ads",
        "_write_to_txlog",
        "_purge_expired_tier2",
    ])
    def test_method_accepts_db_param(self, method_name):
        """Each DB helper MUST accept an optional `db` keyword argument."""
        import inspect
        daemon = _make_daemon()
        method = getattr(daemon, method_name)
        sig = inspect.signature(method)

        assert "db" in sig.parameters, (
            f"INV-DAEMON-SESSION-SCOPE-001 Rule 2: "
            f"{method_name}() MUST accept an optional `db` parameter "
            f"to allow session reuse. Found parameters: "
            f"{list(sig.parameters.keys())}"
        )

        param = sig.parameters["db"]
        assert param.default is not inspect.Parameter.empty, (
            f"INV-DAEMON-SESSION-SCOPE-001 Rule 2: "
            f"{method_name}(db=...) MUST have a default value (None) "
            f"so callers without a session still work."
        )


# ---------------------------------------------------------------------------
# Rule 3: _extend_to_target MUST NOT open sessions itself
# ---------------------------------------------------------------------------

class TestRule3ExtendNoOwnSessions:
    """Rule 3: _extend_to_target() MUST NOT open sessions internally."""

    def test_extend_to_target_has_db_parameter(self):
        """_extend_to_target() MUST accept a `db` parameter so
        evaluate_once() can pass its session through.

        VIOLATION (before fix): _extend_to_target has no db parameter;
        sub-methods open their own sessions.
        """
        import inspect
        daemon = _make_daemon()
        sig = inspect.signature(daemon._extend_to_target)

        assert "db" in sig.parameters, (
            f"INV-DAEMON-SESSION-SCOPE-001 Rule 3: _extend_to_target() MUST "
            f"accept a `db` parameter to receive the session from "
            f"evaluate_once(). Found parameters: {list(sig.parameters.keys())}"
        )

    def test_extend_to_target_passes_db_to_helpers(self):
        """_extend_to_target() MUST forward its db param to _fill_ads
        and _write_to_txlog.

        VIOLATION (before fix): _fill_ads and _write_to_txlog are called
        without a db argument; they open their own sessions.
        """
        import ast
        import inspect
        import textwrap
        from retrovue.runtime.playlog_horizon_daemon import PlaylogHorizonDaemon

        source = textwrap.dedent(inspect.getsource(PlaylogHorizonDaemon._extend_to_target))
        tree = ast.parse(source)

        # Find calls to self._fill_ads and self._write_to_txlog and check
        # they pass a `db` keyword argument
        helpers_checked = {"_fill_ads": False, "_write_to_txlog": False}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            # self.xxx → Attribute(value=Name(id='self'), attr='xxx')
            method_name = func.attr
            if method_name in helpers_checked:
                kw_names = [kw.arg for kw in node.keywords]
                if "db" in kw_names:
                    helpers_checked[method_name] = True

        for method, found_db in helpers_checked.items():
            assert found_db, (
                f"INV-DAEMON-SESSION-SCOPE-001 Rule 3: _extend_to_target() "
                f"calls {method}() without passing db= keyword argument. "
                f"It MUST forward the session to all DB helpers."
            )


# ---------------------------------------------------------------------------
# Rule 4: N daemons = at most N concurrent connections
# ---------------------------------------------------------------------------

class TestRule4BoundedConcurrentConnections:
    """Rule 4: N concurrent daemons MUST use at most N connections."""

    def test_concurrent_daemons_bounded_connections(self):
        """Run 4 daemons in parallel threads. Peak concurrent session
        checkouts MUST be at most 4 (one per daemon thread).

        VIOLATION (before fix): Each daemon opens multiple sessions per
        cycle. With 4 daemons × ~10 sessions each, peak concurrent
        connections can reach 8+ even with sequential per-thread access.
        """
        N = 4
        now_ms = 1_000_000

        blocks = [
            _fake_block_dict(
                f"blk-{i}",
                now_ms + i * 1_800_000,
                now_ms + (i + 1) * 1_800_000,
            )
            for i in range(4)
        ]

        counter = _SessionCounter()

        def run_daemon(channel_id: str):
            daemon = _make_daemon()
            daemon._channel_id = channel_id
            with (
                patch(
                    "retrovue.infra.uow.session",
                    counter,
                ),
                patch.object(daemon, "_load_tier1_blocks", return_value=blocks),
                patch.object(daemon, "_batch_block_exists_in_txlog", return_value=set()),
                patch.object(daemon, "_fill_ads", side_effect=lambda b, db=None: b),
                patch.object(daemon, "_write_to_txlog"),
                patch("retrovue.runtime.playlog_horizon_daemon.time.sleep"),
            ):
                daemon._farthest_end_utc_ms = now_ms
                daemon.evaluate_once()

        threads = [
            threading.Thread(target=run_daemon, args=(f"ch-{i}",))
            for i in range(N)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert counter.total_checkouts <= N, (
            f"INV-DAEMON-SESSION-SCOPE-001 Rule 4: {N} daemons opened "
            f"{counter.total_checkouts} total sessions — MUST be at most {N}. "
            f"Each daemon MUST use exactly one session per evaluate_once() cycle."
        )
