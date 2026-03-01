"""
Contract tests for INV-CHANNEL-STARTUP-NONBLOCKING-001.

Channel viewer-join MUST NOT trigger schedule compilation.
The viewer-join path MUST only lookup a cached schedule block,
compute the JIP offset, and spawn the producer.
"""

import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — lightweight ProgramDirector construction
# ---------------------------------------------------------------------------


def _make_channel_config(channel_id: str = "test-ch") -> "ChannelConfig":
    """Build a minimal ChannelConfig for DSL-backed channels."""
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


def _make_program_director(channel_id: str = "test-ch"):
    """Build a minimal ProgramDirector in embedded mode with a stub DSL service.

    Returns (pd, fake_dsl_service) so tests can inspect the DSL service.
    """
    from retrovue.runtime.config import InlineChannelConfigProvider
    from retrovue.runtime.program_director import ProgramDirector

    config = _make_channel_config(channel_id)
    provider = InlineChannelConfigProvider([config])

    # Build PD in embedded mode with the config provider.
    # We don't actually start the HTTP server or pacing loop.
    pd = ProgramDirector(
        channel_config_provider=provider,
        host="127.0.0.1",
        port=0,
    )

    # Inject a fake DslScheduleService that tracks _build_initial calls
    fake_svc = MagicMock()
    fake_svc.load_schedule = MagicMock(return_value=(True, None))
    fake_svc.get_playout_plan_now = MagicMock(return_value=[])

    # Cache it in PD the same way _get_dsl_service does
    setattr(pd, f"_dsl_{channel_id}", fake_svc)

    # Mark startup as complete (tests bypass the background prewarm thread)
    pd._startup_complete.set()

    return pd, fake_svc


def _create_manager_via_pd(pd, channel_id: str = "test-ch"):
    """Create a ChannelManager through PD's normal code path, mocking AIR spawn."""
    from retrovue.runtime.channel_manager import ChannelManager

    with patch.object(ChannelManager, "_ensure_producer_running"):
        manager = pd._get_or_create_manager(channel_id)
    return manager


# ---------------------------------------------------------------------------
# Contract Tests
# ---------------------------------------------------------------------------


class TestInvChannelStartupNonblocking001:
    """INV-CHANNEL-STARTUP-NONBLOCKING-001 contract tests."""

    def test_manager_survives_teardown(self):
        """_stop_channel_internal() MUST NOT remove ChannelManager from _managers.

        After teardown, the manager MUST still be in _managers with
        _channel_state == "STOPPED" and active_producer == None.
        """
        pd, fake_svc = _make_program_director()
        channel_id = "test-ch"
        manager = _create_manager_via_pd(pd, channel_id)

        # Verify manager exists before teardown
        assert channel_id in pd._managers

        # Stop the channel
        pd._stop_channel_internal(channel_id)

        # INV: Manager MUST survive teardown
        assert channel_id in pd._managers, (
            "ChannelManager was removed from _managers during teardown"
        )
        surviving_manager = pd._managers[channel_id]
        assert surviving_manager is manager
        assert surviving_manager._channel_state == "STOPPED"
        assert surviving_manager.active_producer is None

    def test_retune_after_teardown_skips_build_initial(self):
        """After teardown, _get_or_create_manager() MUST NOT call _build_initial().

        The manager survives teardown, so the second call to
        _get_or_create_manager() should return the existing manager
        without triggering schedule recompilation.
        """
        pd, fake_svc = _make_program_director()
        channel_id = "test-ch"
        manager = _create_manager_via_pd(pd, channel_id)

        # Stop the channel (simulating last viewer disconnect)
        pd._stop_channel_internal(channel_id)

        # Reset call tracking on fake_svc
        fake_svc.load_schedule.reset_mock()

        # Re-obtain the manager (simulating a new viewer tuning in)
        manager2 = pd._get_or_create_manager(channel_id)

        # INV: Must be the same manager (not recreated)
        assert manager2 is manager

        # INV: load_schedule (which calls _build_initial) MUST NOT have been called
        fake_svc.load_schedule.assert_not_called()

    def test_build_initial_idempotent(self):
        """_build_initial() MUST be idempotent: if blocks are already loaded,
        it MUST return without recompilation.
        """
        from retrovue.runtime.dsl_schedule_service import DslScheduleService

        # Create a real DslScheduleService with a minimal DSL
        svc = DslScheduleService(
            dsl_path="/dev/null",
            filler_path="/opt/retrovue/assets/filler.mp4",
            filler_duration_ms=3_650_000,
        )

        # Pre-populate blocks to simulate a previously loaded schedule
        fake_block = MagicMock()
        fake_block.start_utc_ms = 1_000_000
        with svc._lock:
            svc._blocks = [fake_block]

        # Patch _compile_day to detect if compilation occurs
        with patch.object(svc, "_compile_day", side_effect=AssertionError(
            "_compile_day MUST NOT be called when blocks are already loaded"
        )) as mock_compile:
            # _build_initial should return early without compiling
            svc._build_initial("test-ch")

        # INV: Blocks must be unchanged (idempotent)
        assert len(svc._blocks) == 1
        assert svc._blocks[0] is fake_block

    def test_startup_executor_is_bounded(self):
        """ProgramDirector MUST have a bounded _startup_executor.

        The exact cap is governed by INV-CHANNEL-STARTUP-CONCURRENCY-001.
        This test verifies the executor exists and is bounded (not unlimited).
        """
        from concurrent.futures import ThreadPoolExecutor

        pd, _ = _make_program_director()

        assert hasattr(pd, "_startup_executor"), (
            "ProgramDirector missing _startup_executor"
        )
        executor = pd._startup_executor
        assert isinstance(executor, ThreadPoolExecutor)
        assert executor._max_workers is not None and executor._max_workers > 0, (
            f"_startup_executor must be bounded, got max_workers={executor._max_workers}"
        )
