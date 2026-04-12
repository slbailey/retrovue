"""
Contract tests for INV-NO-MID-PROGRAM-CUT-001.

Programs without breakpoints must not be cut mid-play in any derived
artifact. Their full runtime must be consumed within contiguous blocks.

CROSS-001 (Tier 2): 90-min breakpoint-free program spans 3 blocks, no cut.
CROSS-002 (Tier 2): 120-min breakpoint-free longform spans 4 blocks, no cut.
"""

from __future__ import annotations

import pytest

from retrovue.scheduling.midcut_validation import (
    ProgramPlacement,
    validate_no_mid_program_cut,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GRID_30_MIN_MS = 30 * 60 * 1000  # 1_800_000
EPOCH_MS = 0  # Use offset 0 for simplicity


# ---------------------------------------------------------------------------
# CROSS-001: 90-min breakpoint-free program
# ---------------------------------------------------------------------------

class TestInvNoMidProgramCut001:
    """Contract tests for INV-NO-MID-PROGRAM-CUT-001."""

    def test_cross_001_90min_no_breakpoints_no_cut(self):
        """CROSS-001: A 90-minute breakpoint-free program placed in a zone
        [18:00, 22:00] against a 30-minute grid. PlaylistEvent generation
        must not cut it mid-program.

        The program consumes 3 whole 30-minute grid blocks [18:00–19:30].
        No playlist entry boundary falls inside the program's duration.
        """
        eighteen_hundred = 18 * 60 * 60 * 1000  # 18:00 in ms

        placement = ProgramPlacement(
            program_id="longform-90min",
            duration_ms=90 * 60 * 1000,  # 90 minutes
            breakpoints=[],
            start_utc_ms=eighteen_hundred,
            block_count=3,
        )

        # Playlist boundaries: program starts at 18:00, ends at 19:30.
        # Other entries fill [19:30, 22:00] in 30-min blocks.
        boundaries = [
            eighteen_hundred,                           # 18:00 — program start
            eighteen_hundred + 90 * 60 * 1000,          # 19:30 — program end
            eighteen_hundred + 120 * 60 * 1000,         # 20:00
            eighteen_hundred + 150 * 60 * 1000,         # 20:30
            eighteen_hundred + 180 * 60 * 1000,         # 21:00
            eighteen_hundred + 210 * 60 * 1000,         # 21:30
            eighteen_hundred + 240 * 60 * 1000,         # 22:00
        ]

        # Must not raise — no cut within the 90-min program
        validate_no_mid_program_cut(
            placements=[placement],
            grid_block_ms=GRID_30_MIN_MS,
            playlist_boundaries=sorted(boundaries),
        )

    def test_cross_001_90min_cut_detected(self):
        """CROSS-001 (negative): If a playlist boundary falls inside the
        90-minute program (e.g., at 18:30), the violation is detected."""
        eighteen_hundred = 18 * 60 * 60 * 1000

        placement = ProgramPlacement(
            program_id="longform-90min",
            duration_ms=90 * 60 * 1000,
            breakpoints=[],
            start_utc_ms=eighteen_hundred,
            block_count=3,
        )

        # Bad boundaries: a cut at 18:30 inside the program
        boundaries = [
            eighteen_hundred,
            eighteen_hundred + 30 * 60 * 1000,  # 18:30 — CUT inside program!
            eighteen_hundred + 90 * 60 * 1000,  # 19:30
        ]

        with pytest.raises(ValueError, match="INV-NO-MID-PROGRAM-CUT-001-VIOLATED"):
            validate_no_mid_program_cut(
                placements=[placement],
                grid_block_ms=GRID_30_MIN_MS,
                playlist_boundaries=sorted(boundaries),
            )

    # -------------------------------------------------------------------
    # CROSS-002: 120-min breakpoint-free longform
    # -------------------------------------------------------------------

    def test_cross_002_120min_spans_4_blocks_no_cut(self):
        """CROSS-002: A 120-minute breakpoint-free longform placed in zone
        [20:00, 24:00]. It spans 4 contiguous grid blocks.
        No cut exists within the program boundary.
        """
        twenty_hundred = 20 * 60 * 60 * 1000

        placement = ProgramPlacement(
            program_id="longform-120min",
            duration_ms=120 * 60 * 1000,  # 120 minutes
            breakpoints=[],
            start_utc_ms=twenty_hundred,
            block_count=4,
        )

        # Playlist boundaries: program fills [20:00, 22:00] as a single entry
        boundaries = [
            twenty_hundred,                            # 20:00 — program start
            twenty_hundred + 120 * 60 * 1000,          # 22:00 — program end
        ]

        # Must not raise
        validate_no_mid_program_cut(
            placements=[placement],
            grid_block_ms=GRID_30_MIN_MS,
            playlist_boundaries=sorted(boundaries),
        )

    def test_cross_002_120min_cut_detected(self):
        """CROSS-002 (negative): If a playlist boundary falls inside the
        120-minute longform (e.g., at 21:00), the violation is detected."""
        twenty_hundred = 20 * 60 * 60 * 1000

        placement = ProgramPlacement(
            program_id="longform-120min",
            duration_ms=120 * 60 * 1000,
            breakpoints=[],
            start_utc_ms=twenty_hundred,
            block_count=4,
        )

        boundaries = [
            twenty_hundred,
            twenty_hundred + 60 * 60 * 1000,   # 21:00 — CUT inside program!
            twenty_hundred + 120 * 60 * 1000,   # 22:00
        ]

        with pytest.raises(ValueError, match="INV-NO-MID-PROGRAM-CUT-001-VIOLATED"):
            validate_no_mid_program_cut(
                placements=[placement],
                grid_block_ms=GRID_30_MIN_MS,
                playlist_boundaries=sorted(boundaries),
            )

    def test_program_with_breakpoints_allows_cut(self):
        """Programs WITH breakpoints may be cut at declared positions.
        This validates the exemption path."""
        start = 18 * 60 * 60 * 1000

        placement = ProgramPlacement(
            program_id="program-with-breaks",
            duration_ms=90 * 60 * 1000,
            breakpoints=[30 * 60 * 1000],  # Break at 30 minutes
            start_utc_ms=start,
            block_count=3,
        )

        # A boundary at 18:30 is fine because the program has a breakpoint there
        boundaries = [
            start,
            start + 30 * 60 * 1000,   # 18:30 — at declared breakpoint
            start + 90 * 60 * 1000,   # 19:30
        ]

        # Must not raise — breakpoint allows the cut
        validate_no_mid_program_cut(
            placements=[placement],
            grid_block_ms=GRID_30_MIN_MS,
            playlist_boundaries=sorted(boundaries),
        )
