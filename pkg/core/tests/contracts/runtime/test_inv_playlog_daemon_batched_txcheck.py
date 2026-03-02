"""Contract tests for INV-PLAYLOG-DAEMON-BATCHED-TXCHECK-001.

PlaylogHorizonDaemon MUST batch TransmissionLog existence checks and
yield GIL between block fills.

Rules:
1. _extend_to_target() MUST check TransmissionLog existence for
   candidate blocks using a single batched query per scan-day —
   not one query per block.
2. _extend_to_target() MUST yield the GIL (time.sleep(>=0.010))
   after each block fill. 1ms yields are insufficient; 10ms MUST
   be the minimum.
3. A _batch_block_exists_in_txlog(block_ids) method MUST exist and
   MUST return set[str].
4. The wait between consecutive _run_loop() evaluations MUST include
   a random component with a minimum bound of 1 second and a maximum
   of eval_interval_s * 0.25.
"""

import ast
import inspect
import textwrap
import time
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


# ---------------------------------------------------------------------------
# Rule 3: _batch_block_exists_in_txlog method MUST exist
# ---------------------------------------------------------------------------

class TestRule3BatchMethodExists:
    """Rule 3: _batch_block_exists_in_txlog(block_ids) MUST exist and return set[str]."""

    def test_method_exists(self):
        daemon = _make_daemon()
        assert hasattr(daemon, "_batch_block_exists_in_txlog"), (
            "_batch_block_exists_in_txlog method MUST exist on PlaylogHorizonDaemon"
        )
        assert callable(daemon._batch_block_exists_in_txlog)


# ---------------------------------------------------------------------------
# Rule 1: Batched existence checks — not per-block queries
# ---------------------------------------------------------------------------

class TestRule1BatchedExistenceCheck:
    """Rule 1: _extend_to_target() MUST NOT call _block_exists_in_txlog per-block."""

    def test_extend_does_not_call_per_block_exists(self):
        """When extending over multiple candidate blocks, the per-block
        _block_exists_in_txlog MUST NOT be called. Instead, the batched
        method _batch_block_exists_in_txlog MUST be used.
        """
        daemon = _make_daemon()
        now_ms = 1_000_000
        target_ms = 2 * 3_600_000  # 2 hours

        # 4 blocks spanning now → now+2h
        blocks = [
            _fake_block_dict(f"blk-{i}", now_ms + i * 1_800_000, now_ms + (i + 1) * 1_800_000)
            for i in range(4)
        ]

        with (
            patch.object(daemon, "_load_tier1_blocks", return_value=blocks),
            patch.object(daemon, "_block_exists_in_txlog", wraps=lambda _bid: False) as mock_per_block,
            patch.object(daemon, "_batch_block_exists_in_txlog", return_value=set()) as mock_batch,
            patch.object(daemon, "_fill_ads", side_effect=lambda b: b),
            patch.object(daemon, "_write_to_txlog"),
            patch("time.sleep"),
        ):
            daemon._farthest_end_utc_ms = now_ms
            daemon._extend_to_target(now_ms, target_ms)

        # INV: per-block method MUST NOT have been called
        mock_per_block.assert_not_called(), (
            "_extend_to_target called _block_exists_in_txlog per-block "
            "instead of using batched _batch_block_exists_in_txlog"
        )

        # INV: batched method MUST have been called at least once
        assert mock_batch.call_count >= 1, (
            "_batch_block_exists_in_txlog was never called — "
            "_extend_to_target must use batched existence checks"
        )


# ---------------------------------------------------------------------------
# Rule 2: GIL yield after each block fill
# ---------------------------------------------------------------------------

class TestRule2GilYield:
    """Rule 2: _extend_to_target() MUST yield GIL after each block fill."""

    def test_sleep_called_after_each_fill(self):
        """After filling each block, time.sleep() MUST be called to yield GIL."""
        daemon = _make_daemon()
        now_ms = 1_000_000
        target_ms = 2 * 3_600_000

        # 3 blocks, none exist in txlog → all will be filled
        blocks = [
            _fake_block_dict(f"blk-{i}", now_ms + i * 1_800_000, now_ms + (i + 1) * 1_800_000)
            for i in range(3)
        ]

        sleep_calls = []

        with (
            patch.object(daemon, "_load_tier1_blocks", return_value=blocks),
            patch.object(daemon, "_batch_block_exists_in_txlog", return_value=set()),
            patch.object(daemon, "_fill_ads", side_effect=lambda b: b),
            patch.object(daemon, "_write_to_txlog"),
            patch("retrovue.runtime.playlog_horizon_daemon.time.sleep", side_effect=lambda s: sleep_calls.append(s)) as mock_sleep,
        ):
            daemon._farthest_end_utc_ms = now_ms
            daemon._extend_to_target(now_ms, target_ms)

        # INV: sleep MUST be called at least once per filled block
        assert len(sleep_calls) >= 3, (
            f"time.sleep() called {len(sleep_calls)} times for 3 block fills — "
            f"MUST yield GIL after each fill"
        )
        # Each sleep must be > 0 (meaningful yield)
        for s in sleep_calls:
            assert s > 0, f"time.sleep({s}) is not a meaningful GIL yield"

    def test_yield_duration_sufficient(self):
        """Rule 2: GIL yield in _extend_to_target() MUST be >= 10ms.

        AST scan of _extend_to_target() to verify the time.sleep()
        argument meets the minimum. A 1ms yield (0.001) is insufficient
        to prevent upstream reader starvation when filling many blocks;
        10ms (0.010) is the minimum.
        """
        from retrovue.runtime.playlog_horizon_daemon import PlaylogHorizonDaemon

        source = textwrap.dedent(inspect.getsource(PlaylogHorizonDaemon._extend_to_target))
        tree = ast.parse(source)

        # Find all time.sleep(...) calls and extract the constant argument
        sleep_args = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "sleep":
                if node.args and isinstance(node.args[0], ast.Constant):
                    sleep_args.append(node.args[0].value)

        assert sleep_args, (
            "INV-PLAYLOG-DAEMON-BATCHED-TXCHECK-001 Rule 2: "
            "no time.sleep() calls found in _extend_to_target()"
        )

        MIN_YIELD_S = 0.010  # 10ms minimum
        for val in sleep_args:
            assert val >= MIN_YIELD_S, (
                f"INV-PLAYLOG-DAEMON-BATCHED-TXCHECK-001 Rule 2: "
                f"time.sleep({val}) is insufficient. "
                f"Minimum yield MUST be >= {MIN_YIELD_S}s (10ms) "
                f"to prevent upstream reader starvation."
            )


# ---------------------------------------------------------------------------
# Rule 4: Evaluation jitter prevents thundering herd
# ---------------------------------------------------------------------------

class TestRule4EvaluationJitter:
    """Rule 4: _run_loop() wait MUST include a random jitter component."""

    def test_run_loop_uses_random_jitter(self):
        """AST structural: _run_loop() MUST contain a random.uniform call.

        Fails before fix because no `random` import exists in the module.
        """
        from retrovue.runtime.playlog_horizon_daemon import PlaylogHorizonDaemon

        source = textwrap.dedent(inspect.getsource(PlaylogHorizonDaemon._run_loop))
        tree = ast.parse(source)

        # Look for random.uniform(...) call
        found_random_uniform = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "uniform"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "random"
            ):
                found_random_uniform = True
                break
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "uniform"
                and isinstance(func.value, ast.Name)
                and func.value.id == "random"
            ):
                found_random_uniform = True
                break

        assert found_random_uniform, (
            "INV-PLAYLOG-DAEMON-BATCHED-TXCHECK-001 Rule 4: "
            "_run_loop() MUST use random.uniform() for evaluation jitter. "
            "No random.uniform call found in _run_loop() source."
        )

    def test_jitter_varies_across_cycles(self):
        """Behavioral: _run_loop() wait timeouts MUST vary across cycles.

        Runs _run_loop() for 3 evaluation cycles, captures the timeout
        argument passed to Event.wait() on each cycle. Asserts:
        - Timeouts are not all identical (jitter introduces variation).
        - Each timeout exceeds eval_interval_s + 1.0 (minimum jitter bound).

        Fails before fix because all timeouts are exactly eval_interval_s.
        """
        daemon = _make_daemon()
        eval_interval = daemon._eval_interval_s
        wait_timeouts = []
        call_count = [0]

        original_wait = daemon._stop_event.wait

        def mock_wait(timeout=None):
            wait_timeouts.append(timeout)
            call_count[0] += 1
            if call_count[0] >= 3:
                daemon._stop_event.set()
            return daemon._stop_event.is_set()

        with (
            patch.object(daemon, "evaluate_once"),
            patch.object(daemon._stop_event, "wait", side_effect=mock_wait),
            patch.object(daemon._stop_event, "is_set", side_effect=lambda: call_count[0] >= 3),
        ):
            daemon._run_loop()

        assert len(wait_timeouts) >= 3, (
            f"Expected at least 3 wait() calls, got {len(wait_timeouts)}"
        )

        # Each timeout MUST exceed eval_interval_s + 1.0 (minimum jitter)
        for i, t in enumerate(wait_timeouts[:3]):
            assert t >= eval_interval + 1.0, (
                f"INV-PLAYLOG-DAEMON-BATCHED-TXCHECK-001 Rule 4: "
                f"wait timeout[{i}]={t} is below minimum "
                f"(eval_interval_s={eval_interval} + 1.0 jitter minimum). "
                f"_run_loop() MUST add random jitter to the wait."
            )

        # Timeouts MUST NOT all be identical (jitter introduces variation)
        unique_timeouts = set(wait_timeouts[:3])
        assert len(unique_timeouts) > 1, (
            f"INV-PLAYLOG-DAEMON-BATCHED-TXCHECK-001 Rule 4: "
            f"all 3 wait timeouts are identical ({wait_timeouts[:3]}). "
            f"_run_loop() MUST include a random jitter component."
        )
