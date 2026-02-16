"""
Tests for day-of-week layering in the Programming DSL.

Covers: resolve_day_schedule merging, layer precedence, backward compatibility.
"""

from __future__ import annotations

from datetime import date, datetime, timezone as tz_mod

import pytest

from retrovue.runtime.asset_resolver import AssetMetadata, StubAssetResolver
from retrovue.runtime.schedule_compiler import (
    compile_schedule,
    parse_dsl,
    resolve_day_schedule,
)


def _make_resolver() -> StubAssetResolver:
    r = StubAssetResolver()
    r.add("col.cheers", AssetMetadata(
        type="collection", duration_sec=0,
        tags=("ep.cheers.1", "ep.cheers.2"),
    ))
    r.add("col.cosby", AssetMetadata(
        type="collection", duration_sec=0,
        tags=("ep.cosby.1",),
    ))
    r.add("col.batman", AssetMetadata(
        type="collection", duration_sec=0,
        tags=("ep.batman.1",),
    ))
    for ep in ("ep.cheers.1", "ep.cheers.2", "ep.cosby.1", "ep.batman.1"):
        r.add(ep, AssetMetadata(type="episode", duration_sec=1320, rating="PG"))
    return r


class TestResolveDaySchedule:
    def test_all_day_only(self):
        """all_day works as base layer for any day."""
        dsl = {
            "schedule": {
                "all_day": [
                    {"start": "06:00", "slots": [{"title": "A"}]},
                    {"start": "07:00", "slots": [{"title": "B"}]},
                ],
            },
        }
        # Monday
        result = resolve_day_schedule(dsl, date(2026, 2, 16))
        assert len(result) == 2
        assert result[0]["start"] == "06:00"
        assert result[1]["start"] == "07:00"

    def test_weekdays_overrides_all_day(self):
        """weekdays layer overrides all_day by start time."""
        dsl = {
            "schedule": {
                "all_day": [
                    {"start": "06:00", "slots": [{"title": "Base6"}]},
                    {"start": "07:00", "slots": [{"title": "Base7"}]},
                ],
                "weekdays": [
                    {"start": "07:00", "slots": [{"title": "Weekday7"}]},
                ],
            },
        }
        # Monday
        result = resolve_day_schedule(dsl, date(2026, 2, 16))
        assert len(result) == 2
        assert result[0]["slots"][0]["title"] == "Base6"  # from all_day
        assert result[1]["slots"][0]["title"] == "Weekday7"  # overridden

    def test_specific_dow_highest_precedence(self):
        """Specific DOW overrides both weekdays and all_day."""
        dsl = {
            "schedule": {
                "all_day": [
                    {"start": "06:00", "slots": [{"title": "Base"}]},
                    {"start": "20:00", "slots": [{"title": "AllDay20"}]},
                ],
                "weekdays": [
                    {"start": "20:00", "slots": [{"title": "Weekday20"}]},
                ],
                "tuesday": [
                    {"start": "20:00", "slots": [{"title": "Tuesday20"}]},
                ],
            },
        }
        # Tuesday 2026-02-17
        result = resolve_day_schedule(dsl, date(2026, 2, 17))
        assert len(result) == 2
        assert result[0]["slots"][0]["title"] == "Base"  # 06:00 from all_day
        assert result[1]["slots"][0]["title"] == "Tuesday20"  # 20:00 from tuesday

    def test_weekends_group(self):
        """weekends layer applies to Saturday/Sunday."""
        dsl = {
            "schedule": {
                "all_day": [{"start": "06:00", "slots": [{"title": "Base"}]}],
                "weekends": [{"start": "10:00", "slots": [{"title": "Weekend"}]}],
            },
        }
        # Saturday 2026-02-21
        result = resolve_day_schedule(dsl, date(2026, 2, 21))
        assert len(result) == 2
        starts = [b["start"] for b in result]
        assert "06:00" in starts
        assert "10:00" in starts

    def test_weekdays_not_applied_on_weekend(self):
        """weekdays does NOT apply on Saturday."""
        dsl = {
            "schedule": {
                "all_day": [{"start": "06:00", "slots": [{"title": "Base"}]}],
                "weekdays": [{"start": "06:00", "slots": [{"title": "Weekday"}]}],
            },
        }
        # Saturday
        result = resolve_day_schedule(dsl, date(2026, 2, 21))
        assert result[0]["slots"][0]["title"] == "Base"

    def test_merge_adds_new_start_times(self):
        """Higher layers can add new start times not in base."""
        dsl = {
            "schedule": {
                "all_day": [{"start": "06:00", "slots": [{"title": "A"}]}],
                "monday": [{"start": "22:00", "slots": [{"title": "LateNight"}]}],
            },
        }
        result = resolve_day_schedule(dsl, date(2026, 2, 16))
        assert len(result) == 2
        assert result[1]["start"] == "22:00"


class TestDowCompilation:
    def test_all_day_backward_compat(self):
        """Existing all_day-only DSL continues to work."""
        yaml_text = """
channel: test-channel
broadcast_day: "2026-02-16"
timezone: America/New_York
schedule:
  all_day:
    - start: "20:00"
      slots:
        - title: "Cheers"
          episode_selector:
            pool: cheers
            mode: sequential
"""
        resolver = _make_resolver()
        # Register pool
        resolver.register_pools({"cheers": {"match": {"type": "episode"}}})
        # Need to add cheers pool as collection
        resolver.add("cheers", AssetMetadata(type="collection", duration_sec=0, tags=("ep.cheers.1", "ep.cheers.2")))

        dsl = parse_dsl(yaml_text)
        plan = compile_schedule(dsl, resolver, seed=42)
        assert len(plan["program_blocks"]) == 1

    def test_dow_layered_compilation(self):
        """DOW-layered DSL compiles correctly for a specific date."""
        yaml_text = """
channel: test-channel
broadcast_day: "2026-02-16"
timezone: America/New_York
schedule:
  all_day:
    - start: "06:00"
      slots:
        - title: "Cheers"
          episode_selector:
            pool: cheers
            mode: sequential
  monday:
    - start: "20:00"
      slots:
        - title: "Cheers"
          episode_selector:
            pool: cheers
            mode: sequential
"""
        resolver = _make_resolver()
        resolver.register_pools({"cheers": {"match": {"type": "episode"}}})
        resolver.add("cheers", AssetMetadata(type="collection", duration_sec=0, tags=("ep.cheers.1", "ep.cheers.2")))

        dsl = parse_dsl(yaml_text)
        plan = compile_schedule(dsl, resolver, seed=42)
        # Monday: 06:00 from all_day + 20:00 from monday = 2 blocks
        assert len(plan["program_blocks"]) == 2
