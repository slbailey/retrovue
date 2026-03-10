"""
Contract tests for INV-CHANNEL-LIVENESS-RECOVERY-001.

ChannelManager MUST attempt to restore continuous emission after a transient
producer failure while viewers remain connected.  Recovery MUST NOT be attempted
when the session ended due to explicit teardown (last viewer left, lookahead
exhausted).
"""

import ast
import inspect
import textwrap
import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_channel_config(channel_id: str = "test-ch") -> "ChannelConfig":
    from retrovue.runtime.config import ChannelConfig

    return ChannelConfig(
        channel_id=channel_id,
        channel_id_int=1,
        name="Test Channel",
        program_format={"width": 1920, "height": 1080, "fps": 30},
        schedule_source="dsl",
        schedule_config={
            "dsl_path": "/dev/null",
            "filler_path": "/opt/retrovue/assets/filler.mp4",
            "filler_duration_ms": 3_650_000,
        },
    )


def _make_channel_manager(
    channel_id: str = "test-ch",
    viewer_count: int = 0,
):
    """Build a ChannelManager with mocked dependencies for recovery testing.

    Returns (manager, mock_timer_class) where mock_timer_class captures
    threading.Timer construction calls.
    """
    from retrovue.runtime.channel_manager import ChannelManager
    from retrovue.runtime.clock import MasterClock

    clock = MagicMock(spec=MasterClock)
    clock.now_utc.return_value = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    schedule_service = MagicMock()
    program_director = MagicMock()
    program_director.get_channel_mode.return_value = "normal"

    manager = ChannelManager(
        channel_id=channel_id,
        clock=clock,
        schedule_service=schedule_service,
        program_director=program_director,
    )

    # Simulate active viewers
    for i in range(viewer_count):
        sid = f"viewer-{i}"
        manager.viewer_sessions[sid] = {"session_id": sid}
    manager.runtime_state.viewer_count = viewer_count

    return manager


# ---------------------------------------------------------------------------
# Contract Tests
# ---------------------------------------------------------------------------


class TestInvChannelLivenessRecovery001:
    """INV-CHANNEL-LIVENESS-RECOVERY-001 contract tests."""

    # -- Test 1: AST structural --

    # Tier: 3 | Integration simulation
    def test_channel_manager_has_recovery_handler(self):
        """ChannelManager source MUST contain a method that checks viewer_count
        in response to producer session end."""
        from retrovue.runtime import channel_manager as cm_module

        source = inspect.getsource(cm_module.ChannelManager)
        tree = ast.parse(textwrap.dedent(source))

        method_names = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]

        # Must have a method whose name contains "producer_session_end" or
        # "producer_failure" — the recovery handler.
        recovery_methods = [
            n for n in method_names
            if "producer_session_end" in n or "producer_failure" in n
        ]
        assert recovery_methods, (
            "ChannelManager MUST have a recovery handler method "
            "(name containing 'producer_session_end' or 'producer_failure'). "
            f"Found methods: {method_names}"
        )

        # That method must reference viewer_count
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in recovery_methods:
                    body_source = ast.get_source_segment(source, node)
                    assert "viewer_count" in (body_source or ""), (
                        f"Recovery handler {node.name} MUST check viewer_count"
                    )

    # -- Test 2: stopped with viewers schedules restart --

    # Tier: 3 | Integration simulation
    def test_stopped_with_viewers_schedules_restart(self):
        """reason='stopped', viewer_count=1 → Timer created targeting recovery."""
        manager = _make_channel_manager(viewer_count=1)

        with patch("threading.Timer") as MockTimer:
            mock_instance = MagicMock()
            MockTimer.return_value = mock_instance

            manager._on_producer_session_end("stopped")

            MockTimer.assert_called_once()
            args, kwargs = MockTimer.call_args
            # First arg is delay (> 0), second is the callback
            assert args[0] > 0, "Timer delay must be positive"
            mock_instance.start.assert_called_once()

    # -- Test 3: last_viewer_left → no restart --

    # Tier: 3 | Integration simulation
    def test_last_viewer_left_no_restart(self):
        """reason='last_viewer_left', viewer_count=0 → no Timer."""
        manager = _make_channel_manager(viewer_count=0)

        with patch("threading.Timer") as MockTimer:
            manager._on_producer_session_end("last_viewer_left")
            MockTimer.assert_not_called()

    # -- Test 4: lookahead_exhausted → no restart --

    # Tier: 3 | Integration simulation
    def test_lookahead_exhausted_no_restart(self):
        """reason='lookahead_exhausted', viewer_count=1 → no Timer.
        Schedule exhaustion is not a transient failure."""
        manager = _make_channel_manager(viewer_count=1)

        with patch("threading.Timer") as MockTimer:
            manager._on_producer_session_end("lookahead_exhausted")
            MockTimer.assert_not_called()

    # -- Test 5: stopped with zero viewers → no restart --

    # Tier: 3 | Integration simulation
    def test_stopped_zero_viewers_no_restart(self):
        """reason='stopped', viewer_count=0 → no Timer."""
        manager = _make_channel_manager(viewer_count=0)

        with patch("threading.Timer") as MockTimer:
            manager._on_producer_session_end("stopped")
            MockTimer.assert_not_called()

    # -- Test 6: error with viewers → schedules restart --

    # Tier: 3 | Integration simulation
    def test_error_with_viewers_schedules_restart(self):
        """reason='error', viewer_count=1 → Timer created."""
        manager = _make_channel_manager(viewer_count=1)

        with patch("threading.Timer") as MockTimer:
            mock_instance = MagicMock()
            MockTimer.return_value = mock_instance

            manager._on_producer_session_end("error")

            MockTimer.assert_called_once()
            mock_instance.start.assert_called_once()

    # -- Test 7: backoff increases --

    # Tier: 3 | Integration simulation
    def test_backoff_increases(self):
        """Consecutive failures → Timer delays are bounded and increasing."""
        manager = _make_channel_manager(viewer_count=1)

        delays = []
        with patch("threading.Timer") as MockTimer:
            mock_instance = MagicMock()
            MockTimer.return_value = mock_instance

            # Trigger multiple consecutive failures
            for _ in range(4):
                MockTimer.reset_mock()
                mock_instance.reset_mock()
                manager._on_producer_session_end("stopped")
                if MockTimer.called:
                    delay = MockTimer.call_args[0][0]
                    delays.append(delay)

        assert len(delays) >= 2, f"Expected at least 2 recovery attempts, got {len(delays)}"

        # Delays must be non-decreasing (with tolerance for equal values at cap)
        for i in range(1, len(delays)):
            assert delays[i] >= delays[i - 1], (
                f"Delay must not decrease: delays={delays}"
            )

        # Delays must be bounded (not infinite)
        assert all(d <= 60.0 for d in delays), (
            f"Delays must be bounded: {delays}"
        )

    # -- Test 8: max attempts gives up --

    # Tier: 3 | Integration simulation
    def test_max_attempts_gives_up(self):
        """After max consecutive failures → no more Timers created."""
        manager = _make_channel_manager(viewer_count=1)

        timer_count = 0
        with patch("threading.Timer") as MockTimer:
            mock_instance = MagicMock()
            MockTimer.return_value = mock_instance

            # Trigger many failures
            for _ in range(20):
                MockTimer.reset_mock()
                mock_instance.reset_mock()
                manager._on_producer_session_end("stopped")
                if MockTimer.called:
                    timer_count += 1

        # Must have created some timers but then stopped
        assert timer_count > 0, "Must attempt at least one recovery"
        assert timer_count < 20, (
            f"Must give up after max attempts, but created {timer_count} timers "
            "out of 20 failures"
        )

    # -- Test 9: recovery counter resets on successful start --

    # Tier: 3 | Integration simulation
    def test_recovery_counter_resets_on_successful_start(self):
        """After _ensure_producer_running succeeds → counter resets to 0,
        next failure uses base delay."""
        manager = _make_channel_manager(viewer_count=1)

        with patch("threading.Timer") as MockTimer:
            mock_instance = MagicMock()
            MockTimer.return_value = mock_instance

            # Trigger 3 failures to bump counter
            for _ in range(3):
                manager._on_producer_session_end("stopped")

            assert manager._recovery_attempts == 3

            # Simulate successful producer start (resets counter)
            with patch.object(manager, "_get_current_mode", return_value="normal"), \
                 patch.object(manager, "_build_producer_for_mode") as mock_build:
                mock_producer = MagicMock()
                mock_producer.mode.value = "normal"
                mock_producer.health.return_value = "running"
                mock_producer.start.return_value = True
                mock_producer.get_stream_endpoint.return_value = "http://test"
                mock_build.return_value = mock_producer

                # Also mock schedule_service.get_block_at
                mock_block = MagicMock()
                mock_block.start_utc_ms = 1000
                mock_block.duration_ms = 5000
                manager.schedule_service.get_block_at.return_value = mock_block

                manager._ensure_producer_running()

            assert manager._recovery_attempts == 0, (
                "Recovery counter must reset to 0 after successful producer start"
            )

            # Next failure should use base delay
            MockTimer.reset_mock()
            mock_instance.reset_mock()
            MockTimer.return_value = mock_instance

            manager._on_producer_session_end("stopped")

            if MockTimer.called:
                delay = MockTimer.call_args[0][0]
                assert delay == manager._RECOVERY_BASE_DELAY_S, (
                    f"After counter reset, delay should be base ({manager._RECOVERY_BASE_DELAY_S}), "
                    f"got {delay}"
                )
