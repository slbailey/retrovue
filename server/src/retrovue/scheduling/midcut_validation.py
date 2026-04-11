"""Mid-program cut validation.

Enforces INV-NO-MID-PROGRAM-CUT-001: Programs without breakpoints
must not be cut mid-play in any derived artifact.

A program with no declared breakpoints is an indivisible editorial unit.
Its full runtime must be consumed within contiguous grid blocks.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProgramPlacement:
    """A program placement in a schedule with its runtime and breakpoints."""

    program_id: str
    duration_ms: int
    breakpoints: list[int]  # list of ms offsets where breaks are allowed
    start_utc_ms: int
    block_count: int  # how many grid blocks the program occupies


def validate_no_mid_program_cut(
    *,
    placements: list[ProgramPlacement],
    grid_block_ms: int,
    playlist_boundaries: list[int],
) -> None:
    """Validate that no playlist boundary falls inside a breakpoint-free program.

    For each program with no breakpoints, checks that no playlist entry
    boundary exists between the program's start and end (exclusive of
    the start and end themselves).

    Args:
        placements: Programs placed in the schedule with their timings.
        grid_block_ms: Grid block duration in milliseconds.
        playlist_boundaries: Sorted list of all playlist entry boundary
            timestamps (start and end times of every entry).

    Raises ValueError if a cut exists within a breakpoint-free program.
    """
    boundary_set = set(playlist_boundaries)

    for p in placements:
        if p.breakpoints:
            continue  # Has breakpoints — cuts allowed at those points

        # The program spans [start, start + duration_ms)
        # No boundary should fall strictly inside this range
        program_end = p.start_utc_ms + p.duration_ms

        for boundary in boundary_set:
            if p.start_utc_ms < boundary < program_end:
                # This boundary is inside the program — is it a grid boundary
                # that the program is supposed to span?
                # A grid boundary is OK only if the program consumes whole blocks.
                # But a playlist entry boundary INSIDE the program means the
                # program was split into multiple entries — that's the cut.
                #
                # Grid block boundaries that the program spans are fine for
                # grid accounting, but a playlist entry should not START or END
                # at these mid-program points.
                offset_from_start = boundary - p.start_utc_ms
                raise ValueError(
                    f"INV-NO-MID-PROGRAM-CUT-001-VIOLATED: "
                    f"program '{p.program_id}' ({p.duration_ms}ms, no breakpoints) "
                    f"has a cut at offset {offset_from_start}ms "
                    f"(boundary at {boundary}ms). "
                    f"Breakpoint-free programs must not be interrupted mid-play."
                )
