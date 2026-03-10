"""
Tests for day-of-week layering in the Programming DSL.

Covers: resolve_day_schedule merging, layer precedence, compilation.
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
    r.register_collection("col.cheers", ["ep.cheers.1", "ep.cheers.2"])
    r.add("col.cosby", AssetMetadata(
        type="collection", duration_sec=0,
        tags=("ep.cosby.1",),
    ))
    r.register_collection("col.cosby", ["ep.cosby.1"])
    r.add("col.batman", AssetMetadata(
        type="collection", duration_sec=0,
        tags=("ep.batman.1",),
    ))
    r.register_collection("col.batman", ["ep.batman.1"])
    for ep in ("ep.cheers.1", "ep.cheers.2", "ep.cosby.1", "ep.batman.1"):
        r.add(ep, AssetMetadata(type="episode", duration_sec=1320, rating="PG"))
    return r


class TestResolveDaySchedule:
    def test_all_day_only(self):
        """all_day works as base layer for any day."""
        dsl = {
            "schedule": {
                "all_day": [
                    {"start": "06:00", "slots": 1, "program": "a", "progression": "random"},
                    {"start": "07:00", "slots": 1, "program": "b", "progression": "random"},
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
                    {"start": "06:00", "slots": 1, "program": "base6", "progression": "random"},
                    {"start": "07:00", "slots": 1, "program": "base7", "progression": "random"},
                ],
                "weekdays": [
                    {"start": "07:00", "slots": 1, "program": "weekday7", "progression": "random"},
                ],
            },
        }
        # Monday
        result = resolve_day_schedule(dsl, date(2026, 2, 16))
        assert len(result) == 2
        assert result[0]["program"] == "base6"  # from all_day
        assert result[1]["program"] == "weekday7"  # overridden

    def test_specific_dow_highest_precedence(self):
        """Specific DOW overrides both weekdays and all_day."""
        dsl = {
            "schedule": {
                "all_day": [
                    {"start": "06:00", "slots": 1, "program": "base", "progression": "random"},
                    {"start": "20:00", "slots": 1, "program": "allday20", "progression": "random"},
                ],
                "weekdays": [
                    {"start": "20:00", "slots": 1, "program": "weekday20", "progression": "random"},
                ],
                "tuesday": [
                    {"start": "20:00", "slots": 1, "program": "tuesday20", "progression": "random"},
                ],
            },
        }
        # Tuesday 2026-02-17
        result = resolve_day_schedule(dsl, date(2026, 2, 17))
        assert len(result) == 2
        assert result[0]["program"] == "base"  # 06:00 from all_day
        assert result[1]["program"] == "tuesday20"  # 20:00 from tuesday

    def test_weekends_group(self):
        """weekends layer applies to Saturday/Sunday."""
        dsl = {
            "schedule": {
                "all_day": [{"start": "06:00", "slots": 1, "program": "base", "progression": "random"}],
                "weekends": [{"start": "10:00", "slots": 1, "program": "weekend", "progression": "random"}],
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
                "all_day": [{"start": "06:00", "slots": 1, "program": "base", "progression": "random"}],
                "weekdays": [{"start": "06:00", "slots": 1, "program": "weekday", "progression": "random"}],
            },
        }
        # Saturday
        result = resolve_day_schedule(dsl, date(2026, 2, 21))
        assert result[0]["program"] == "base"

    def test_merge_adds_new_start_times(self):
        """Higher layers can add new start times not in base."""
        dsl = {
            "schedule": {
                "all_day": [{"start": "06:00", "slots": 1, "program": "a", "progression": "random"}],
                "monday": [{"start": "22:00", "slots": 1, "program": "late", "progression": "random"}],
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
pools:
  cheers:
    match: { type: episode, collection: col.cheers }
programs:
  p_cheers:
    pool: cheers
    grid_blocks: 1
    fill_mode: single
schedule:
  all_day:
    - start: "20:00"
      slots: 1
      program: p_cheers
      progression: sequential
"""
        resolver = _make_resolver()
        dsl = parse_dsl(yaml_text)
        plan = compile_schedule(dsl, resolver, seed=42)
        assert len(plan["program_blocks"]) == 1

    def test_dow_layered_compilation(self):
        """DOW-layered DSL compiles correctly for a specific date."""
        yaml_text = """
channel: test-channel
broadcast_day: "2026-02-16"
timezone: America/New_York
pools:
  cheers:
    match: { type: episode, collection: col.cheers }
programs:
  p_cheers:
    pool: cheers
    grid_blocks: 1
    fill_mode: single
schedule:
  all_day:
    - start: "06:00"
      slots: 1
      program: p_cheers
      progression: sequential
  monday:
    - start: "20:00"
      slots: 1
      program: p_cheers
      progression: sequential
"""
        resolver = _make_resolver()
        dsl = parse_dsl(yaml_text)
        plan = compile_schedule(dsl, resolver, seed=42)
        # Monday: 06:00 from all_day + 20:00 from monday = 2 blocks
        assert len(plan["program_blocks"]) == 2
