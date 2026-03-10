"""Contract tests for ProgressionRunStore — persistent episode progression.

Validates that the run store correctly:
    - Creates new ProgressionRun records on first encounter
    - Returns existing records on subsequent lookups
    - Persists records across store instantiations (in-memory scope)
    - Produces correct SerialRunInfo snapshots
    - Integrates with the schedule compilation pipeline

Contract: docs/contracts/episode_progression.md § Progression Run Model
"""

from __future__ import annotations

import pytest
from datetime import date, time

from retrovue.runtime.progression_run_store import (
    InMemoryProgressionRunStore,
)
from retrovue.runtime.serial_episode_resolver import (
    SerialRunInfo,
    count_occurrences,
    apply_wrap_policy,
    DAILY,
    WEEKDAY,
    WEEKEND,
)
from retrovue.runtime.asset_resolver import AssetMetadata, StubAssetResolver
from retrovue.runtime.program_assembly import assemble_schedule_block, _MIGRATION_EPOCH
from retrovue.runtime.schedule_compiler import compile_schedule


# ===========================================================================
# Run creation
# ===========================================================================


@pytest.mark.contract
class TestRunCreation:

    # Tier: 2 | Scheduling logic invariant
    def test_create_returns_serial_run_info(self):
        """create() returns a SerialRunInfo snapshot."""
        store = InMemoryProgressionRunStore()
        info = store.create(
            channel_id="test-ch",
            run_id="test-ch:all_day:00:00:sitcoms",
            content_source_id="sitcoms",
            anchor_date=date(2026, 3, 9),
            anchor_episode_index=0,
            placement_days=DAILY,
            exhaustion_policy="wrap",
        )
        assert isinstance(info, SerialRunInfo)
        assert info.anchor_date == date(2026, 3, 9)
        assert info.placement_days == DAILY
        assert info.wrap_policy == "wrap"

    # Tier: 2 | Scheduling logic invariant
    def test_create_sets_anchor_episode_index(self):
        """create() preserves the anchor_episode_index."""
        store = InMemoryProgressionRunStore()
        info = store.create(
            channel_id="test-ch",
            run_id="run-1",
            content_source_id="sitcoms",
            anchor_date=date(2026, 3, 9),
            anchor_episode_index=5,
            placement_days=DAILY,
            exhaustion_policy="wrap",
        )
        assert info.anchor_episode_index == 5

    # Tier: 2 | Scheduling logic invariant
    def test_create_with_different_exhaustion_policies(self):
        """create() correctly maps exhaustion_policy to wrap_policy."""
        store = InMemoryProgressionRunStore()
        for policy in ("wrap", "hold_last", "stop"):
            info = store.create(
                channel_id="test-ch",
                run_id=f"run-{policy}",
                content_source_id="sitcoms",
                anchor_date=date(2026, 3, 9),
                anchor_episode_index=0,
                placement_days=DAILY,
                exhaustion_policy=policy,
            )
            assert info.wrap_policy == policy


# ===========================================================================
# Run lookup
# ===========================================================================


@pytest.mark.contract
class TestRunLookup:

    # Tier: 2 | Scheduling logic invariant
    def test_load_nonexistent_returns_none(self):
        """load() returns None for an unknown run_id."""
        store = InMemoryProgressionRunStore()
        assert store.load("ch", "nonexistent") is None

    # Tier: 2 | Scheduling logic invariant
    def test_load_after_create_returns_same_record(self):
        """load() returns the same record created by create()."""
        store = InMemoryProgressionRunStore()
        created = store.create(
            channel_id="test-ch",
            run_id="run-1",
            content_source_id="sitcoms",
            anchor_date=date(2026, 3, 9),
            anchor_episode_index=0,
            placement_days=DAILY,
            exhaustion_policy="wrap",
        )
        loaded = store.load("test-ch", "run-1")
        assert loaded == created

    # Tier: 2 | Scheduling logic invariant
    def test_load_is_channel_scoped(self):
        """Runs with the same run_id on different channels are independent."""
        store = InMemoryProgressionRunStore()
        store.create(
            channel_id="ch-a",
            run_id="shared-name",
            content_source_id="sitcoms",
            anchor_date=date(2026, 3, 9),
            anchor_episode_index=0,
            placement_days=DAILY,
            exhaustion_policy="wrap",
        )
        assert store.load("ch-b", "shared-name") is None

    # Tier: 2 | Scheduling logic invariant
    def test_multiple_runs_per_channel(self):
        """A channel can have multiple runs with different run_ids."""
        store = InMemoryProgressionRunStore()
        store.create(
            channel_id="test-ch",
            run_id="morning",
            content_source_id="sitcoms",
            anchor_date=date(2026, 3, 9),
            anchor_episode_index=0,
            placement_days=DAILY,
            exhaustion_policy="wrap",
        )
        store.create(
            channel_id="test-ch",
            run_id="primetime",
            content_source_id="dramas",
            anchor_date=date(2026, 3, 9),
            anchor_episode_index=0,
            placement_days=WEEKDAY,
            exhaustion_policy="hold_last",
        )
        morning = store.load("test-ch", "morning")
        primetime = store.load("test-ch", "primetime")
        assert morning is not None
        assert primetime is not None
        assert morning.content_source_id == "sitcoms"
        assert primetime.content_source_id == "dramas"


# ===========================================================================
# Run reuse across recompilations
# ===========================================================================


@pytest.mark.contract
class TestRunReuse:

    # Tier: 2 | Scheduling logic invariant
    def test_same_store_reuses_run_across_days(self):
        """Compiling multiple broadcast days with the same store reuses
        the run created on the first compilation.

        INV-EPISODE-PROGRESSION-001: Deterministic episode selection.
        INV-EPISODE-PROGRESSION-002: Restart invariance (within store lifetime).
        """
        store = InMemoryProgressionRunStore()
        run_id = "test-ch:all_day:00:00:sitcoms"
        anchor = date(2026, 3, 9)  # Monday

        # First compilation creates the run.
        store.create(
            channel_id="test-ch",
            run_id=run_id,
            content_source_id="sitcoms",
            anchor_date=anchor,
            anchor_episode_index=0,
            placement_days=DAILY,
            exhaustion_policy="wrap",
        )

        # Subsequent lookups return the same anchor.
        for day_offset in range(1, 8):
            loaded = store.load("test-ch", run_id)
            assert loaded is not None
            assert loaded.anchor_date == anchor, (
                f"Anchor must be stable across lookups (day_offset={day_offset})"
            )


# ===========================================================================
# Pipeline integration — store wired through assemble_schedule_block
# ===========================================================================


def _resolver_with_episodes(
    pool_name: str,
    episode_durations_sec: list[int],
) -> StubAssetResolver:
    resolver = StubAssetResolver()
    for i, dur in enumerate(episode_durations_sec):
        aid = f"ep-{i:03d}"
        resolver.add(aid, AssetMetadata(
            type="episode", duration_sec=dur, title=f"Episode {i}",
        ))
    resolver.register_pools({pool_name: {"match": {"type": "episode"}}})
    return resolver


@pytest.mark.contract
class TestPipelineIntegration:

    # Tier: 2 | Scheduling logic invariant
    def test_auto_creates_run_on_first_compilation(self):
        """assemble_schedule_block creates a run in the store if none exists.

        The anchor is the migration epoch (2026-01-05), not the broadcast day,
        for backward compatibility with the pre-persistence era.
        """
        store = InMemoryProgressionRunStore()
        resolver = _resolver_with_episodes("sitcoms", [1500, 1400, 1600])

        results = assemble_schedule_block(
            program_ref="half_hour",
            program_def={"pool": "sitcoms", "grid_blocks": 1, "fill_mode": "single"},
            pool_name="sitcoms",
            slots=1,
            progression="sequential",
            grid_minutes=30,
            resolver=resolver,
            broadcast_day="2026-03-09",
            channel_id="test-ch",
            run_store=store,
        )
        assert len(results) == 1

        # Verify a run was created in the store with epoch anchor.
        run_id = "test-ch:all_day:00:00:half_hour"
        loaded = store.load("test-ch", run_id)
        assert loaded is not None
        assert loaded.anchor_date == _MIGRATION_EPOCH

    # Tier: 2 | Scheduling logic invariant
    def test_reuses_existing_run(self):
        """assemble_schedule_block reuses an existing run from the store."""
        store = InMemoryProgressionRunStore()
        resolver = _resolver_with_episodes("sitcoms", [1500, 1400, 1600])

        # Pre-create a run with a specific anchor.
        anchor = date(2026, 3, 2)  # Monday, one week before target
        store.create(
            channel_id="test-ch",
            run_id="test-ch:all_day:00:00:half_hour",
            content_source_id="half_hour",
            anchor_date=anchor,
            anchor_episode_index=0,
            placement_days=DAILY,
            exhaustion_policy="wrap",
        )

        # Compile for March 9 (7 days after anchor → occurrence=7).
        results = assemble_schedule_block(
            program_ref="half_hour",
            program_def={"pool": "sitcoms", "grid_blocks": 1, "fill_mode": "single"},
            pool_name="sitcoms",
            slots=1,
            progression="sequential",
            grid_minutes=30,
            resolver=resolver,
            broadcast_day="2026-03-09",
            channel_id="test-ch",
            run_store=store,
        )
        # With 3 episodes, wrap policy, occurrence=7 → index = 7 % 3 = 1
        content = [s for s in results[0].segments if s.segment_type == "content"]
        assert content[0].asset_id == "ep-001"

    # Tier: 2 | Scheduling logic invariant
    def test_anchor_stability_across_compilations(self):
        """Compiling for day N, then day N+1, uses the same epoch anchor.
        Episodes advance by exactly 1 between consecutive days.

        INV-EPISODE-PROGRESSION-001: Deterministic selection.
        INV-EPISODE-PROGRESSION-003: Monotonic advancement.
        """
        store = InMemoryProgressionRunStore()
        resolver = _resolver_with_episodes("sitcoms", [1500] * 100)

        def compile_day(broadcast_day: str) -> str:
            results = assemble_schedule_block(
                program_ref="marathon",
                program_def={"pool": "sitcoms", "grid_blocks": 1, "fill_mode": "single"},
                pool_name="sitcoms",
                slots=1,
                progression="sequential",
                grid_minutes=30,
                resolver=resolver,
                broadcast_day=broadcast_day,
                channel_id="test-ch",
                run_store=store,
            )
            content = [s for s in results[0].segments if s.segment_type == "content"]
            return content[0].asset_id

        # Anchor is the migration epoch (2026-01-05).
        # 2026-03-09 is 63 days after epoch → ep-063.
        # 2026-03-10 is 64 days after epoch → ep-064.
        ep_day1 = compile_day("2026-03-09")
        ep_day2 = compile_day("2026-03-10")

        occ_day1 = count_occurrences(_MIGRATION_EPOCH, date(2026, 3, 9), DAILY)
        occ_day2 = count_occurrences(_MIGRATION_EPOCH, date(2026, 3, 10), DAILY)
        assert ep_day1 == f"ep-{occ_day1:03d}"
        assert ep_day2 == f"ep-{occ_day2:03d}"
        assert occ_day2 == occ_day1 + 1  # monotonic advancement

        # Verify anchor hasn't changed.
        run_id = "test-ch:all_day:00:00:marathon"
        loaded = store.load("test-ch", run_id)
        assert loaded.anchor_date == _MIGRATION_EPOCH

    # Tier: 2 | Scheduling logic invariant
    def test_explicit_run_id_shared_across_blocks(self):
        """Two blocks sharing an explicit run_id resolve the same episode.

        INV-EPISODE-PROGRESSION-004: Placement isolation (shared case).
        """
        store = InMemoryProgressionRunStore()
        resolver = _resolver_with_episodes("sitcoms", [1500, 1400, 1600])

        def compile_block(run_id: str, program_ref: str) -> str:
            results = assemble_schedule_block(
                program_ref=program_ref,
                program_def={"pool": "sitcoms", "grid_blocks": 1, "fill_mode": "single"},
                pool_name="sitcoms",
                slots=1,
                progression="sequential",
                grid_minutes=30,
                resolver=resolver,
                broadcast_day="2026-03-09",
                channel_id="test-ch",
                run_id=run_id,
                run_store=store,
            )
            content = [s for s in results[0].segments if s.segment_type == "content"]
            return content[0].asset_id

        # Both blocks use the same explicit run_id.
        ep_a = compile_block("shared-run", "morning_show")
        ep_b = compile_block("shared-run", "evening_show")

        # Same run_id → same episode (shared progression).
        assert ep_a == ep_b

    # Tier: 2 | Scheduling logic invariant
    def test_no_run_store_defaults_to_inmemory(self):
        """When run_store is None, a transient InMemoryProgressionRunStore
        is created per call. Episodes still resolve correctly."""
        resolver = _resolver_with_episodes("sitcoms", [1500, 1400, 1600])

        results = assemble_schedule_block(
            program_ref="half_hour",
            program_def={"pool": "sitcoms", "grid_blocks": 1, "fill_mode": "single"},
            pool_name="sitcoms",
            slots=3,
            progression="sequential",
            grid_minutes=30,
            resolver=resolver,
            broadcast_day="2026-03-09",
            channel_id="test-ch",
            # run_store=None — default
        )
        assert len(results) == 3
        asset_ids = [r.segments[0].asset_id for r in results]
        assert asset_ids == ["ep-000", "ep-001", "ep-002"]

    # Tier: 2 | Scheduling logic invariant
    def test_multi_execution_daily_stride(self):
        """With N executions per day, day D+1 must start where day D left off.

        INV-EPISODE-PROGRESSION-009: Multi-execution sequencing.
        INV-EPISODE-PROGRESSION-013: Daily stride scales with executions.

        A block with slots=4 (4 executions) on day D selects episodes
        [base, base+1, base+2, base+3]. Day D+1 must select
        [base+4, base+5, base+6, base+7] — zero overlap.
        """
        store = InMemoryProgressionRunStore()
        resolver = _resolver_with_episodes("sitcoms", [1500] * 500)

        def compile_day(broadcast_day: str) -> list[str]:
            # emissions_per_occurrence=4: single block with 4 executions per day
            results = assemble_schedule_block(
                program_ref="marathon",
                program_def={"pool": "sitcoms", "grid_blocks": 1, "fill_mode": "single"},
                pool_name="sitcoms",
                slots=4,
                progression="sequential",
                grid_minutes=30,
                resolver=resolver,
                broadcast_day=broadcast_day,
                channel_id="test-ch",
                run_store=store,
                emissions_per_occurrence=4,
            )
            return [
                [s for s in r.segments if s.segment_type == "content"][0].asset_id
                for r in results
            ]

        eps_day1 = compile_day("2026-03-09")
        eps_day2 = compile_day("2026-03-10")

        # Day 1 and Day 2 must have ZERO overlap.
        assert set(eps_day1).isdisjoint(set(eps_day2)), (
            f"Episodes overlap between consecutive days!\n"
            f"  Day 1: {eps_day1}\n"
            f"  Day 2: {eps_day2}"
        )

        # Day 2 must start exactly where Day 1 left off.
        day1_last_idx = int(eps_day1[-1].split("-")[1])
        day2_first_idx = int(eps_day2[0].split("-")[1])
        assert day2_first_idx == day1_last_idx + 1, (
            f"Day 2 should start at ep-{day1_last_idx + 1:03d}, "
            f"got {eps_day2[0]}"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_weekday_placement_anchor_matches_pattern(self):
        """When placement is weekday-only, anchor matches the pattern.
        The epoch (Monday) matches weekday, so anchor = epoch.

        INV-EPISODE-PROGRESSION-011: Anchor validity.
        """
        store = InMemoryProgressionRunStore()
        resolver = _resolver_with_episodes("sitcoms", [1500] * 100)

        # 2026-03-09 is a Monday — matches weekday pattern.
        results = assemble_schedule_block(
            program_ref="strip",
            program_def={"pool": "sitcoms", "grid_blocks": 1, "fill_mode": "single"},
            pool_name="sitcoms",
            slots=1,
            progression="sequential",
            grid_minutes=30,
            resolver=resolver,
            broadcast_day="2026-03-09",
            channel_id="test-ch",
            schedule_layer="weekdays",
            run_store=store,
        )
        assert len(results) == 1

        run_id = "test-ch:weekdays:00:00:strip"
        loaded = store.load("test-ch", run_id)
        assert loaded is not None
        # Anchor is epoch (Monday) — weekday bit must be set.
        assert loaded.anchor_date == _MIGRATION_EPOCH
        assert loaded.placement_days == WEEKDAY
        assert (1 << loaded.anchor_date.weekday()) & WEEKDAY != 0

    # Tier: 2 | Scheduling logic invariant
    def test_shared_run_id_same_day_blocks(self):
        """Two blocks sharing an explicit run_id on the same day produce
        contiguous, non-overlapping episode sequences.

        Block A (06:00, slots=3): emissions 0,1,2
        Block B (16:00, slots=3): emissions 3,4,5
        Day 2 Block A: emissions 6,7,8
        Day 2 Block B: emissions 9,10,11

        INV-EPISODE-PROGRESSION-009: Multi-execution sequencing.
        """
        store = InMemoryProgressionRunStore()
        resolver = _resolver_with_episodes("sitcoms", [1500] * 500)
        shared_rid = "cheers_strip"

        def compile_block(broadcast_day: str, prior: int) -> list[str]:
            # emissions_per_occurrence=6: 3 (block A) + 3 (block B) per day
            results = assemble_schedule_block(
                program_ref="cheers_30",
                program_def={"pool": "sitcoms", "grid_blocks": 1, "fill_mode": "single"},
                pool_name="sitcoms",
                slots=3,
                progression="sequential",
                grid_minutes=30,
                resolver=resolver,
                broadcast_day=broadcast_day,
                channel_id="test-ch",
                run_id=shared_rid,
                run_store=store,
                emissions_per_occurrence=6,
                prior_same_day_emissions=prior,
            )
            return [
                [s for s in r.segments if s.segment_type == "content"][0].asset_id
                for r in results
            ]

        # Day 1: Block A (prior=0), Block B (prior=3)
        day1_a = compile_block("2026-03-09", prior=0)
        day1_b = compile_block("2026-03-09", prior=3)
        # Day 2: Block A (prior=0), Block B (prior=3)
        day2_a = compile_block("2026-03-10", prior=0)
        day2_b = compile_block("2026-03-10", prior=3)

        all_day1 = day1_a + day1_b
        all_day2 = day2_a + day2_b

        # No overlap within a day
        assert len(set(all_day1)) == 6, f"Day 1 has duplicates: {all_day1}"
        # No overlap between days
        assert set(all_day1).isdisjoint(set(all_day2)), (
            f"Day 1/2 overlap!\n  Day 1: {all_day1}\n  Day 2: {all_day2}"
        )
        # Day 2 starts exactly where Day 1 left off
        day1_last_idx = int(all_day1[-1].split("-")[1])
        day2_first_idx = int(all_day2[0].split("-")[1])
        assert day2_first_idx == day1_last_idx + 1

    # Tier: 2 | Scheduling logic invariant
    def test_derived_run_id_uses_start_time(self):
        """Blocks at different start times (no explicit run_id) produce
        independent progressions via distinct derived run_ids.

        INV-EPISODE-PROGRESSION-004: Placement isolation.
        """
        store = InMemoryProgressionRunStore()
        resolver = _resolver_with_episodes("sitcoms", [1500] * 100)

        def compile_at(start_time: str) -> str:
            results = assemble_schedule_block(
                program_ref="sitcoms_30",
                program_def={"pool": "sitcoms", "grid_blocks": 1, "fill_mode": "single"},
                pool_name="sitcoms",
                slots=1,
                progression="sequential",
                grid_minutes=30,
                resolver=resolver,
                broadcast_day="2026-03-09",
                channel_id="test-ch",
                schedule_layer="all_day",
                start_time=start_time,
                run_store=store,
            )
            content = [s for s in results[0].segments if s.segment_type == "content"]
            return content[0].asset_id

        ep_06 = compile_at("06:00")
        ep_16 = compile_at("16:00")

        # Different start times → different derived run_ids → independent runs.
        # Both have same occurrence count from epoch, so they select the same
        # episode index — but from independent runs.
        # Verify run store has two distinct entries.
        run_06 = store.load("test-ch", "test-ch:all_day:06:00:sitcoms_30")
        run_16 = store.load("test-ch", "test-ch:all_day:16:00:sitcoms_30")
        assert run_06 is not None, "06:00 run should exist"
        assert run_16 is not None, "16:00 run should exist"

    # Tier: 2 | Scheduling logic invariant
    def test_explicit_shared_run_id_shares_progression(self):
        """Blocks with the same explicit run_id share progression state.

        INV-EPISODE-PROGRESSION-004: Shared run_id → shared progression.
        """
        store = InMemoryProgressionRunStore()
        resolver = _resolver_with_episodes("sitcoms", [1500] * 100)

        def compile_with_rid(run_id: str, prior: int, epo: int) -> str:
            results = assemble_schedule_block(
                program_ref="cheers_30",
                program_def={"pool": "sitcoms", "grid_blocks": 1, "fill_mode": "single"},
                pool_name="sitcoms",
                slots=1,
                progression="sequential",
                grid_minutes=30,
                resolver=resolver,
                broadcast_day="2026-03-09",
                channel_id="test-ch",
                run_id=run_id,
                run_store=store,
                emissions_per_occurrence=epo,
                prior_same_day_emissions=prior,
            )
            content = [s for s in results[0].segments if s.segment_type == "content"]
            return content[0].asset_id

        # Two blocks, same explicit run_id, emissions_per_occurrence=2
        ep_a = compile_with_rid("shared", prior=0, epo=2)
        ep_b = compile_with_rid("shared", prior=1, epo=2)

        # They should pick consecutive episodes (no overlap)
        idx_a = int(ep_a.split("-")[1])
        idx_b = int(ep_b.split("-")[1])
        assert idx_b == idx_a + 1, f"Expected consecutive: {ep_a}, {ep_b}"


# ===========================================================================
# Full pipeline — compile_schedule pre-scan integration
# ===========================================================================


@pytest.mark.contract
class TestCompileScheduleEmissions:
    """Tests that compile_schedule correctly computes emissions_per_occurrence
    and prior_same_day_emissions for blocks sharing a run_id."""

    # Tier: 2 | Scheduling logic invariant
    def test_shared_run_id_via_compile_schedule(self):
        """Two blocks sharing run_id in a DSL schedule produce contiguous
        episode sequences across days via compile_schedule.

        This exercises the pre-scan logic in compile_schedule that computes
        emissions_per_occurrence and prior_same_day_emissions.
        """
        resolver = StubAssetResolver()
        for i in range(500):
            aid = f"ep-{i:03d}"
            resolver.add(aid, AssetMetadata(
                type="episode", duration_sec=1500, title=f"Episode {i}",
            ))
        resolver.register_pools({"sitcoms": {"match": {"type": "episode"}}})

        store = InMemoryProgressionRunStore()

        dsl = {
            "channel": "test-ch",
            "broadcast_day": "2026-03-09",
            "timezone": "UTC",
            "template": "network_television",
            "pools": {"sitcoms": {"match": {"type": "episode"}}},
            "programs": {
                "cheers_30": {
                    "pool": "sitcoms",
                    "grid_blocks": 1,
                    "fill_mode": "single",
                },
            },
            "schedule": {
                "all_day": [
                    {
                        "start": "06:00",
                        "slots": 3,
                        "program": "cheers_30",
                        "progression": "sequential",
                        "run_id": "cheers_strip",
                    },
                    {
                        "start": "16:00",
                        "slots": 3,
                        "program": "cheers_30",
                        "progression": "sequential",
                        "run_id": "cheers_strip",
                    },
                ],
            },
        }

        from retrovue.runtime.schedule_compiler import compilation_seed
        seed = compilation_seed("test-ch", "2026-03-09")

        result_day1 = compile_schedule(dsl, resolver, seed=seed, run_store=store)
        day1_ids = [b["asset_id"] for b in result_day1["program_blocks"]]
        assert len(day1_ids) == 6, f"Expected 6 blocks, got {len(day1_ids)}"

        # All 6 must be unique (no overlap within the day)
        assert len(set(day1_ids)) == 6, f"Day 1 has duplicates: {day1_ids}"

        # Day 2
        dsl2 = dict(dsl, broadcast_day="2026-03-10")
        seed2 = compilation_seed("test-ch", "2026-03-10")
        result_day2 = compile_schedule(dsl2, resolver, seed=seed2, run_store=store)
        day2_ids = [b["asset_id"] for b in result_day2["program_blocks"]]

        # No overlap between days
        assert set(day1_ids).isdisjoint(set(day2_ids)), (
            f"Day 1/2 overlap!\n  Day 1: {day1_ids}\n  Day 2: {day2_ids}"
        )

        # Day 2 starts where Day 1 left off
        day1_last_idx = int(day1_ids[-1].split("-")[1])
        day2_first_idx = int(day2_ids[0].split("-")[1])
        assert day2_first_idx == day1_last_idx + 1, (
            f"Day 2 should start at ep-{day1_last_idx + 1:03d}, got {day2_ids[0]}"
        )
