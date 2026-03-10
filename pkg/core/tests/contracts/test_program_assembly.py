"""Contract tests for program_assembly — the V2 pipeline bridge.

Validates that assemble_schedule_block correctly bridges the schedule
compiler (progression, timing) with program_definition (fill_mode,
bleed, intro/outro) using a real AssetResolver.

Invariants tested:
    INV-PROGRAM-GRID-001 — slots/grid_blocks multiple enforcement
    INV-PROGRAM-FILL-001 — single fill selects one asset per execution
    INV-PROGRAM-FILL-002 — accumulate stops at grid target
    INV-PROGRAM-BLEED-001 — non-bleeding rejects overlong content
    INV-PROGRAM-BLEED-002 — bleeding allows overrun
    INV-PROGRAM-INTRO-OUTRO-001 — intro/outro included in runtime
"""

from __future__ import annotations

import pytest

from retrovue.runtime.asset_resolver import AssetMetadata, StubAssetResolver
from retrovue.runtime.program_assembly import assemble_schedule_block
from retrovue.runtime.program_definition import AssemblyFault


GRID_MINUTES = 30


def _resolver_with_episodes(
    pool_name: str,
    episode_durations_sec: list[int],
) -> StubAssetResolver:
    """Build a resolver with a pool of episodes at given durations."""
    resolver = StubAssetResolver()
    ep_ids = []
    for i, dur in enumerate(episode_durations_sec):
        aid = f"ep-{i:03d}"
        resolver.add(aid, AssetMetadata(
            type="episode",
            duration_sec=dur,
            title=f"Episode {i}",
        ))
        ep_ids.append(aid)
    # Register pool so resolver.lookup(pool_name) returns pool-type metadata
    resolver.register_pools({pool_name: {"match": {"type": "episode"}}})
    return resolver


# ===========================================================================
# INV-PROGRAM-GRID-001 — slots must be multiple of grid_blocks
# ===========================================================================


@pytest.mark.contract
class TestAssemblyGridValidation:

    def test_slots_not_multiple_raises(self):
        resolver = _resolver_with_episodes("sitcoms", [1500])
        with pytest.raises(AssemblyFault, match="INV-PROGRAM-GRID-001"):
            assemble_schedule_block(
                program_ref="test",
                program_def={"pool": "sitcoms", "grid_blocks": 2, "fill_mode": "single"},
                pool_name="sitcoms",
                slots=3,
                progression="sequential",
                grid_minutes=GRID_MINUTES,
                resolver=resolver,
            )

    def test_slots_exact_multiple_accepted(self):
        resolver = _resolver_with_episodes("sitcoms", [1500])
        results = assemble_schedule_block(
            program_ref="test",
            program_def={"pool": "sitcoms", "grid_blocks": 1, "fill_mode": "single"},
            pool_name="sitcoms",
            slots=4,
            progression="sequential",
            grid_minutes=GRID_MINUTES,
            resolver=resolver,
        )
        assert len(results) == 4


# ===========================================================================
# INV-PROGRAM-FILL-001 — single fill selects exactly one content asset
# ===========================================================================


@pytest.mark.contract
class TestAssemblySingleFill:

    def test_single_fill_one_asset_per_execution(self):
        resolver = _resolver_with_episodes("sitcoms", [1500, 1400, 1600])
        results = assemble_schedule_block(
            program_ref="half_hour",
            program_def={"pool": "sitcoms", "grid_blocks": 1, "fill_mode": "single"},
            pool_name="sitcoms",
            slots=2,
            progression="sequential",
            grid_minutes=GRID_MINUTES,
            resolver=resolver,
        )
        assert len(results) == 2
        for r in results:
            content = [s for s in r.segments if s.segment_type == "content"]
            assert len(content) == 1

    def test_single_fill_empty_pool_raises(self):
        resolver = StubAssetResolver()
        resolver.register_pools({"empty": {"match": {"type": "episode"}}})
        # Pool exists but has no assets
        with pytest.raises(AssemblyFault):
            assemble_schedule_block(
                program_ref="test",
                program_def={"pool": "empty", "grid_blocks": 1, "fill_mode": "single"},
                pool_name="empty",
                slots=1,
                progression="sequential",
                grid_minutes=GRID_MINUTES,
                resolver=resolver,
                bleed=True,
            )


# ===========================================================================
# INV-PROGRAM-FILL-002 — accumulate stops at grid target
# ===========================================================================


@pytest.mark.contract
class TestAssemblyAccumulateFill:

    def test_accumulate_fills_to_target(self):
        # grid_blocks=2 → target = 60min = 3600s
        # 3 episodes at 1500s each: 1500+1500=3000 < 3600, 1500+1500+1500=4500 >= 3600
        resolver = _resolver_with_episodes("sitcoms", [1500, 1500, 1500, 1500])
        results = assemble_schedule_block(
            program_ref="hour_block",
            program_def={"pool": "sitcoms", "grid_blocks": 2, "fill_mode": "accumulate"},
                bleed=True,
            pool_name="sitcoms",
            slots=2,
            progression="sequential",
            grid_minutes=GRID_MINUTES,
            resolver=resolver,
        )
        assert len(results) == 1  # 2 slots / 2 grid_blocks = 1 execution
        content = [s for s in results[0].segments if s.segment_type == "content"]
        assert len(content) == 3  # 3 episodes to reach 4500ms >= 3600ms target
        total_ms = sum(s.duration_ms for s in content)
        assert total_ms >= 3600 * 1000

    def test_accumulate_does_not_overshoot(self):
        # grid_blocks=2 → target = 3600s
        # Assets: 2000s, 1700s, 500s. 2000+1700=3700 >= 3600 → stop at 2.
        resolver = _resolver_with_episodes("sitcoms", [2000, 1700, 500])
        results = assemble_schedule_block(
            program_ref="hour_block",
            program_def={"pool": "sitcoms", "grid_blocks": 2, "fill_mode": "accumulate"},
                bleed=True,
            pool_name="sitcoms",
            slots=2,
            progression="sequential",
            grid_minutes=GRID_MINUTES,
            resolver=resolver,
        )
        content = [s for s in results[0].segments if s.segment_type == "content"]
        assert len(content) == 2


# ===========================================================================
# INV-PROGRAM-BLEED-001 — non-bleeding rejects overlong content
# ===========================================================================


@pytest.mark.contract
class TestAssemblyNoBleed:

    def test_no_bleed_single_rejects_overlong(self):
        # grid_blocks=1 → 1800s. 2000s episode exceeds. 1500s fits.
        resolver = _resolver_with_episodes("sitcoms", [2000, 1500])
        results = assemble_schedule_block(
            program_ref="test",
            program_def={"pool": "sitcoms", "grid_blocks": 1, "fill_mode": "single"},
            pool_name="sitcoms",
            slots=1,
            progression="sequential",
            grid_minutes=GRID_MINUTES,
            resolver=resolver,
        )
        assert len(results) == 1
        content = [s for s in results[0].segments if s.segment_type == "content"]
        assert content[0].asset_id == "ep-001"  # 1500s fits, 2000s rejected


# ===========================================================================
# INV-PROGRAM-BLEED-002 — bleeding allows overrun
# ===========================================================================


@pytest.mark.contract
class TestAssemblyBleed:

    def test_bleed_allows_overrun(self):
        # grid_blocks=1 → 1800s target. 2500s episode exceeds but bleed=true.
        resolver = _resolver_with_episodes("sitcoms", [2500])
        results = assemble_schedule_block(
            program_ref="test",
            program_def={"pool": "sitcoms", "grid_blocks": 1, "fill_mode": "single"},
                bleed=True,
            pool_name="sitcoms",
            slots=1,
            progression="sequential",
            grid_minutes=GRID_MINUTES,
            resolver=resolver,
        )
        assert len(results) == 1
        assert results[0].total_runtime_ms == 2500 * 1000


# ===========================================================================
# INV-PROGRAM-INTRO-OUTRO-001 — intro/outro included in runtime
# ===========================================================================


@pytest.mark.contract
class TestAssemblyIntroOutro:

    def test_intro_included_in_runtime(self):
        resolver = _resolver_with_episodes("sitcoms", [1500])
        # Add intro asset
        resolver.add("my_intro", AssetMetadata(
            type="bumper", duration_sec=30, title="Intro",
        ))
        results = assemble_schedule_block(
            program_ref="test",
            program_def={
                "pool": "sitcoms", "grid_blocks": 1,
                "fill_mode": "single",
                "intro": "my_intro",
            },
            pool_name="sitcoms",
            slots=1,
            progression="sequential",
            grid_minutes=GRID_MINUTES,
            resolver=resolver,
            bleed=True,
        )
        assert len(results) == 1
        # 30s intro + 1500s content = 1530s
        assert results[0].total_runtime_ms == 1530 * 1000
        segment_types = [s.segment_type for s in results[0].segments]
        assert segment_types[0] == "intro"
        assert segment_types[1] == "content"


# ===========================================================================
# Progression — sequential cursor advances across executions
# ===========================================================================


@pytest.mark.contract
class TestAssemblyProgression:

    def test_sequential_advances_across_executions(self):
        resolver = _resolver_with_episodes("sitcoms", [1500, 1400, 1600])
        results = assemble_schedule_block(
            program_ref="half_hour",
            program_def={"pool": "sitcoms", "grid_blocks": 1, "fill_mode": "single"},
            pool_name="sitcoms",
            slots=3,
            progression="sequential",
            grid_minutes=GRID_MINUTES,
            resolver=resolver,
            broadcast_day="2026-01-05",
            channel_id="test-channel",
        )
        # Sequential: each execution picks the next episode
        # (INV-EPISODE-PROGRESSION-009: multi-execution sequencing)
        asset_ids = [r.segments[0].asset_id for r in results]
        assert asset_ids == ["ep-000", "ep-001", "ep-002"]
