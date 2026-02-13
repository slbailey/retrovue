"""
As-Run reconciliation: compare TransmissionLog (plan) to AsRunLog (actual).

Enforces AsRunReconciliationContract v0.1. Deterministic, no mutation, no Horizon/AIR.
"""

from __future__ import annotations

from dataclasses import dataclass

from retrovue.runtime.asrun_types import AsRunBlock, AsRunLog, AsRunSegment
from retrovue.runtime.planning_pipeline import TransmissionLog, TransmissionLogEntry


class AsRunReconciliationError(Exception):
    """Raised when reconciliation encounters an unrecoverable error (e.g. invalid input)."""


@dataclass
class ReconciliationReport:
    """Result of reconciling a TransmissionLog with an AsRunLog."""
    success: bool
    errors: list[str]
    classification: list[str]


def _planned_segment_key(seg: dict) -> tuple[str, str | None, int | None, int]:
    """Normalize planned segment (dict) to comparable tuple."""
    return (
        seg.get("segment_type", ""),
        seg.get("asset_uri") if seg.get("asset_uri") else None,
        seg.get("asset_start_offset_ms") if "asset_start_offset_ms" in seg else None,
        seg.get("segment_duration_ms", 0),
    )


def _asrun_segment_key(seg: AsRunSegment) -> tuple[str, str | None, int | None, int]:
    """Normalize as-run segment to comparable tuple."""
    return (
        seg.segment_type,
        seg.asset_uri,
        seg.asset_start_offset_ms,
        seg.segment_duration_ms,
    )


def reconcile_transmission_log(
    transmission_log: TransmissionLog,
    as_run_log: AsRunLog,
) -> ReconciliationReport:
    """
    Compare TransmissionLog (plan) to AsRunLog (actual). Enforce INV-ASRUN-001..005.

    Deterministic. Does not mutate inputs.     Does not depend on Horizon or AIR.
    Returns structured report; does not auto-correct.
    """
    errors: list[str] = []
    classification: list[str] = []

    plan_by_id: dict[str, TransmissionLogEntry] = {
        e.block_id: e for e in transmission_log.entries
    }
    asrun_blocks_by_id: list[tuple[str, AsRunBlock]] = [
        (b.block_id, b) for b in as_run_log.blocks
    ]
    asrun_block_ids = [bid for bid, _ in asrun_blocks_by_id]
    asrun_id_to_blocks: dict[str, list[AsRunBlock]] = {}
    for bid, blk in asrun_blocks_by_id:
        asrun_id_to_blocks.setdefault(bid, []).append(blk)

    # INV-ASRUN-001: Block coverage
    for plan_id in plan_by_id:
        if plan_id not in asrun_id_to_blocks:
            errors.append(f"Missing as-run block for planned block_id={plan_id!r}")
            if "MISSING_BLOCK" not in classification:
                classification.append("MISSING_BLOCK")
    for bid, blks in asrun_id_to_blocks.items():
        if bid not in plan_by_id:
            errors.append(f"Extra as-run block not in plan: block_id={bid!r}")
            if "EXTRA_BLOCK" not in classification:
                classification.append("EXTRA_BLOCK")
        elif len(blks) > 1:
            errors.append(f"Duplicate block_id in as-run: block_id={bid!r}")
            if "EXTRA_BLOCK" not in classification:
                classification.append("EXTRA_BLOCK")

    # Build 1:1 mapping plan block_id -> single as-run block (for timing and segment checks)
    matched: dict[str, tuple[TransmissionLogEntry, AsRunBlock]] = {}
    for bid, plan_entry in plan_by_id.items():
        blks = asrun_id_to_blocks.get(bid, [])
        if len(blks) == 1:
            matched[bid] = (plan_entry, blks[0])
        # else: already reported missing or duplicate

    # INV-ASRUN-002: Block timing fidelity
    for bid, (plan_entry, asrun_block) in matched.items():
        if asrun_block.start_utc_ms != plan_entry.start_utc_ms:
            errors.append(
                f"Block {bid!r}: start_utc_ms mismatch "
                f"(planned={plan_entry.start_utc_ms}, as_run={asrun_block.start_utc_ms})"
            )
            if "BLOCK_TIME_MISMATCH" not in classification:
                classification.append("BLOCK_TIME_MISMATCH")
        if asrun_block.end_utc_ms != plan_entry.end_utc_ms:
            errors.append(
                f"Block {bid!r}: end_utc_ms mismatch "
                f"(planned={plan_entry.end_utc_ms}, as_run={asrun_block.end_utc_ms})"
            )
            if "BLOCK_TIME_MISMATCH" not in classification:
                classification.append("BLOCK_TIME_MISMATCH")

    # INV-ASRUN-003, INV-ASRUN-004: Segment sequence and no phantoms
    for bid, (plan_entry, asrun_block) in matched.items():
        planned_segments = [_planned_segment_key(s) for s in plan_entry.segments]
        # As-run segments not marked runtime_recovery must match plan in order
        asrun_non_recovery: list[AsRunSegment] = [
            s for s in asrun_block.segments if not s.runtime_recovery
        ]
        asrun_recovery_count = sum(1 for s in asrun_block.segments if s.runtime_recovery)
        if asrun_recovery_count > 0 and "RUNTIME_RECOVERY" not in classification:
            classification.append("RUNTIME_RECOVERY")
        asrun_runway_degradation_count = sum(
            1 for s in asrun_block.segments
            if s.runtime_recovery and s.runway_degradation
        )
        if asrun_runway_degradation_count > 0 and "RUNWAY_DEGRADATION" not in classification:
            classification.append("RUNWAY_DEGRADATION")

        plan_idx = 0
        for aseg in asrun_non_recovery:
            if plan_idx >= len(planned_segments):
                errors.append(
                    f"Block {bid!r}: phantom segment "
                    f"(segment_type={aseg.segment_type!r}, no matching planned segment)"
                )
                if "PHANTOM_SEGMENT" not in classification:
                    classification.append("PHANTOM_SEGMENT")
                continue
            planned_key = planned_segments[plan_idx]
            asrun_key = _asrun_segment_key(aseg)
            if asrun_key != planned_key:
                errors.append(
                    f"Block {bid!r}: segment sequence mismatch at index {plan_idx} "
                    f"(planned={planned_key!r}, as_run={asrun_key!r})"
                )
                if "SEGMENT_SEQUENCE_MISMATCH" not in classification:
                    classification.append("SEGMENT_SEQUENCE_MISMATCH")
            plan_idx += 1
        if plan_idx < len(planned_segments):
            errors.append(
                f"Block {bid!r}: missing {len(planned_segments) - plan_idx} planned segment(s) in as-run"
            )
            if "SEGMENT_SEQUENCE_MISMATCH" not in classification:
                classification.append("SEGMENT_SEQUENCE_MISMATCH")

    success = len(errors) == 0
    return ReconciliationReport(success=success, errors=errors, classification=classification)
