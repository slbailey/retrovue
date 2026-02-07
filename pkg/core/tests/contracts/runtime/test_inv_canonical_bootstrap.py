"""
Contract Tests: INV-CANONICAL-BOOTSTRAP

Contract reference:
    docs/contracts/runtime/INV-CANONICAL-BOOTSTRAP.md

These tests enforce the single-bootstrap-path guard: when a channel's
ChannelConfig has blockplan_only=True, all legacy playout paths
(load_playlist, Phase8AirProducer, _ensure_producer_running_playlist,
_tick_playlist) MUST raise RuntimeError immediately.

    INV-CANONICAL-BOOT-001  load_playlist rejected
    INV-CANONICAL-BOOT-002  Phase8AirProducer selection rejected
    INV-CANONICAL-BOOT-003  Playlist bootstrap rejected
    INV-CANONICAL-BOOT-004  Playlist tick rejected
    INV-CANONICAL-BOOT-005  BlockPlanProducer allowed

All tests are deterministic and require no media files or AIR process.

Copyright (c) 2025 RetroVue
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from retrovue.runtime.channel_manager import (
    BlockPlanProducer,
    ChannelManager,
    Phase8AirProducer,
    Playlist,
    PlaylistSegment,
)
from retrovue.runtime.clock import MasterClock
from retrovue.runtime.config import (
    ChannelConfig,
    MOCK_CHANNEL_CONFIG,
    ProgramFormat,
    DEFAULT_PROGRAM_FORMAT,
)


# =============================================================================
# Test Infrastructure
# =============================================================================

class _StubScheduleService:
    def load_schedule(self, channel_id: str) -> tuple[bool, str | None]:
        return (True, None)

    def get_playout_plan_now(self, channel_id: str, at_station_time) -> list[dict]:
        return [{"asset_path": "assets/A.mp4", "duration_ms": 10_000}]


class _StubProgramDirector:
    def get_channel_mode(self, channel_id: str) -> str:
        return "normal"


def _blockplan_only_config() -> ChannelConfig:
    """ChannelConfig with blockplan_only=True."""
    return ChannelConfig(
        channel_id="guard-test",
        channel_id_int=1,
        name="Guard Test Channel",
        program_format=DEFAULT_PROGRAM_FORMAT,
        schedule_source="mock",
        blockplan_only=True,
    )


def _normal_config() -> ChannelConfig:
    """ChannelConfig with blockplan_only=False (default)."""
    return ChannelConfig(
        channel_id="guard-test",
        channel_id_int=1,
        name="Guard Test Channel",
        program_format=DEFAULT_PROGRAM_FORMAT,
        schedule_source="mock",
        blockplan_only=False,
    )


def _make_manager(blockplan_only: bool) -> ChannelManager:
    """Build a ChannelManager with the given blockplan_only setting."""
    config = _blockplan_only_config() if blockplan_only else _normal_config()
    mgr = ChannelManager(
        channel_id="guard-test",
        clock=MasterClock(),
        schedule_service=_StubScheduleService(),
        program_director=_StubProgramDirector(),
    )
    mgr.channel_config = config
    return mgr


def _make_playlist() -> Playlist:
    """Build a minimal one-segment Playlist."""
    now = datetime.now(timezone.utc)
    seg = PlaylistSegment(
        segment_id="seg-0001",
        start_at=now,
        duration_seconds=1800,
        type="PROGRAM",
        asset_id="asset-001",
        asset_path="/dev/null",
        frame_count=1800 * 30,
    )
    return Playlist(
        channel_id="guard-test",
        channel_timezone="UTC",
        window_start_at=now,
        window_end_at=now + timedelta(seconds=1800),
        generated_at=now,
        source="TEST",
        segments=(seg,),
    )


# =============================================================================
# 1. INV-CANONICAL-BOOT-001: load_playlist rejected
# =============================================================================

class TestLoadPlaylistRejected:
    """INV-CANONICAL-BOOT-001: load_playlist raises on blockplan_only channels."""

    def test_load_playlist_rejected(self):
        """load_playlist() raises RuntimeError when blockplan_only=True."""
        mgr = _make_manager(blockplan_only=True)

        with pytest.raises(RuntimeError, match="INV-CANONICAL-BOOT"):
            mgr.load_playlist(_make_playlist())

    def test_playlist_remains_none_after_rejection(self):
        """After the guard fires, _playlist is still None."""
        mgr = _make_manager(blockplan_only=True)

        with pytest.raises(RuntimeError):
            mgr.load_playlist(_make_playlist())

        assert mgr._playlist is None


# =============================================================================
# 2. INV-CANONICAL-BOOT-002: Phase8AirProducer selection rejected
# =============================================================================

class TestPhase8ProducerRejected:
    """INV-CANONICAL-BOOT-002: _build_producer_for_mode raises when _playlist
    is set on a blockplan_only channel."""

    def test_phase8_producer_rejected(self):
        """Force _playlist to non-None, then call _build_producer_for_mode."""
        mgr = _make_manager(blockplan_only=True)
        mgr.set_blockplan_mode(True)
        # Bypass load_playlist guard to set _playlist directly (defense-in-depth test)
        mgr._playlist = _make_playlist()

        with pytest.raises(RuntimeError, match="INV-CANONICAL-BOOT"):
            mgr._build_producer_for_mode("normal")


# =============================================================================
# 3. INV-CANONICAL-BOOT-003: Playlist bootstrap rejected
# =============================================================================

class TestPlaylistBootstrapRejected:
    """INV-CANONICAL-BOOT-003: _ensure_producer_running_playlist raises on
    blockplan_only channels."""

    def test_playlist_bootstrap_rejected(self):
        """_ensure_producer_running_playlist() raises RuntimeError."""
        mgr = _make_manager(blockplan_only=True)

        with pytest.raises(RuntimeError, match="INV-CANONICAL-BOOT"):
            mgr._ensure_producer_running_playlist(datetime.now(timezone.utc))


# =============================================================================
# 4. INV-CANONICAL-BOOT-004: Playlist tick rejected
# =============================================================================

class TestPlaylistTickRejected:
    """INV-CANONICAL-BOOT-004: _tick_playlist raises on blockplan_only channels."""

    def test_playlist_tick_rejected(self):
        """_tick_playlist() raises RuntimeError."""
        mgr = _make_manager(blockplan_only=True)

        with pytest.raises(RuntimeError, match="INV-CANONICAL-BOOT"):
            mgr._tick_playlist()


# =============================================================================
# 5. INV-CANONICAL-BOOT-005: BlockPlanProducer allowed
# =============================================================================

class TestBlockPlanProducerAllowed:
    """INV-CANONICAL-BOOT-005: The canonical path works on blockplan_only channels."""

    def test_blockplan_producer_allowed(self):
        """_build_producer_for_mode returns BlockPlanProducer when
        blockplan_only=True and _blockplan_mode=True."""
        mgr = _make_manager(blockplan_only=True)
        mgr.set_blockplan_mode(True)
        # No playlist loaded — canonical path

        producer = mgr._build_producer_for_mode("normal")

        assert isinstance(producer, BlockPlanProducer)


# =============================================================================
# 6. Non-blockplan_only channels: legacy paths remain callable
# =============================================================================

class TestNonBlockplanOnlyAllowsLegacy:
    """Without blockplan_only=True, all legacy paths remain callable."""

    def test_load_playlist_allowed(self):
        """load_playlist() succeeds when blockplan_only=False."""
        mgr = _make_manager(blockplan_only=False)

        # Should NOT raise
        mgr.load_playlist(_make_playlist())

        assert mgr._playlist is not None

    def test_phase8_producer_allowed(self):
        """_build_producer_for_mode returns Phase8AirProducer when playlist loaded
        and blockplan_only=False."""
        mgr = _make_manager(blockplan_only=False)
        mgr.load_playlist(_make_playlist())

        producer = mgr._build_producer_for_mode("normal")

        assert isinstance(producer, Phase8AirProducer)

    def test_tick_playlist_callable(self):
        """_tick_playlist() does not raise when blockplan_only=False."""
        mgr = _make_manager(blockplan_only=False)
        # _tick_playlist returns early if no producer/playlist — but must not raise
        mgr._tick_playlist()  # Should not raise


# =============================================================================
# 7. Error message quality
# =============================================================================

class TestErrorMessageQuality:
    """All guard errors contain the invariant prefix and the channel ID."""

    @pytest.mark.parametrize("method,args", [
        ("load_playlist", [None]),  # placeholder — replaced in body
        ("_ensure_producer_running_playlist", [None]),
        ("_tick_playlist", []),
    ])
    def test_error_contains_invariant_prefix_and_channel_id(self, method, args):
        """Error message includes INV-CANONICAL-BOOT and the channel ID."""
        mgr = _make_manager(blockplan_only=True)

        # Fix up args for methods that need real values
        if method == "load_playlist":
            args = [_make_playlist()]
        elif method == "_ensure_producer_running_playlist":
            args = [datetime.now(timezone.utc)]

        with pytest.raises(RuntimeError) as exc_info:
            getattr(mgr, method)(*args)

        msg = str(exc_info.value)
        assert "INV-CANONICAL-BOOT" in msg, f"Missing invariant prefix in: {msg}"
        assert "guard-test" in msg, f"Missing channel_id in: {msg}"
        assert "blockplan_only=True" in msg, f"Missing config flag in: {msg}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
