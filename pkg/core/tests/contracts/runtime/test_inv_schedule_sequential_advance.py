"""Contract tests for INV-SCHEDULE-SEQUENTIAL-ADVANCE-001.

For channels using `mode: sequential`, consecutive broadcast days MUST
advance the sequential counter so that episodes progress through the pool
across days rather than repeating from the start.

Rules:
1. _count_slots_in_dsl() MUST return >0 for any DSL that produces program
   blocks, including block-style schedules with duration/start/end.
2. Compiling two consecutive days with the same DSL MUST produce different
   first episodes when the pool contains more episodes than one day's slots.
"""

import pytest

from retrovue.runtime.schedule_compiler import (
    compile_schedule,
    channel_seed,
    NETWORK_GRID_MINUTES,
)
from retrovue.runtime.asset_resolver import AssetMetadata, AssetResolver


# ---------------------------------------------------------------------------
# Minimal test resolver with enough episodes to span multiple days
# ---------------------------------------------------------------------------

class _TestResolver(AssetResolver):
    """Fake resolver with a configurable pool of sequential episodes."""

    def __init__(self, n_episodes: int = 100):
        self._episodes = [f"ep-{i:04d}" for i in range(n_episodes)]

    def lookup(self, asset_id: str) -> AssetMetadata:
        if asset_id == "test_pool":
            return AssetMetadata(
                type="pool",
                duration_sec=0,
                tags=tuple(self._episodes),
            )
        # Individual episode — 24-minute sitcom
        return AssetMetadata(
            type="episode",
            duration_sec=1440,
            title=f"Episode {asset_id}",
        )


# ---------------------------------------------------------------------------
# Rule 1: _count_slots_in_dsl() returns >0 for block-style DSL
# ---------------------------------------------------------------------------

class TestRule1SlotCountPositive:
    """Rule 1: _count_slots_in_dsl() MUST return >0 for block-style DSL."""

    def test_block_with_duration_returns_positive(self):
        """Block-style DSL with duration: '24h' MUST produce a positive
        slot count, not zero."""
        from retrovue.runtime.dsl_schedule_service import DslScheduleService

        dsl = {
            "schedule": {
                "all_day": [
                    {
                        "block": {
                            "start": "06:00",
                            "duration": "24h",
                            "title": "Test",
                            "pool": "test_pool",
                            "mode": "sequential",
                        }
                    }
                ]
            }
        }
        count = DslScheduleService._count_slots_in_dsl(dsl)
        assert count > 0, (
            "INV-SCHEDULE-SEQUENTIAL-ADVANCE-001 Rule 1: "
            "_count_slots_in_dsl() returned 0 for block-style DSL with "
            "duration='24h'. Block-style schedules MUST be counted by "
            "computing total scheduled minutes divided by grid slot size."
        )

    def test_block_with_start_end_returns_positive(self):
        """Block-style DSL with start/end MUST produce a positive slot count."""
        from retrovue.runtime.dsl_schedule_service import DslScheduleService

        dsl = {
            "schedule": {
                "all_day": [
                    {
                        "block": {
                            "start": "06:00",
                            "end": "18:00",
                            "title": "Test",
                            "pool": "test_pool",
                            "mode": "sequential",
                        }
                    }
                ]
            }
        }
        count = DslScheduleService._count_slots_in_dsl(dsl)
        assert count > 0, (
            "INV-SCHEDULE-SEQUENTIAL-ADVANCE-001 Rule 1: "
            "_count_slots_in_dsl() returned 0 for block-style DSL with "
            "start/end. Must compute duration from time range."
        )

    def test_movie_marathon_returns_positive(self):
        """movie_marathon block MUST produce a positive slot count."""
        from retrovue.runtime.dsl_schedule_service import DslScheduleService

        dsl = {
            "schedule": {
                "all_day": [
                    {
                        "movie_marathon": {
                            "start": "22:00",
                            "end": "06:00",
                            "title": "Late Movies",
                            "movie_selector": {"pool": "movies"},
                        }
                    }
                ]
            }
        }
        count = DslScheduleService._count_slots_in_dsl(dsl)
        assert count > 0, (
            "INV-SCHEDULE-SEQUENTIAL-ADVANCE-001 Rule 1: "
            "_count_slots_in_dsl() returned 0 for movie_marathon block."
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
        from retrovue.runtime.dsl_schedule_service import DslScheduleService

        resolver = _TestResolver(n_episodes=100)
        seed = channel_seed("test-sequential-channel")

        dsl = {
            "channel": "test-sequential-channel",
            "timezone": "UTC",
            "template": "network_sitcom",
            "pools": {
                "test_pool": {
                    "match": {"type": "episode"},
                }
            },
            "schedule": {
                "all_day": [
                    {
                        "block": {
                            "start": "06:00",
                            "duration": "24h",
                            "title": "Test Marathon",
                            "pool": "test_pool",
                            "mode": "sequential",
                        }
                    }
                ]
            },
        }

        slots_per_day = DslScheduleService._count_slots_in_dsl(dsl)
        assert slots_per_day > 0, "Precondition: slots_per_day must be >0"

        # Compile day 60 (arbitrary) and day 61
        from datetime import date, timedelta
        epoch = date(2026, 1, 1)
        day_a = epoch + timedelta(days=60)
        day_b = epoch + timedelta(days=61)

        def compile_day(broadcast_day: date) -> dict:
            from retrovue.runtime.progression_cursor import (
                CursorStore,
                ProgressionCursor,
                ScheduleBlockIdentity,
            )
            d = dict(dsl)
            d["broadcast_day"] = broadcast_day.isoformat()
            day_offset = (broadcast_day - epoch).days
            starting_counter = day_offset * slots_per_day
            cursor_store = CursorStore()
            identity = ScheduleBlockIdentity(
                channel_id="test-sequential-channel",
                schedule_layer="compilation",
                start_time="00:00",
                program_ref="test_pool",
            )
            cursor_store.save(ProgressionCursor(
                identity=identity,
                position=starting_counter,
                cycle=0,
            ))
            return compile_schedule(
                d, resolver=resolver,
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
