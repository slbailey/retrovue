"""INV-CM-ORCHESTRATION-SOLE-OWNER-001: ChannelManager owns the per-channel
runtime orchestration methods (producer-start, producer-stop, driver loop,
health, failure surfacing, HLS timebase push). ProgramDirector's teardown
paths use the narrow ``halt_producer()`` CM API rather than reaching through
``active_producer``.

Phase 5C.1 of the ADR-004 migration. BPP retains its orchestration methods
as rollback-safe dead code until Phase 5C.2.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
CM_PATH = REPO_ROOT / "server" / "src" / "retrovue" / "runtime" / "channel_manager.py"
PD_PATH = REPO_ROOT / "server" / "src" / "retrovue" / "runtime" / "program_director.py"


class TestChannelManagerOrchestrationSurface:
    """CM exposes the orchestration methods."""

    @pytest.mark.parametrize("method", [
        "_producer_start",
        "_producer_stop",
        "_producer_health",
        "_producer_driver_loop",
        "_producer_fail",
        "_producer_push_hls_timebase",
        "halt_producer",
    ])
    def test_method_present(self, method: str) -> None:
        from retrovue.runtime.channel_manager import ChannelManager

        assert hasattr(ChannelManager, method), (
            f"ChannelManager MUST expose {method}() for Phase 5C.1 "
            f"(INV-CM-ORCHESTRATION-SOLE-OWNER-001)"
        )


class TestChannelManagerCallsOwnOrchestration:
    """CM's runtime paths call CM's methods, not active_producer.X()."""

    def test_ensure_producer_running_calls_producer_start(self) -> None:
        from retrovue.runtime.channel_manager import ChannelManager

        src = inspect.getsource(ChannelManager._ensure_producer_running)
        assert "self._producer_start(" in src, (
            "_ensure_producer_running MUST call self._producer_start(...)"
        )
        assert "self.active_producer.start(" not in src, (
            "_ensure_producer_running MUST NOT call self.active_producer.start(...)"
        )

    def test_ensure_producer_running_uses_producer_stop(self) -> None:
        from retrovue.runtime.channel_manager import ChannelManager

        src = inspect.getsource(ChannelManager._ensure_producer_running)
        # The pre-restart cleanup path previously did
        # self.active_producer.stop(); migrated to CM orchestration.
        assert "self.active_producer.stop(" not in src, (
            "_ensure_producer_running MUST NOT call self.active_producer.stop(...)"
        )

    def test_ensure_producer_running_does_not_read_health_through_bpp(self) -> None:
        from retrovue.runtime.channel_manager import ChannelManager

        src = inspect.getsource(ChannelManager._ensure_producer_running)
        assert "self.active_producer.health(" not in src, (
            "_ensure_producer_running MUST call self._producer_health() "
            "instead of self.active_producer.health()"
        )


class TestProgramDirectorUsesHaltProducer:
    """PD shutdown paths no longer reach through active_producer."""

    def test_pd_does_not_call_active_producer_stop(self) -> None:
        src = PD_PATH.read_text()
        assert "active_producer.stop(" not in src, (
            "ProgramDirector MUST NOT call manager.active_producer.stop(...); "
            "use manager.halt_producer(reason=...) instead "
            "(INV-CM-ORCHESTRATION-SOLE-OWNER-001)"
        )


class TestHaltProducerIsNarrow:
    """halt_producer() is the narrow 'terminate AIR subprocess' API; does not
    trigger channel-wide teardown side effects like stop_channel does."""

    def test_halt_producer_exists_as_public_method(self) -> None:
        from retrovue.runtime.channel_manager import ChannelManager

        method = getattr(ChannelManager, "halt_producer", None)
        assert method is not None, "halt_producer MUST exist as a CM method"
        assert callable(method), "halt_producer MUST be callable"

    def test_halt_producer_delegates_to_producer_stop(self) -> None:
        from retrovue.runtime.channel_manager import ChannelManager

        src = inspect.getsource(ChannelManager.halt_producer)
        assert "self._producer_stop(" in src, (
            "halt_producer MUST delegate to self._producer_stop(...) "
            "so it is a narrow subprocess-halt API, not a channel-teardown API"
        )
