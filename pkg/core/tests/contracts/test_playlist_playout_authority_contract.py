"""Playlist Playout Authority Contract Tests

Contract: INV-PLAYOUT-AUTHORITY

Verifies the control-plane decision that determines which Producer is built
when a ChannelManager starts playout.

    PA-T001  Playlist active → Phase8AirProducer (playlist_authorized=True)
    PA-T002  No playlist + blockplan → BlockPlanProducer
    PA-T003  Phase8AirProducer.start() guard allows playlist-authorized
    PA-T004  Phase8AirProducer.start() guard blocks unauthorized
    PA-T005  ProgramDirector factory delegates to CM when playlist active
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from retrovue.runtime.channel_manager import (
    BlockPlanProducer,
    ChannelManager,
    Phase8AirProducer,
    Playlist,
    PlaylistSegment,
    PLAYOUT_AUTHORITY,
)
from retrovue.runtime.clock import MasterClock
from retrovue.runtime.config import MOCK_CHANNEL_CONFIG


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _StubScheduleService:
    def load_schedule(self, channel_id: str) -> tuple[bool, str | None]:
        return (True, None)

    def get_playout_plan_now(self, channel_id: str, at_station_time: datetime) -> list[dict]:
        return []


class _StubProgramDirector:
    def get_channel_mode(self, channel_id: str) -> str:
        return "normal"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FPS = 30


def _make_playlist(channel_id: str = "test-ch") -> Playlist:
    """Build a minimal one-segment Playlist for testing."""
    now = datetime.now(timezone.utc)
    seg = PlaylistSegment(
        segment_id="seg-0001",
        start_at=now,
        duration_seconds=1800,
        type="PROGRAM",
        asset_id="asset-001",
        asset_path="/dev/null",
        frame_count=1800 * FPS,
    )
    return Playlist(
        channel_id=channel_id,
        channel_timezone="UTC",
        window_start_at=now,
        window_end_at=now + timedelta(seconds=1800),
        generated_at=now,
        source="TEST",
        segments=(seg,),
    )


def _make_manager(channel_id: str = "test-ch") -> ChannelManager:
    """Build a ChannelManager with stub collaborators."""
    mgr = ChannelManager(
        channel_id=channel_id,
        clock=MasterClock(),
        schedule_service=_StubScheduleService(),
        program_director=_StubProgramDirector(),
    )
    mgr.channel_config = MOCK_CHANNEL_CONFIG
    return mgr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPlaylistPlayoutAuthority:
    """INV-PLAYOUT-AUTHORITY: Producer selection is a control-plane decision."""

    def test_pa_t001_playlist_active_selects_phase8(self):
        """PA-T001: When a Playlist is loaded, _build_producer_for_mode returns Phase8AirProducer."""
        mgr = _make_manager()
        mgr.load_playlist(_make_playlist())

        producer = mgr._build_producer_for_mode("normal")

        assert isinstance(producer, Phase8AirProducer)

    def test_pa_t001_playlist_authorized_flag(self):
        """PA-T001: Phase8AirProducer built for playlist has playlist_authorized=True."""
        mgr = _make_manager()
        mgr.load_playlist(_make_playlist())

        producer = mgr._build_producer_for_mode("normal")

        assert producer._playlist_authorized is True

    def test_pa_t002_no_playlist_blockplan_selects_blockplan(self):
        """PA-T002: Without a Playlist, blockplan mode selects BlockPlanProducer."""
        assert PLAYOUT_AUTHORITY == "blockplan", (
            "This test assumes the module-level PLAYOUT_AUTHORITY is 'blockplan'"
        )
        mgr = _make_manager()
        mgr.set_blockplan_mode(True)
        # No playlist loaded

        producer = mgr._build_producer_for_mode("normal")

        assert isinstance(producer, BlockPlanProducer)

    def test_pa_t003_start_guard_allows_playlist_authorized(self):
        """PA-T003: Phase8AirProducer.start() does not raise when playlist_authorized=True."""
        producer = Phase8AirProducer(
            "test-ch", {}, channel_config=MOCK_CHANNEL_CONFIG,
            playlist_authorized=True,
        )
        # start() will return False (no real asset), but must NOT raise RuntimeError
        result = producer.start([], datetime.now(timezone.utc))
        assert result is False  # empty plan → False, but no RuntimeError

    def test_pa_t004_start_guard_blocks_unauthorized(self):
        """PA-T004: Phase8AirProducer.start() raises when not playlist-authorized and PLAYOUT_AUTHORITY is blockplan."""
        assert PLAYOUT_AUTHORITY == "blockplan"
        producer = Phase8AirProducer(
            "test-ch", {}, channel_config=MOCK_CHANNEL_CONFIG,
        )
        with pytest.raises(RuntimeError, match="INV-PLAYOUT-AUTHORITY"):
            producer.start(
                [{"asset_path": "/dev/null", "start_pts": 0}],
                datetime.now(timezone.utc),
            )

    def test_pa_t005_pd_factory_delegates_on_playlist(self):
        """PA-T005: ProgramDirector's factory_wrapper delegates to CM._build_producer_for_mode when playlist is active."""
        from retrovue.runtime.config import ChannelConfig, DEFAULT_PROGRAM_FORMAT, InlineChannelConfigProvider
        from retrovue.runtime.program_director import ProgramDirector

        config = ChannelConfig(
            channel_id="test-ch",
            channel_id_int=1,
            name="Test Channel",
            program_format=DEFAULT_PROGRAM_FORMAT,
            schedule_source="test",
        )
        pd = ProgramDirector(
            channel_config_provider=InlineChannelConfigProvider([config]),
            port=0,
        )

        class _StubSvc:
            def load_schedule(self, channel_id):
                return (True, None)
            def get_playout_plan_now(self, channel_id, at_station_time):
                return []

        pd._schedule_service = _StubSvc()

        manager = pd._get_or_create_manager("test-ch")
        manager.load_playlist(_make_playlist("test-ch"))

        # The monkey-patched factory_wrapper should delegate to CM's method
        producer = manager._build_producer_for_mode("normal")

        assert isinstance(producer, Phase8AirProducer)
        assert producer._playlist_authorized is True
