"""Contract tests for INV-SCHEDULE-SEQUENTIAL-ADVANCE-001.

STATUS: RETIRED

INV-SCHEDULE-SEQUENTIAL-ADVANCE-001 has been superseded by
INV-EPISODE-PROGRESSION-003 (monotonic ordered advancement).

The cursor-based sequential progression tested here has been replaced by
calendar-based occurrence counting. See:
  - docs/contracts/episode_progression.md
  - pkg/core/tests/contracts/test_episode_progression.py

These tests are skipped. They are retained for historical reference only.
"""

import pytest

pytestmark = pytest.mark.skip(
    reason="RETIRED: INV-SCHEDULE-SEQUENTIAL-ADVANCE-001 superseded by "
           "INV-EPISODE-PROGRESSION-003. See test_episode_progression.py."
)
from datetime import date, timedelta

from retrovue.runtime.schedule_compiler import (
    compile_schedule,
    channel_seed,
    NETWORK_GRID_MINUTES,
    parse_dsl,
)
from retrovue.runtime.asset_resolver import AssetMetadata, StubAssetResolver
from retrovue.runtime.progression_cursor import (
    CursorStore,
    ProgressionCursor,
    ScheduleBlockIdentity,
)


# ---------------------------------------------------------------------------
# Minimal test resolver with enough episodes to span multiple days
# ---------------------------------------------------------------------------

def _make_sequential_resolver(n_episodes: int = 100) -> StubAssetResolver:
    """Build a resolver with a large sequential episode pool."""
    r = StubAssetResolver()
    episode_ids = [f"ep-{i:04d}" for i in range(n_episodes)]
    r.register_collection("test_pool", episode_ids)
    r.register_pools({"test_pool": {"match": {"type": "episode"}}})
    for eid in episode_ids:
        r.add(eid, AssetMetadata(
            type="episode", duration_sec=1440, title=f"Episode {eid}",
        ))
    return r


_V2_SEQUENTIAL_DSL = {
    "channel": "test-sequential-channel",
    "broadcast_day": "2026-03-01",
    "timezone": "UTC",
    "template": "network",
    "pools": {
        "test_pool": {
            "match": {"type": "episode"},
        },
    },
    "programs": {
        "marathon": {
            "pool": "test_pool",
            "grid_blocks": 1,
            "fill_mode": "single",
            "bleed": False,
        },
    },
    "schedule": {
        "all_day": [
            {
                "start": "06:00",
                "slots": 36,  # 36 × 30min = 18h of programming
                "program": "marathon",
                "progression": "sequential",
            },
        ],
    },
}

SLOTS_PER_DAY = 36


# ---------------------------------------------------------------------------
# Rule 1: V2 DSL with slots > 0 produces program blocks
# ---------------------------------------------------------------------------

class TestRule1SlotCountPositive:
    """Rule 1: A V2 DSL with slots > 0 MUST produce program blocks."""

    def test_dsl_produces_blocks(self):
        """V2 DSL with 36 slots MUST produce at least 1 program block."""
        resolver = _make_sequential_resolver()
        dsl = dict(_V2_SEQUENTIAL_DSL)
        schedule = compile_schedule(dsl, resolver=resolver, seed=42)
        assert len(schedule["program_blocks"]) > 0, (
            "V2 DSL with slots=36 produced zero program blocks"
        )

    def test_dsl_produces_expected_block_count(self):
        """V2 DSL with 36 slots and grid_blocks=1 MUST produce 36 blocks."""
        resolver = _make_sequential_resolver()
        dsl = dict(_V2_SEQUENTIAL_DSL)
        schedule = compile_schedule(dsl, resolver=resolver, seed=42)
        assert len(schedule["program_blocks"]) == SLOTS_PER_DAY, (
            f"Expected {SLOTS_PER_DAY} blocks, got {len(schedule['program_blocks'])}"
        )


# ---------------------------------------------------------------------------
# Rule 2: Consecutive days produce different first episodes
# ---------------------------------------------------------------------------

class TestRule2ConsecutiveDaysDiffer:
    """Rule 2: Compiling two consecutive days MUST produce different first
    episodes when the pool is larger than one day's slots."""

    def test_day_n_and_day_n_plus_1_differ(self):
        """Compile day N and day N+1 for a sequential channel.
        The first program_block asset_id MUST differ between days."""
        resolver = _make_sequential_resolver(n_episodes=100)
        seed = channel_seed("test-sequential-channel")

        epoch = date(2026, 1, 1)
        day_a = epoch + timedelta(days=60)
        day_b = epoch + timedelta(days=61)

        def compile_day(broadcast_day: date) -> dict:
            dsl = dict(_V2_SEQUENTIAL_DSL)
            dsl["broadcast_day"] = broadcast_day.isoformat()
            day_offset = (broadcast_day - epoch).days
            starting_counter = day_offset * SLOTS_PER_DAY
            cursor_store = CursorStore()
            identity = ScheduleBlockIdentity(
                channel_id="test-sequential-channel",
                schedule_layer="compilation",
                start_time="00:00",
                program_ref="marathon",
            )
            cursor_store.save(ProgressionCursor(
                identity=identity,
                position=starting_counter,
                cycle=0,
            ))
            return compile_schedule(
                dsl, resolver=resolver,
                cursor_store=cursor_store,
                seed=seed,
            )

        schedule_a = compile_day(day_a)
        schedule_b = compile_day(day_b)

        first_a = schedule_a["program_blocks"][0]["asset_id"]
        first_b = schedule_b["program_blocks"][0]["asset_id"]

        assert first_a != first_b, (
            f"INV-SCHEDULE-SEQUENTIAL-ADVANCE-001 Rule 2: "
            f"Day {day_a} and day {day_b} both start with the same episode "
            f"({first_a}). Consecutive days MUST advance the sequential "
            f"counter to produce different episode sequences."
        )
