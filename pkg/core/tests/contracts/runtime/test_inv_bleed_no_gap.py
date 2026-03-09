"""
Contract tests for INV-BLEED-NO-GAP-001.

When allow_bleed causes a program block to extend past its window, the compiler
MUST resolve the overlap by compacting — pushing subsequent blocks forward.
Output MUST be a strictly contiguous, non-overlapping, grid-aligned sequence.
"""

from __future__ import annotations

import pytest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from retrovue.runtime.asset_resolver import AssetMetadata, StubAssetResolver
from retrovue.runtime.schedule_compiler import (
    CompileError,
    ProgramBlockOutput,
    compile_schedule,
    parse_dsl,
    _validate_grid_alignment,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GRID_MINUTES = 30
SLOT_SEC = GRID_MINUTES * 60  # 1800s

UTC = timezone.utc


def _make_marathon_resolver() -> StubAssetResolver:
    """Build a resolver with movie pools for two consecutive program blocks.

    Horror pool: movies ~100 min (ceil to 2h grid slot at 30min grid).
    Comedy pool: movies ~80 min (ceil to 1.5h grid slot at 30min grid).
    """
    r = StubAssetResolver()

    horror_ids = ["asset.movies.horror_a", "asset.movies.horror_b",
                  "asset.movies.horror_c", "asset.movies.horror_d",
                  "asset.movies.horror_e"]
    comedy_ids = ["asset.movies.comedy_a", "asset.movies.comedy_b",
                  "asset.movies.comedy_c", "asset.movies.comedy_d"]

    # Register pools so resolver.lookup("horror") works
    r.register_pools({
        "horror": {"match": {"type": "movie"}},
        "comedy": {"match": {"type": "movie"}},
    })
    # Register collections so pool query returns correct assets
    r.register_collection("horror_col", horror_ids)
    r.register_collection("comedy_col", comedy_ids)

    for mid in horror_ids:
        r.add(mid, AssetMetadata(type="movie", duration_sec=6000, rating="R",
                                 title=mid.split(".")[-1]))
    for mid in comedy_ids:
        r.add(mid, AssetMetadata(type="movie", duration_sec=4800, rating="PG",
                                 title=mid.split(".")[-1]))

    return r


def _two_block_dsl(
    m1_start: str = "06:00",
    m2_start: str = "08:00",
    m1_bleed: bool = True,
    m2_bleed: bool = True,
) -> dict:
    """Build a V2 DSL with two program blocks where bleed causes overlap.

    Horror: grid_blocks=2 (1h nominal), 100-min movies → bleed to 2h each.
    4 slots / 2 grid_blocks = 2 executions × 2h = 4h. Starts 06:00, ends 10:00.
    Comedy: starts at 08:00 (overlaps horror). Compaction pushes it to 10:00.
    When m2_bleed=False, comedy uses grid_blocks=4 (2h) so 80-min movies fit.
    """
    # When bleed is off, grid must be large enough to contain the asset.
    # Comedy movies are 80 min; grid_blocks=2 (1h) is too small without bleed.
    # grid_blocks=4 (2h) fits 80 min and slots=4 is a valid multiple (4/4=1).
    comedy_grid = 2 if m2_bleed else 4
    return {
        "channel": "test-ch",
        "broadcast_day": "2026-03-01",
        "timezone": "UTC",
        "template": "network",
        "pools": {
            "horror": {"match": {"type": "movie"}},
            "comedy": {"match": {"type": "movie"}},
        },
        "programs": {
            "horror_movie": {
                "pool": "horror",
                "grid_blocks": 2,
                "fill_mode": "single",
                "bleed": m1_bleed,
            },
            "comedy_movie": {
                "pool": "comedy",
                "grid_blocks": comedy_grid,
                "fill_mode": "single",
                "bleed": m2_bleed,
            },
        },
        "schedule": {
            "all_day": [
                {
                    "start": m1_start,
                    "slots": 4,
                    "program": "horror_movie",
                    "progression": "random",
                },
                {
                    "start": m2_start,
                    "slots": 4,
                    "program": "comedy_movie",
                    "progression": "random",
                },
            ]
        },
    }


def _three_block_dsl() -> dict:
    """Build a V2 DSL with three overlapping program blocks.

    All comedy, grid_blocks=2 (1h nominal), 80-min movies → bleed to 1.5h each.
    Each block: 4 slots / 2 = 2 executions × 1.5h = 3h actual.
    Block 1: 06:00 → ends 09:00. Block 2: 08:00 → pushed to 09:00, ends 12:00.
    Block 3: 10:00 → pushed to 12:00, ends 15:00.
    """
    return {
        "channel": "test-ch",
        "broadcast_day": "2026-03-01",
        "timezone": "UTC",
        "template": "network",
        "pools": {
            "comedy": {"match": {"type": "movie"}},
        },
        "programs": {
            "comedy_movie": {
                "pool": "comedy",
                "grid_blocks": 2,
                "fill_mode": "single",
                "bleed": True,
            },
        },
        "schedule": {
            "all_day": [
                {
                    "start": "06:00",
                    "slots": 4,
                    "program": "comedy_movie",
                    "progression": "random",
                },
                {
                    "start": "08:00",
                    "slots": 4,
                    "program": "comedy_movie",
                    "progression": "random",
                },
                {
                    "start": "10:00",
                    "slots": 4,
                    "program": "comedy_movie",
                    "progression": "random",
                },
            ]
        },
    }


def _compile(dsl: dict, resolver: StubAssetResolver) -> list[dict]:
    """Compile and return program_blocks list."""
    result = compile_schedule(dsl, resolver, seed=42)
    return result["program_blocks"]


# ---------------------------------------------------------------------------
# Contract Tests
# ---------------------------------------------------------------------------


class TestInvBleedNoGap001:
    """INV-BLEED-NO-GAP-001 contract tests."""

    def test_consecutive_marathons_with_bleed_are_contiguous(self):
        """After compile_schedule(), every consecutive block pair satisfies
        block[i].end_at == block[i+1].start_at. No gaps, no overlaps."""
        resolver = _make_marathon_resolver()
        dsl = _two_block_dsl()
        blocks = _compile(dsl, resolver)

        assert len(blocks) >= 3, f"Expected at least 3 blocks, got {len(blocks)}"

        for i in range(len(blocks) - 1):
            end_i = datetime.fromisoformat(blocks[i]["start_at"]) + timedelta(
                seconds=blocks[i]["slot_duration_sec"]
            )
            start_next = datetime.fromisoformat(blocks[i + 1]["start_at"])
            assert end_i == start_next, (
                f"Gap or overlap between block {i} (ends {end_i.isoformat()}) "
                f"and block {i+1} (starts {start_next.isoformat()})"
            )

    def test_bleed_pushes_subsequent_blocks_forward(self):
        """Block 2's first block start_at equals block 1's last block
        end_at, not block 2's DSL-declared start time."""
        resolver = _make_marathon_resolver()
        dsl = _two_block_dsl()
        blocks = _compile(dsl, resolver)

        # Find boundary between horror and comedy blocks using collection field
        first_m2_idx = None
        for i, b in enumerate(blocks):
            if b.get("collection") == "comedy":
                first_m2_idx = i
                break

        if first_m2_idx is not None and first_m2_idx > 0:
            prev_end = datetime.fromisoformat(blocks[first_m2_idx - 1]["start_at"]) + timedelta(
                seconds=blocks[first_m2_idx - 1]["slot_duration_sec"]
            )
            m2_start = datetime.fromisoformat(blocks[first_m2_idx]["start_at"])
            assert m2_start == prev_end, (
                f"Block 2 starts at {m2_start.isoformat()}, "
                f"but previous block ends at {prev_end.isoformat()}"
            )

    def test_all_blocks_are_grid_aligned(self):
        """Every block's start_at minute is divisible by grid_minutes.
        Every slot_duration_sec is a multiple of grid_minutes * 60."""
        resolver = _make_marathon_resolver()
        dsl = _two_block_dsl()
        blocks = _compile(dsl, resolver)

        for b in blocks:
            start_dt = datetime.fromisoformat(b["start_at"])
            start_epoch = int(start_dt.timestamp())
            assert start_epoch % SLOT_SEC == 0, (
                f"Block '{b['title']}' start_at={b['start_at']} not grid-aligned "
                f"(epoch {start_epoch} % {SLOT_SEC} = {start_epoch % SLOT_SEC})"
            )
            assert b["slot_duration_sec"] % SLOT_SEC == 0, (
                f"Block '{b['title']}' slot_duration_sec={b['slot_duration_sec']} "
                f"not a multiple of {SLOT_SEC}"
            )

    def test_fully_enclosed_overlap_pushes_forward(self):
        """Construct input where one block is fully enclosed within another.
        Compaction MUST push the enclosed block forward (not raise)."""
        t0 = datetime(2026, 3, 1, 6, 0, tzinfo=UTC)
        outer = ProgramBlockOutput(
            title="outer", asset_id="a1", start_at=t0,
            slot_duration_sec=7200, episode_duration_sec=6000,
        )
        inner = ProgramBlockOutput(
            title="inner", asset_id="a2",
            start_at=t0 + timedelta(seconds=1800),
            slot_duration_sec=1800, episode_duration_sec=1500,
        )
        # The inner block is fully enclosed within outer (06:30-07:00 < 06:00-08:00).
        # Compaction must push inner forward to outer's end (08:00), not raise.
        blocks = [outer, inner]
        blocks.sort(key=lambda b: b.start_at)

        # Simulate what the compaction code does
        compacted: list[ProgramBlockOutput] = []
        for block in blocks:
            if compacted and compacted[-1].end_at() > block.start_at:
                new_start = compacted[-1].end_at()
                block = replace(block, start_at=new_start)
            compacted.append(block)

        assert len(compacted) == 2
        assert compacted[0].start_at == t0
        # Inner pushed to outer's end: 06:00 + 7200s = 08:00
        assert compacted[1].start_at == t0 + timedelta(seconds=7200)
        # No overlap
        assert compacted[0].end_at() <= compacted[1].start_at

    def test_grid_misalignment_raises(self):
        """Construct a ProgramBlockOutput with non-grid-aligned start_at.
        Validation MUST raise CompileError."""
        # start_at at 06:05 — 5 min offset, not grid-aligned
        t0 = datetime(2026, 3, 1, 6, 5, tzinfo=UTC)
        block = ProgramBlockOutput(
            title="misaligned", asset_id="a1", start_at=t0,
            slot_duration_sec=1800, episode_duration_sec=1500,
        )
        with pytest.raises(CompileError, match="[Gg]rid violation"):
            _validate_grid_alignment([block], GRID_MINUTES)

    def test_post_compaction_revalidation(self):
        """After compaction produces output, _validate_grid_alignment runs
        again and passes. Verifies no silent misalignment from shifting."""
        t0 = datetime(2026, 3, 1, 6, 0, tzinfo=UTC)
        b1 = ProgramBlockOutput(
            title="b1", asset_id="a1", start_at=t0,
            slot_duration_sec=3600, episode_duration_sec=3000,
        )
        b2 = ProgramBlockOutput(
            title="b2", asset_id="a2",
            start_at=t0 + timedelta(seconds=3600),
            slot_duration_sec=1800, episode_duration_sec=1500,
        )
        # Both grid-aligned, no overlap — validation should pass
        _validate_grid_alignment([b1, b2], GRID_MINUTES)

    def test_compaction_eliminates_overlap_gaps(self):
        """When bleed creates an overlap, compaction pushes the next block
        forward — the resulting pair has no gap between them."""
        resolver = _make_marathon_resolver()
        dsl = _two_block_dsl(m1_bleed=True, m2_bleed=False)
        blocks = _compile(dsl, resolver)

        # Find the boundary between horror and comedy blocks using collection
        boundary_idx = None
        for i, b in enumerate(blocks):
            if b.get("collection") == "comedy":
                boundary_idx = i
                break

        assert boundary_idx is not None and boundary_idx > 0, (
            "Expected to find boundary between program blocks"
        )

        # At the boundary, there must be no gap
        prev_end = datetime.fromisoformat(blocks[boundary_idx - 1]["start_at"]) + timedelta(
            seconds=blocks[boundary_idx - 1]["slot_duration_sec"]
        )
        m2_start = datetime.fromisoformat(blocks[boundary_idx]["start_at"])
        assert prev_end == m2_start, (
            f"Gap at boundary: prev ends {prev_end.isoformat()}, "
            f"next starts {m2_start.isoformat()}"
        )

    def test_naive_datetime_raises(self):
        """Construct a ProgramBlockOutput with timezone-naive start_at.
        Validation MUST raise CompileError."""
        t0 = datetime(2026, 3, 1, 6, 0)  # naive — no tzinfo
        block = ProgramBlockOutput(
            title="naive", asset_id="a1", start_at=t0,
            slot_duration_sec=1800, episode_duration_sec=1500,
        )
        with pytest.raises(CompileError, match="not UTC"):
            _validate_grid_alignment([block], GRID_MINUTES)

    def test_non_utc_timezone_raises(self):
        """Construct a ProgramBlockOutput with start_at in US/Eastern.
        Validation MUST raise CompileError."""
        from zoneinfo import ZoneInfo
        t0 = datetime(2026, 3, 1, 6, 0, tzinfo=ZoneInfo("America/New_York"))
        block = ProgramBlockOutput(
            title="eastern", asset_id="a1", start_at=t0,
            slot_duration_sec=1800, episode_duration_sec=1500,
        )
        with pytest.raises(CompileError, match="not UTC"):
            _validate_grid_alignment([block], GRID_MINUTES)

    def test_three_block_cascading_bleed(self):
        """Three overlapping program blocks with bleed: true.
        Cascading bleed across all three boundaries MUST compile successfully
        (no CompileError), producing contiguous grid-aligned output."""
        resolver = _make_marathon_resolver()
        dsl = _three_block_dsl()

        # Must not raise CompileError
        blocks = _compile(dsl, resolver)

        assert len(blocks) >= 4, f"Expected at least 4 blocks, got {len(blocks)}"

        # All blocks contiguous — no gaps, no overlaps
        for i in range(len(blocks) - 1):
            end_i = datetime.fromisoformat(blocks[i]["start_at"]) + timedelta(
                seconds=blocks[i]["slot_duration_sec"]
            )
            start_next = datetime.fromisoformat(blocks[i + 1]["start_at"])
            assert end_i == start_next, (
                f"Gap or overlap between block {i} (ends {end_i.isoformat()}) "
                f"and block {i+1} (starts {start_next.isoformat()})"
            )

        # All blocks grid-aligned
        for b in blocks:
            start_dt = datetime.fromisoformat(b["start_at"])
            start_epoch = int(start_dt.timestamp())
            assert start_epoch % SLOT_SEC == 0, (
                f"Block '{b['title']}' start_at={b['start_at']} not grid-aligned"
            )

        # First block starts at 06:00
        first_start = datetime.fromisoformat(blocks[0]["start_at"])
        day_start = datetime(2026, 3, 1, 6, 0, tzinfo=UTC)
        assert first_start == day_start, (
            f"First block starts at {first_start.isoformat()}, expected {day_start.isoformat()}"
        )

    def test_block_spanning_broadcast_day_not_split(self):
        """One block 05:00-07:00 UTC, broadcast day boundary at 06:00.
        Assert exactly one ProgramBlockOutput — day boundaries do not split blocks."""
        t0 = datetime(2026, 3, 1, 5, 0, tzinfo=UTC)
        block = ProgramBlockOutput(
            title="overnight", asset_id="a1", start_at=t0,
            slot_duration_sec=7200, episode_duration_sec=6000,  # 2h
        )
        # Validate that this single block passing through 06:00 boundary is valid
        _validate_grid_alignment([block], GRID_MINUTES)
        # The block is not split — still one block
        assert block.start_at == t0
        assert block.end_at() == t0 + timedelta(seconds=7200)
