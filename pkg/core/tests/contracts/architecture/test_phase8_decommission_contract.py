"""
Contract Tests: Phase 8 Decommission Contract

Contract reference:
    docs/contracts/architecture/Phase8DecommissionContract.md

These tests enforce the normative outcomes of "Phase 8 removed":
- Single runtime playout authority: blockplan
- No Phase8 services in ProgramDirector registry
- ChannelConfig rejects non-blockplan schedule_source
- No production import of Phase8AirProducer (playlist/load_playlist removed)
"""

from __future__ import annotations

from pathlib import Path

import pytest

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
    assert "schedule_source" in str(exc_info.value)
    assert "mock" in str(exc_info.value) or "phase3" in str(exc_info.value)


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


def test_valid_schedule_sources_includes_phase3_and_dsl():
    """Valid schedule sources include phase3 (blockplan) and dsl; preserve flexibility."""
    assert set(valid_schedule_sources()) == {"phase3", "dsl"}


# =============================================================================
# ProgramDirector registry does not register Phase8 services
# =============================================================================

def test_program_director_registry_does_not_register_phase8_services():
    """ProgramDirector embedded registry must not reference Phase8* services."""
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


def test_no_phase8_classes_in_core_src():
    """No Phase8 schedule/director class definitions remain in pkg/core/src."""
    repo_root = Path(__file__).resolve().parents[5]
    core_src = repo_root / "pkg" / "core" / "src"
    assert core_src.exists(), f"Missing {core_src}"
    forbidden_class_defs = (
        "class Phase8ScheduleService",
        "class Phase8MockScheduleService",
        "class Phase8ProgramDirector",
    )
    found: list[str] = []
    for py_path in core_src.rglob("*.py"):
        rel = py_path.relative_to(core_src)
        content = py_path.read_text()
        for defn in forbidden_class_defs:
            if defn in content:
                found.append(f"{rel}: {defn}")
    assert not found, (
        f"Phase8DecommissionContract: No Phase8 classes in Core src. Found: {found}"
    )


# =============================================================================
# No import of Phase8AirProducer in production code
# =============================================================================

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
