"""
Contract Tests — As-Run Reconciliation Contract

Tests assert reconciliation invariants from
docs/contracts/core/AsRunReconciliationContract_v0.1.md.
Uses real planning pipeline to generate TransmissionLog; synthetic AsRunLog.
No AIR, no modification to planning pipeline or seam validation.
"""

from __future__ import annotations

from datetime import date, datetime, time

import pytest

from retrovue.runtime.asrun_reconciler import reconcile_transmission_log
from retrovue.runtime.asrun_types import AsRunBlock, AsRunLog, AsRunSegment
from retrovue.runtime.planning_pipeline import (
    InMemoryAssetLibrary,
    PlanningDirective,
    PlanningRunRequest,
    TransmissionLog,
    ZoneDirective,
    run_planning_pipeline,
)
from retrovue.runtime.schedule_manager_service import (
    InMemoryResolvedStore,
    InMemorySequenceStore,
)
from retrovue.runtime.schedule_types import (
    Episode,
    Program,
    ProgramRef,
    ProgramRefType,
    ScheduleManagerConfig,
)


# ---------------------------------------------------------------------------
# Helpers (real pipeline, no AIR)
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


def _planned_segment_to_asrun(seg: dict) -> AsRunSegment:
    """Convert planned segment dict to AsRunSegment (no runtime_recovery)."""
    return AsRunSegment(
        segment_type=seg.get("segment_type", ""),
        asset_uri=seg.get("asset_uri") or None,
        asset_start_offset_ms=seg.get("asset_start_offset_ms") if "asset_start_offset_ms" in seg else None,
        segment_duration_ms=seg.get("segment_duration_ms", 0),
        runtime_recovery=False,
    )


def _transmission_log_to_asrun_log(transmission_log: TransmissionLog) -> AsRunLog:
    """Build an AsRunLog that exactly mirrors the TransmissionLog (perfect match)."""
    blocks = [
        AsRunBlock(
            block_id=e.block_id,
            start_utc_ms=e.start_utc_ms,
            end_utc_ms=e.end_utc_ms,
            segments=[_planned_segment_to_asrun(s) for s in e.segments],
        )
        for e in transmission_log.entries
    ]
    return AsRunLog(
        channel_id=transmission_log.channel_id,
        broadcast_date=transmission_log.broadcast_date,
        blocks=blocks,
    )


# ---------------------------------------------------------------------------
# Perfect match
# ---------------------------------------------------------------------------


def test_perfect_match_success():
    """Perfect match → success=True, no errors, no failure classifications."""
    transmission_log = _make_log_via_pipeline()
    as_run_log = _transmission_log_to_asrun_log(transmission_log)
    report = reconcile_transmission_log(transmission_log, as_run_log)
    assert report.success is True
    assert report.errors == []
    assert "MISSING_BLOCK" not in report.classification
    assert "EXTRA_BLOCK" not in report.classification
    assert "BLOCK_TIME_MISMATCH" not in report.classification
    assert "SEGMENT_SEQUENCE_MISMATCH" not in report.classification
    assert "PHANTOM_SEGMENT" not in report.classification


# ---------------------------------------------------------------------------
# INV-ASRUN-001 — Missing block
# ---------------------------------------------------------------------------


def test_missing_block_inv_asrun_001():
    """Missing planned block → MISSING_BLOCK classification."""
    transmission_log = _make_log_via_pipeline()
    as_run_log = _transmission_log_to_asrun_log(transmission_log)
    # Drop last block from as-run
    as_run_log = AsRunLog(
        channel_id=as_run_log.channel_id,
        broadcast_date=as_run_log.broadcast_date,
        blocks=as_run_log.blocks[:-1],
    )
    report = reconcile_transmission_log(transmission_log, as_run_log)
    assert report.success is False
    assert "MISSING_BLOCK" in report.classification
    assert any("Missing as-run block" in e for e in report.errors)


# ---------------------------------------------------------------------------
# INV-ASRUN-001 — Extra block
# ---------------------------------------------------------------------------


def test_extra_block_inv_asrun_001():
    """Extra as-run block not in plan → EXTRA_BLOCK classification."""
    transmission_log = _make_log_via_pipeline()
    as_run_log = _transmission_log_to_asrun_log(transmission_log)
    base = transmission_log.entries[0].start_utc_ms
    block_dur = 30 * 60 * 1000
    extra = AsRunBlock(
        block_id="ch1-extra-not-in-plan",
        start_utc_ms=base + 2 * block_dur,
        end_utc_ms=base + 3 * block_dur,
        segments=[],
    )
    as_run_log = AsRunLog(
        channel_id=as_run_log.channel_id,
        broadcast_date=as_run_log.broadcast_date,
        blocks=as_run_log.blocks + [extra],
    )
    report = reconcile_transmission_log(transmission_log, as_run_log)
    assert report.success is False
    assert "EXTRA_BLOCK" in report.classification
    assert any("Extra as-run block" in e or "not in plan" in e for e in report.errors)


def test_duplicate_block_id_inv_asrun_001():
    """Duplicate block_id in AsRunLog → EXTRA_BLOCK classification."""
    transmission_log = _make_log_via_pipeline()
    as_run_log = _transmission_log_to_asrun_log(transmission_log)
    first = as_run_log.blocks[0]
    duplicate = AsRunBlock(
        block_id=first.block_id,
        start_utc_ms=first.start_utc_ms,
        end_utc_ms=first.end_utc_ms,
        segments=first.segments,
    )
    as_run_log = AsRunLog(
        channel_id=as_run_log.channel_id,
        broadcast_date=as_run_log.broadcast_date,
        blocks=as_run_log.blocks + [duplicate],
    )
    report = reconcile_transmission_log(transmission_log, as_run_log)
    assert report.success is False
    assert "EXTRA_BLOCK" in report.classification
    assert any("Duplicate block_id" in e for e in report.errors)


# ---------------------------------------------------------------------------
# INV-ASRUN-002 — Block timing mismatch
# ---------------------------------------------------------------------------


def test_timing_mismatch_inv_asrun_002():
    """Block start/end time mismatch → BLOCK_TIME_MISMATCH classification."""
    transmission_log = _make_log_via_pipeline()
    as_run_log = _transmission_log_to_asrun_log(transmission_log)
    # Change first block's start_utc_ms
    first = as_run_log.blocks[0]
    as_run_log = AsRunLog(
        channel_id=as_run_log.channel_id,
        broadcast_date=as_run_log.broadcast_date,
        blocks=[
            AsRunBlock(
                block_id=first.block_id,
                start_utc_ms=first.start_utc_ms + 5000,
                end_utc_ms=first.end_utc_ms,
                segments=first.segments,
            ),
            *as_run_log.blocks[1:],
        ],
    )
    report = reconcile_transmission_log(transmission_log, as_run_log)
    assert report.success is False
    assert "BLOCK_TIME_MISMATCH" in report.classification
    assert any("start_utc_ms mismatch" in e or "end_utc_ms" in e for e in report.errors)


# ---------------------------------------------------------------------------
# INV-ASRUN-003 — Segment sequence mismatch
# ---------------------------------------------------------------------------


def test_segment_order_mismatch_inv_asrun_003():
    """Segment order/identity mismatch → SEGMENT_SEQUENCE_MISMATCH classification."""
    transmission_log = _make_log_via_pipeline()
    as_run_log = _transmission_log_to_asrun_log(transmission_log)
    if len(as_run_log.blocks[0].segments) < 2:
        pytest.skip("Need at least 2 segments in first block")
    first = as_run_log.blocks[0]
    segs = list(first.segments)
    segs[0], segs[1] = segs[1], segs[0]
    as_run_log = AsRunLog(
        channel_id=as_run_log.channel_id,
        broadcast_date=as_run_log.broadcast_date,
        blocks=[
            AsRunBlock(
                block_id=first.block_id,
                start_utc_ms=first.start_utc_ms,
                end_utc_ms=first.end_utc_ms,
                segments=segs,
            ),
            *as_run_log.blocks[1:],
        ],
    )
    report = reconcile_transmission_log(transmission_log, as_run_log)
    assert report.success is False
    assert "SEGMENT_SEQUENCE_MISMATCH" in report.classification
    assert any("sequence mismatch" in e for e in report.errors)


# ---------------------------------------------------------------------------
# INV-ASRUN-004 — Phantom segment
# ---------------------------------------------------------------------------


def test_phantom_segment_inv_asrun_004():
    """As-run segment not in plan → PHANTOM_SEGMENT classification."""
    transmission_log = _make_log_via_pipeline()
    as_run_log = _transmission_log_to_asrun_log(transmission_log)
    first = as_run_log.blocks[0]
    phantom = AsRunSegment(
        segment_type="filler",
        asset_uri="/media/filler/phantom.mp4",
        asset_start_offset_ms=0,
        segment_duration_ms=10_000,
        runtime_recovery=False,
    )
    as_run_log = AsRunLog(
        channel_id=as_run_log.channel_id,
        broadcast_date=as_run_log.broadcast_date,
        blocks=[
            AsRunBlock(
                block_id=first.block_id,
                start_utc_ms=first.start_utc_ms,
                end_utc_ms=first.end_utc_ms,
                segments=first.segments + [phantom],
            ),
            *as_run_log.blocks[1:],
        ],
    )
    report = reconcile_transmission_log(transmission_log, as_run_log)
    assert report.success is False
    assert "PHANTOM_SEGMENT" in report.classification
    assert any("phantom" in e.lower() for e in report.errors)


# ---------------------------------------------------------------------------
# Recovery segment allowed → RUNTIME_RECOVERY
# ---------------------------------------------------------------------------


def test_recovery_segment_allowed_classified_runtime_recovery():
    """Recovery segment allowed → classified RUNTIME_RECOVERY, no phantom/mismatch error."""
    transmission_log = _make_log_via_pipeline()
    as_run_log = _transmission_log_to_asrun_log(transmission_log)
    first = as_run_log.blocks[0]
    recovery_seg = AsRunSegment(
        segment_type="filler",
        asset_uri="/media/filler/recovery.mp4",
        asset_start_offset_ms=0,
        segment_duration_ms=5_000,
        runtime_recovery=True,
    )
    as_run_log = AsRunLog(
        channel_id=as_run_log.channel_id,
        broadcast_date=as_run_log.broadcast_date,
        blocks=[
            AsRunBlock(
                block_id=first.block_id,
                start_utc_ms=first.start_utc_ms,
                end_utc_ms=first.end_utc_ms,
                segments=first.segments + [recovery_seg],
            ),
            *as_run_log.blocks[1:],
        ],
    )
    report = reconcile_transmission_log(transmission_log, as_run_log)
    assert "RUNTIME_RECOVERY" in report.classification
    # Recovery segment is allowed: no PHANTOM_SEGMENT or SEGMENT_SEQUENCE_MISMATCH for it
    assert "PHANTOM_SEGMENT" not in report.classification
    assert report.success is True
    assert not any("phantom" in e.lower() or "recovery" in e.lower() for e in report.errors)


# ---------------------------------------------------------------------------
# RUNWAY_DEGRADATION classification
# ---------------------------------------------------------------------------


def test_planned_pad_is_match():
    """Planned PAD in both plan and as-run → MATCH (no recovery, no degradation)."""
    transmission_log = _make_log_via_pipeline()
    as_run_log = _transmission_log_to_asrun_log(transmission_log)
    # The pipeline produces filler/pad segments — a perfect mirror is a perfect match.
    report = reconcile_transmission_log(transmission_log, as_run_log)
    assert report.success is True
    assert report.errors == []
    assert "RUNTIME_RECOVERY" not in report.classification
    assert "RUNWAY_DEGRADATION" not in report.classification


def test_recovery_runway_insufficiency_classified_runway_degradation():
    """Recovery due to runway insufficiency → RUNTIME_RECOVERY + RUNWAY_DEGRADATION."""
    transmission_log = _make_log_via_pipeline()
    as_run_log = _transmission_log_to_asrun_log(transmission_log)
    first = as_run_log.blocks[0]
    runway_recovery_seg = AsRunSegment(
        segment_type="filler",
        asset_uri="/media/filler/runway_recovery.mp4",
        asset_start_offset_ms=0,
        segment_duration_ms=5_000,
        runtime_recovery=True,
        runway_degradation=True,
    )
    as_run_log = AsRunLog(
        channel_id=as_run_log.channel_id,
        broadcast_date=as_run_log.broadcast_date,
        blocks=[
            AsRunBlock(
                block_id=first.block_id,
                start_utc_ms=first.start_utc_ms,
                end_utc_ms=first.end_utc_ms,
                segments=first.segments + [runway_recovery_seg],
            ),
            *as_run_log.blocks[1:],
        ],
    )
    report = reconcile_transmission_log(transmission_log, as_run_log)
    assert report.success is True
    assert "RUNTIME_RECOVERY" in report.classification
    assert "RUNWAY_DEGRADATION" in report.classification
    assert "PHANTOM_SEGMENT" not in report.classification
    assert "MISSING_BLOCK" not in report.classification


def test_missing_block_not_runway_degradation():
    """Missing block → MISSING_BLOCK, not RUNWAY_DEGRADATION."""
    transmission_log = _make_log_via_pipeline()
    as_run_log = _transmission_log_to_asrun_log(transmission_log)
    # Drop last block from as-run
    as_run_log = AsRunLog(
        channel_id=as_run_log.channel_id,
        broadcast_date=as_run_log.broadcast_date,
        blocks=as_run_log.blocks[:-1],
    )
    report = reconcile_transmission_log(transmission_log, as_run_log)
    assert report.success is False
    assert "MISSING_BLOCK" in report.classification
    assert "RUNWAY_DEGRADATION" not in report.classification
