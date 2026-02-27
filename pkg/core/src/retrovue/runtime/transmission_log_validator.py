"""Transmission Log Seam Validator — Contract Enforcement

Validates TransmissionLog seam invariants before execution eligibility.
See: docs/contracts/core/TransmissionLogSeamContract_v0.1.md

Pure artifact validation. No AIR dependencies. No side effects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from retrovue.runtime.planning_pipeline import TransmissionLog


class TransmissionLogSeamError(Exception):
    """Raised when TransmissionLog violates seam invariants."""

    pass


def validate_transmission_log_seams(
    log: TransmissionLog,
    grid_block_minutes: int,
) -> None:
    """Enforce seam invariants on a TransmissionLog.

    Raises TransmissionLogSeamError if any invariant is violated.

    Invariants enforced:
    - INV-TL-SEAM-001: Contiguous boundaries (no gaps or overlaps)
    - INV-TL-SEAM-002: Grid duration consistency
    - INV-TL-SEAM-003: Monotonic ordering
    - INV-TL-SEAM-004: Non-zero duration per entry
    """
    entries = log.entries
    expected_dur_ms = grid_block_minutes * 60 * 1000

    for i, entry in enumerate(entries):
        # INV-TL-SEAM-004 — Non-zero duration
        if entry.end_utc_ms <= entry.start_utc_ms:
            raise TransmissionLogSeamError(
                f"INV-TL-SEAM-004 violated: entry[{i}] (block_id={entry.block_id}) "
                f"has non-positive duration: start_utc_ms={entry.start_utc_ms}, "
                f"end_utc_ms={entry.end_utc_ms}"
            )

        # INV-TL-SEAM-002 — Grid duration consistency
        actual_dur_ms = entry.end_utc_ms - entry.start_utc_ms
        if actual_dur_ms != expected_dur_ms:
            raise TransmissionLogSeamError(
                f"INV-TL-SEAM-002 violated: entry[{i}] (block_id={entry.block_id}) "
                f"duration {actual_dur_ms} ms != expected "
                f"grid_block_minutes*60*1000 = {expected_dur_ms} ms"
            )

        # INV-TL-SEAM-003 — Monotonic ordering (implied by INV-TL-SEAM-004 for single entry)
        # INV-TL-SEAM-001 — Contiguous boundaries
        if i + 1 < len(entries):
            next_entry = entries[i + 1]
            if entry.end_utc_ms != next_entry.start_utc_ms:
                raise TransmissionLogSeamError(
                    f"INV-TL-SEAM-001 violated: entry[{i}].end_utc_ms={entry.end_utc_ms} "
                    f"!= entry[{i+1}].start_utc_ms={next_entry.start_utc_ms}; "
                    f"gaps or overlaps not allowed"
                )
            if next_entry.start_utc_ms <= entry.start_utc_ms:
                raise TransmissionLogSeamError(
                    f"INV-TL-SEAM-003 violated: entry[{i+1}] not strictly after entry[{i}]; "
                    f"start_utc_ms ordering violated"
                )


def validate_transmission_log_grid_alignment(
    log: TransmissionLog,
    grid_block_minutes: int,
) -> None:
    """Enforce grid alignment on all TransmissionLogEntry boundaries.

    Raises ValueError if any entry start or end time does not fall on a
    grid boundary (i.e. is not divisible by grid_block_minutes * 60_000 ms).

    Invariant enforced:
    - INV-PLAYLIST-GRID-ALIGNMENT-001: All TransmissionLogEntry boundaries
      must align to the channel grid.

    Empty entry lists pass trivially.
    """
    grid_ms = grid_block_minutes * 60 * 1000

    for i, entry in enumerate(log.entries):
        for label, value_ms in (
            ("start_utc_ms", entry.start_utc_ms),
            ("end_utc_ms", entry.end_utc_ms),
        ):
            if value_ms % grid_ms != 0:
                floor_ms = (value_ms // grid_ms) * grid_ms
                ceil_ms = floor_ms + grid_ms
                raise ValueError(
                    f"INV-PLAYLIST-GRID-ALIGNMENT-001-VIOLATED: "
                    f"entry[{i}] (block_id={entry.block_id}) "
                    f"{label}={value_ms} is not aligned to "
                    f"{grid_block_minutes}-minute grid. "
                    f"Nearest valid boundaries: "
                    f"floor={floor_ms}, ceil={ceil_ms}"
                )
