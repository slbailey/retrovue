"""Compile-time validators for the production schedule path.

These validators run during DSL compilation (in _compile_day) to catch
compiler bugs before bad data enters the playlog. They operate on
ScheduledBlock lists — the production path's native type.

Architectural decision (2026-04-09): The formal derivation chain
(derive_transmission_log -> derive_execution_entries) remains test-only.
The production path (DSL -> compiler -> ScheduleRevision -> PlaylistEvent
-> ScheduledBlock) is equivalent but distinct. These validators enforce
the same scheduling invariants on production types.

Invariants enforced:
    INV-COMPILED-BLOCK-CONTIGUITY-001: No temporal gaps between adjacent
        compiled blocks within a broadcast day.
    INV-COMPILED-GRID-ALIGNMENT-001: Block boundaries align to grid after
        ScheduleRevision write (post-compaction check).
"""

from __future__ import annotations

from retrovue.runtime.schedule_types import ScheduledBlock


def validate_compiled_block_contiguity(
    blocks: list[ScheduledBlock],
) -> None:
    """Validate no temporal gaps between adjacent compiled blocks.

    Production-path equivalent of validate_scheduleday_contiguity().
    Checks that each block's end_utc_ms equals the next block's
    start_utc_ms — the broadcast day is a linked list with no holes.

    Raises ValueError with INV-COMPILED-BLOCK-CONTIGUITY-001-VIOLATED
    on any gap.
    """
    if not blocks:
        return  # Empty block list is valid (write may be refused)

    sorted_blocks = sorted(blocks, key=lambda b: b.start_utc_ms)

    for i in range(len(sorted_blocks) - 1):
        current = sorted_blocks[i]
        next_block = sorted_blocks[i + 1]

        if current.end_utc_ms != next_block.start_utc_ms:
            gap_ms = next_block.start_utc_ms - current.end_utc_ms
            raise ValueError(
                f"INV-COMPILED-BLOCK-CONTIGUITY-001-VIOLATED: "
                f"gap of {gap_ms}ms between block {current.block_id} "
                f"(end={current.end_utc_ms}ms) and block "
                f"{next_block.block_id} (start={next_block.start_utc_ms}ms)"
            )


def validate_compiled_grid_alignment(
    blocks: list[ScheduledBlock],
    grid_ms: int,
) -> None:
    """Validate block boundaries align to the scheduling grid.

    Post-expansion check: every block start_utc_ms must be a multiple
    of grid_ms relative to the first block's start (the broadcast day
    anchor). This catches rounding errors introduced during expansion.

    Raises ValueError with INV-COMPILED-GRID-ALIGNMENT-001-VIOLATED
    on misalignment.
    """
    if not blocks or grid_ms <= 0:
        return

    anchor_ms = blocks[0].start_utc_ms

    for block in blocks:
        offset = block.start_utc_ms - anchor_ms
        if offset % grid_ms != 0:
            raise ValueError(
                f"INV-COMPILED-GRID-ALIGNMENT-001-VIOLATED: "
                f"block {block.block_id} start_utc_ms={block.start_utc_ms} "
                f"is not grid-aligned (offset {offset}ms from anchor "
                f"{anchor_ms}ms, grid={grid_ms}ms)"
            )
