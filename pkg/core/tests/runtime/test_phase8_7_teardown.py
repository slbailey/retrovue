"""
Phase 8.7 — Immediate Teardown & Lifecycle Ownership.

Contract: Viewer count 0 → ChannelManager destroyed (removed from registry); no reuse;
double disconnect safe; new viewer gets fresh ChannelManager.

See: pkg/air/docs/contracts/phases/Phase8-7-ImmediateTeardown.md

Tests use mocks/lightweight fakes; no Air or UDS.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from retrovue.runtime.producer.base import (
    ContentSegment,
    Producer,
    ProducerMode,
    ProducerStatus,
)
from retrovue.runtime.channel_manager_daemon import (
    ChannelManagerDaemon,
    ChannelManager,
)
from retrovue.runtime.program_director import ProgramDirector


# ---------------------------------------------------------------------------
# Fake producer (no Air / no UDS)
# ---------------------------------------------------------------------------


class FakeProducer(Producer):
    """Minimal Producer for tests; no subprocess, no UDS."""

    def __init__(self, channel_id: str, mode: ProducerMode, configuration: dict[str, Any]):
        super().__init__(channel_id, mode, configuration)
        self._endpoint = f"fake://{channel_id}"

    def start(
        self,
        playout_plan: list[dict[str, Any]],
        start_at_station_time: datetime,
    ) -> bool:
        self.status = ProducerStatus.RUNNING
        self.started_at = start_at_station_time
        self.output_url = self._endpoint
        return True

    def stop(self) -> bool:
        self.status = ProducerStatus.STOPPED
        self.output_url = None
        self._teardown_cleanup()
        return True

    def play_content(self, content: ContentSegment) -> bool:
        return True

    def get_stream_endpoint(self) -> str | None:
        return self.output_url

    def health(self) -> str:
        if self.status == ProducerStatus.RUNNING:
            return "running"
        if self.status == ProducerStatus.ERROR:
            return "degraded"
        return "stopped"

    def get_producer_id(self) -> str:
        return f"fake_{self.channel_id}"

    def on_paced_tick(self, t_now: float, dt: float) -> None:
        self._advance_teardown(dt)


# ---------------------------------------------------------------------------
# Provider fixture (ChannelManagerDaemon with fake producer; no HTTP, no Air)
# ---------------------------------------------------------------------------

CHANNEL_ID = "mock"


@pytest.fixture
def channel_manager_provider() -> ChannelManagerDaemon:
    """ChannelManagerDaemon with mock schedule and FakeProducer; no start() so no HTTP/Air."""
    daemon = ChannelManagerDaemon(schedule_dir=None)
    daemon._producer_factory = lambda channel_id, mode, config, channel_config=None: FakeProducer(
        channel_id, ProducerMode.NORMAL, config or {}
    )
    return daemon


# ---------------------------------------------------------------------------
# Tests (Phase 8.7: provider destroys manager on stop_channel when viewer count 0)
# ---------------------------------------------------------------------------


def test_viewer_count_zero_destroys_channel_manager(channel_manager_provider: ChannelManagerDaemon) -> None:
    """
    Phase 8.7: When viewer count goes 1 → 0, ChannelManager is destroyed (removed from registry).

    - Start ProgramDirector (with provider).
    - Simulate first viewer connect → channel manager exists.
    - Simulate viewer disconnect → channel manager removed immediately.
    """
    provider = channel_manager_provider
    director = ProgramDirector(channel_manager_provider=provider)
    director.start()
    try:
        assert CHANNEL_ID not in provider.list_channels()

        # Simulate first viewer connect (same path as stream endpoint: get manager, then viewer_join)
        manager = provider.get_channel_manager(CHANNEL_ID)
        manager.viewer_join("session-1", {"channel_id": CHANNEL_ID})
        assert CHANNEL_ID in provider.list_channels()

        # Simulate last viewer disconnect (same order as daemon: viewer_leave then stop_channel)
        manager.viewer_leave("session-1")
        provider.stop_channel(CHANNEL_ID)

        # Phase 8.7: ChannelManager MUST be destroyed — removed from provider registry.
        assert CHANNEL_ID not in provider.list_channels(), (
            "Phase 8.7: ChannelManager must be destroyed when viewer count goes to 0; "
            "provider must remove channel from registry on stop_channel."
        )
        # No active ChannelStream or background tasks for this channel after teardown.
        assert not provider.has_channel_stream(CHANNEL_ID), (
            "Phase 8.7: No channel stream (reader loop) must remain for torn-down channel."
        )
    finally:
        director.stop(timeout=1.0)


def test_double_disconnect_is_safe(channel_manager_provider: ChannelManagerDaemon) -> None:
    """
    Phase 8.7: Disconnecting twice (e.g. duplicate stop_channel or viewer_leave) must not
    raise exceptions and viewer count must never go negative.
    """
    provider = channel_manager_provider
    manager = provider.get_channel_manager(CHANNEL_ID)
    manager.viewer_join("session-1", {"channel_id": CHANNEL_ID})
    assert manager.runtime_state.viewer_count == 1

    # First disconnect
    manager.viewer_leave("session-1")
    assert manager.runtime_state.viewer_count == 0
    provider.stop_channel(CHANNEL_ID)

    # Second disconnect (no second viewer) — must not raise
    provider.stop_channel(CHANNEL_ID)

    # If manager still exists (pre-8.7), viewer_count must not have gone negative
    if CHANNEL_ID in provider.list_channels():
        m = provider.get_channel_manager(CHANNEL_ID)
        assert m.runtime_state.viewer_count >= 0, "viewer_count must never go negative"


def test_new_viewer_creates_fresh_channel_manager(channel_manager_provider: ChannelManagerDaemon) -> None:
    """
    Phase 8.7: Connect → disconnect → connect again must create a NEW ChannelManager
    instance (not reuse the torn-down one).
    """
    provider = channel_manager_provider

    # First connect
    manager1 = provider.get_channel_manager(CHANNEL_ID)
    manager1.viewer_join("session-1", {"channel_id": CHANNEL_ID})
    id1 = id(manager1)

    # Disconnect
    manager1.viewer_leave("session-1")
    provider.stop_channel(CHANNEL_ID)

    # Second connect — must be a new instance
    manager2 = provider.get_channel_manager(CHANNEL_ID)
    id2 = id(manager2)

    assert id1 != id2, (
        "Phase 8.7: Second tune-in must create a new ChannelManager instance; "
        "torn-down channel must not be reused."
    )
