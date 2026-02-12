"""
Contract Tests: Phase 8 Decommission Contract

Contract reference:
    docs/contracts/architecture/Phase8DecommissionContract.md

These tests enforce the normative outcomes of "Phase 8 removed":
- Single runtime playout authority: blockplan
- No Phase8 services in ProgramDirector registry
- ChannelConfig rejects non-blockplan schedule_source
- load_playlist() raises canonical exception when blockplan-only
- No production import of Phase8AirProducer

Tests that assert Phase 8 absence may be xfail until the deletion PR lands.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from retrovue.runtime.channel_manager import (
    ChannelManager,
    Playlist,
    PlaylistSegment,
)
from retrovue.runtime.clock import MasterClock
from retrovue.runtime.config import (
    BLOCKPLAN_SCHEDULE_SOURCE,
    ChannelConfig,
    DEFAULT_PROGRAM_FORMAT,
    assert_schedule_source_valid,
    valid_schedule_sources,
)


# =============================================================================
# Schedule source validation (Phase8 Decommission: only blockplan source valid)
# =============================================================================

def test_channel_config_rejects_schedule_source_mock():
    """ChannelConfig validation rejects schedule_source != phase3 (e.g. 'mock')."""
    config = ChannelConfig(
        channel_id="test",
        channel_id_int=1,
        name="Test",
        program_format=DEFAULT_PROGRAM_FORMAT,
        schedule_source="mock",
    )
    with pytest.raises(ValueError) as exc_info:
        assert_schedule_source_valid(config)
    assert "Phase8DecommissionContract" in str(exc_info.value)
    assert "mock" in str(exc_info.value) or "schedule_source" in str(exc_info.value)


def test_channel_config_accepts_schedule_source_phase3():
    """ChannelConfig validation accepts schedule_source 'phase3' (blockplan)."""
    config = ChannelConfig(
        channel_id="test",
        channel_id_int=1,
        name="Test",
        program_format=DEFAULT_PROGRAM_FORMAT,
        schedule_source=BLOCKPLAN_SCHEDULE_SOURCE,
    )
    assert_schedule_source_valid(config)  # must not raise


def test_valid_schedule_sources_is_phase3():
    """Only blockplan schedule source is valid (phase3)."""
    assert valid_schedule_sources() == ("phase3",)


# =============================================================================
# load_playlist() raises canonical exception
# =============================================================================

class _StubScheduleService:
    def load_schedule(self, channel_id: str) -> tuple[bool, str | None]:
        return (True, None)

    def get_playout_plan_now(self, channel_id: str, at_station_time) -> list[dict]:
        return [{"asset_path": "assets/A.mp4", "duration_ms": 10_000}]


class _StubProgramDirector:
    def get_channel_mode(self, channel_id: str) -> str:
        return "normal"


def test_load_playlist_raises_canonical_exception():
    """Attempting to call load_playlist() on blockplan-only channel raises RuntimeError."""
    config = ChannelConfig(
        channel_id="guard-test",
        channel_id_int=1,
        name="Guard Test Channel",
        program_format=DEFAULT_PROGRAM_FORMAT,
        schedule_source=BLOCKPLAN_SCHEDULE_SOURCE,
        blockplan_only=True,
    )
    mgr = ChannelManager(
        channel_id="guard-test",
        clock=MasterClock(),
        schedule_service=_StubScheduleService(),
        program_director=_StubProgramDirector(),
    )
    mgr.channel_config = config
    now = datetime.now(timezone.utc)
    seg = PlaylistSegment(
        segment_id="seg-0001",
        start_at=now,
        duration_seconds=10,
        type="PROGRAM",
        asset_id="asset-001",
        asset_path="/a.mp4",
        frame_count=300,
    )
    playlist = Playlist(
        channel_id="guard-test",
        channel_timezone="UTC",
        window_start_at=now,
        window_end_at=now + timedelta(seconds=10),
        generated_at=now,
        source="TEST",
        segments=(seg,),
    )
    with pytest.raises(RuntimeError) as exc_info:
        mgr.load_playlist(playlist)
    msg = str(exc_info.value)
    assert "INV-CANONICAL-BOOT" in msg or "forbidden" in msg.lower() or "blockplan_only" in msg


# =============================================================================
# ProgramDirector registry does not register Phase8 services
# =============================================================================

def test_program_director_registry_does_not_register_phase8_services():
    """ProgramDirector embedded registry must not reference Phase8* services."""
    # Resolve path to program_director module (under pkg/core/src)
    repo_root = Path(__file__).resolve().parents[5]
    core_src = repo_root / "pkg" / "core" / "src"
    program_director_path = core_src / "retrovue" / "runtime" / "program_director.py"
    assert program_director_path.exists(), f"Missing {program_director_path}"
    text = program_director_path.read_text()
    forbidden = (
        "Phase8ScheduleService",
        "Phase8MockScheduleService",
        "Phase8ProgramDirector",
        "Phase8AirProducer",
    )
    for name in forbidden:
        assert name not in text, (
            f"Phase8DecommissionContract: ProgramDirector must not register {name}"
        )


# =============================================================================
# No import of Phase8AirProducer in production code (xfail until removed)
# =============================================================================

@pytest.mark.xfail(reason="Phase8 not yet removed; Phase8AirProducer still referenced in Core")
def test_no_import_of_phase8_air_producer_in_core_src():
    """No production code under pkg/core/src may import Phase8AirProducer."""
    repo_root = Path(__file__).resolve().parents[5]
    core_src = repo_root / "pkg" / "core" / "src"
    assert core_src.exists(), f"Missing {core_src}"
    found: list[str] = []
    for py_path in core_src.rglob("*.py"):
        rel = py_path.relative_to(core_src)
        content = py_path.read_text()
        if "Phase8AirProducer" in content:
            found.append(str(rel))
    assert not found, (
        f"Phase8DecommissionContract: Phase8AirProducer must not be imported in production code. "
        f"Found in: {found}"
    )
