"""
Contract Tests — Transmission Log Seam Contract

Tests assert seam invariants from docs/contracts/core/TransmissionLogSeamContract_v0.1.md.
Uses real planning pipeline output where possible.
"""

from __future__ import annotations

from datetime import date, datetime, time

import pytest

from retrovue.runtime.planning_pipeline import (
    InMemoryAssetLibrary,
    MarkerInfo,
    PlanningDirective,
    PlanningRunRequest,
    TransmissionLog,
    TransmissionLogEntry,
    ZoneDirective,
    assemble_transmission_log,
    build_schedule_plan,
    derive_epg,
    fill_breaks,
    lock_for_execution,
    resolve_schedule_day,
    run_planning_pipeline,
    segment_blocks,
)
from retrovue.runtime.schedule_manager_service import (
    InMemoryResolvedStore,
    InMemorySequenceStore,
)
from retrovue.runtime.schedule_types import (
    EPGEvent,
    Episode,
    Program,
    ProgramRef,
    ProgramRefType,
    ScheduleManagerConfig,
)
from retrovue.runtime.transmission_log_validator import (
    TransmissionLogSeamError,
    validate_transmission_log_seams,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CHEERS = Program(
    program_id="cheers",
    name="Cheers",
    play_mode="sequential",
    episodes=[
        Episode("s01e01", "Give Me a Ring Sometime", "/media/cheers/s01e01.mp4", 1320.0),
        Episode("s01e02", "Sam's Women", "/media/cheers/s01e02.mp4", 1340.0),
    ],
)

BROADCAST_DATE = date(2025, 7, 15)
RESOLUTION_TIME = datetime(2025, 7, 15, 5, 0, 0)


def _make_config():
    class SimpleCatalog:
        def __init__(self):
            self._programs = {"cheers": CHEERS}

        def get_program(self, program_id: str):
            return self._programs.get(program_id)

    return ScheduleManagerConfig(
        grid_minutes=30,
        program_catalog=SimpleCatalog(),
        sequence_store=InMemorySequenceStore(),
        resolved_store=InMemoryResolvedStore(),
        filler_path="/media/filler/bars.mp4",
        filler_duration_seconds=0.0,
        programming_day_start_hour=6,
    )


def _make_asset_library():
    lib = InMemoryAssetLibrary()
    lib.register_asset("/media/cheers/s01e01.mp4", 1_320_000)
    lib.register_asset("/media/cheers/s01e02.mp4", 1_340_000)
    lib.register_asset("/media/filler/bars.mp4", 30_000)
    lib.register_filler("/media/filler/promo30.mp4", 30_000, "filler")
    return lib


def _make_log_via_pipeline(
    start: time = time(6, 0),
    end: time = time(7, 0),
) -> TransmissionLog:
    """Generate TransmissionLog via real planning pipeline."""
    directive = PlanningDirective(
        channel_id="ch1",
        grid_block_minutes=30,
        programming_day_start_hour=6,
        zones=[
            ZoneDirective(start, end, [ProgramRef(ProgramRefType.PROGRAM, "cheers")]),
        ],
    )
    run_req = PlanningRunRequest(directive, BROADCAST_DATE, RESOLUTION_TIME)
    config = _make_config()
    lib = _make_asset_library()
    return run_planning_pipeline(run_req, config, lib)


# ---------------------------------------------------------------------------
# INV-TL-SEAM-001 — Contiguous Boundaries
# ---------------------------------------------------------------------------


def test_inv_tl_seam_001_real_pipeline_passes():
    """INV-TL-SEAM-001: Real pipeline produces contiguous boundaries."""
    log = _make_log_via_pipeline()
    validate_transmission_log_seams(log, 30)
    for i in range(len(log.entries) - 1):
        assert log.entries[i].end_utc_ms == log.entries[i + 1].start_utc_ms


def test_inv_tl_seam_001_gap_raises():
    """INV-TL-SEAM-001: Gap between entries raises TransmissionLogSeamError."""
    log = _make_log_via_pipeline()
    base = log.entries[0].start_utc_ms
    block_dur = 30 * 60 * 1000
    entries = [
        TransmissionLogEntry("b0", 0, base, base + block_dur, []),
        TransmissionLogEntry("b1", 1, base + block_dur + 1000, base + 2 * block_dur + 1000, []),
    ]
    bad_log = TransmissionLog(
        channel_id="ch1",
        broadcast_date=BROADCAST_DATE,
        entries=entries,
        is_locked=False,
        metadata={"grid_block_minutes": 30},
    )
    with pytest.raises(TransmissionLogSeamError) as exc_info:
        validate_transmission_log_seams(bad_log, 30)
    assert "INV-TL-SEAM-001" in str(exc_info.value)
    assert "gap" in str(exc_info.value).lower() or "!=" in str(exc_info.value)


def test_inv_tl_seam_001_overlap_raises():
    """INV-TL-SEAM-001: Overlap between entries raises TransmissionLogSeamError."""
    base = 1721000000000
    block_dur = 30 * 60 * 1000
    entries = [
        TransmissionLogEntry("b0", 0, base, base + block_dur, []),
        TransmissionLogEntry("b1", 1, base + block_dur - 5000, base + 2 * block_dur - 5000, []),
    ]
    bad_log = TransmissionLog(
        channel_id="ch1",
        broadcast_date=BROADCAST_DATE,
        entries=entries,
        is_locked=False,
        metadata={"grid_block_minutes": 30},
    )
    with pytest.raises(TransmissionLogSeamError) as exc_info:
        validate_transmission_log_seams(bad_log, 30)
    assert "INV-TL-SEAM-001" in str(exc_info.value)


# ---------------------------------------------------------------------------
# INV-TL-SEAM-002 — Grid Duration Consistency
# ---------------------------------------------------------------------------


def test_inv_tl_seam_002_real_pipeline_passes():
    """INV-TL-SEAM-002: Real pipeline produces correct grid duration."""
    log = _make_log_via_pipeline()
    validate_transmission_log_seams(log, 30)
    expected_ms = 30 * 60 * 1000
    for entry in log.entries:
        assert entry.end_utc_ms - entry.start_utc_ms == expected_ms


def test_inv_tl_seam_002_wrong_duration_raises():
    """INV-TL-SEAM-002: Wrong duration raises TransmissionLogSeamError."""
    base = 1721000000000
    entries = [
        TransmissionLogEntry("b0", 0, base, base + 25 * 60 * 1000, []),
    ]
    bad_log = TransmissionLog(
        channel_id="ch1",
        broadcast_date=BROADCAST_DATE,
        entries=entries,
        is_locked=False,
        metadata={"grid_block_minutes": 30},
    )
    with pytest.raises(TransmissionLogSeamError) as exc_info:
        validate_transmission_log_seams(bad_log, 30)
    assert "INV-TL-SEAM-002" in str(exc_info.value)


# ---------------------------------------------------------------------------
# INV-TL-SEAM-003 — Monotonic Ordering
# ---------------------------------------------------------------------------


def test_inv_tl_seam_003_real_pipeline_passes():
    """INV-TL-SEAM-003: Real pipeline produces strictly increasing entries."""
    log = _make_log_via_pipeline()
    validate_transmission_log_seams(log, 30)
    for i in range(len(log.entries) - 1):
        assert log.entries[i].start_utc_ms < log.entries[i + 1].start_utc_ms


# ---------------------------------------------------------------------------
# INV-TL-SEAM-004 — Non-Zero Duration
# ---------------------------------------------------------------------------


def test_inv_tl_seam_004_real_pipeline_passes():
    """INV-TL-SEAM-004: Real pipeline produces non-zero duration entries."""
    log = _make_log_via_pipeline()
    validate_transmission_log_seams(log, 30)
    for entry in log.entries:
        assert entry.end_utc_ms > entry.start_utc_ms


def test_inv_tl_seam_004_zero_duration_raises():
    """INV-TL-SEAM-004: Zero duration raises TransmissionLogSeamError."""
    base = 1721000000000
    entries = [
        TransmissionLogEntry("b0", 0, base, base, []),
    ]
    bad_log = TransmissionLog(
        channel_id="ch1",
        broadcast_date=BROADCAST_DATE,
        entries=entries,
        is_locked=False,
        metadata={"grid_block_minutes": 30},
    )
    with pytest.raises(TransmissionLogSeamError) as exc_info:
        validate_transmission_log_seams(bad_log, 30)
    assert "INV-TL-SEAM-004" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Enforcement Before Execution Eligibility
# ---------------------------------------------------------------------------


def test_lock_for_execution_validates_and_locks():
    """lock_for_execution validates seams before marking execution-eligible."""
    log = _make_log_via_pipeline()
    lock_time = datetime(2025, 7, 15, 5, 30, 0)
    locked = lock_for_execution(log, lock_time)
    assert locked.is_locked is True


def test_lock_for_execution_rejects_invalid_log():
    """lock_for_execution raises TransmissionLogSeamError for invalid log."""
    base = 1721000000000
    block_dur = 30 * 60 * 1000
    entries = [
        TransmissionLogEntry("b0", 0, base, base + block_dur, []),
        TransmissionLogEntry("b1", 1, base + block_dur + 1000, base + 2 * block_dur + 1000, []),
    ]
    bad_log = TransmissionLog(
        channel_id="ch1",
        broadcast_date=BROADCAST_DATE,
        entries=entries,
        is_locked=False,
        metadata={"grid_block_minutes": 30},
    )
    with pytest.raises(TransmissionLogSeamError):
        lock_for_execution(bad_log, datetime(2025, 7, 15, 5, 30, 0))


def test_lock_for_execution_missing_grid_block_minutes_raises():
    """lock_for_execution raises when grid_block_minutes missing from metadata."""
    log = _make_log_via_pipeline()
    log_without_grid = TransmissionLog(
        channel_id=log.channel_id,
        broadcast_date=log.broadcast_date,
        entries=log.entries,
        is_locked=False,
        metadata={},
    )
    with pytest.raises(TransmissionLogSeamError) as exc_info:
        lock_for_execution(log_without_grid, datetime(2025, 7, 15, 5, 30, 0))
    assert "grid_block_minutes" in str(exc_info.value).lower()


def test_run_planning_pipeline_with_lock_produces_valid_locked_log():
    """run_planning_pipeline with lock_time returns validated locked log."""
    directive = PlanningDirective(
        channel_id="ch1",
        grid_block_minutes=30,
        programming_day_start_hour=6,
        zones=[
            ZoneDirective(
                time(6, 0), time(7, 0),
                [ProgramRef(ProgramRefType.PROGRAM, "cheers")],
            ),
        ],
    )
    run_req = PlanningRunRequest(directive, BROADCAST_DATE, RESOLUTION_TIME)
    config = _make_config()
    lib = _make_asset_library()
    lock_time = datetime(2025, 7, 15, 5, 30, 0)
    log = run_planning_pipeline(run_req, config, lib, lock_time=lock_time)
    assert log.is_locked is True
    validate_transmission_log_seams(log, 30)
