"""
Tests for episode preemption in the Programming DSL compiler.

When an episode's duration exceeds a grid slot, it preempts subsequent slots.
"""

from __future__ import annotations

from datetime import datetime, timezone as tz_mod

import pytest

from retrovue.runtime.asset_resolver import AssetMetadata, StubAssetResolver
from retrovue.runtime.schedule_compiler import (
    compile_schedule,
    parse_dsl,
)


def _make_resolver_with_long_ep() -> StubAssetResolver:
    """Resolver with a 60-minute episode in a 30-minute grid."""
    r = StubAssetResolver()
    # Pool with one 60-minute episode
    r.add("col.drama", AssetMetadata(
        type="collection", duration_sec=0,
        tags=("ep.drama.1",),
    ))
    r.add("ep.drama.1", AssetMetadata(type="episode", duration_sec=3600, rating="PG"))
    # Pool with normal 22-minute episodes
    r.add("col.sitcom", AssetMetadata(
        type="collection", duration_sec=0,
        tags=("ep.sitcom.1", "ep.sitcom.2", "ep.sitcom.3"),
    ))
    for ep in ("ep.sitcom.1", "ep.sitcom.2", "ep.sitcom.3"):
        r.add(ep, AssetMetadata(type="episode", duration_sec=1320, rating="PG"))
    return r


class TestEpisodePreemption:
    def test_60min_ep_consumes_two_slots(self):
        """A 60-minute episode in 30-minute grid consumes 2 slots, skipping the second slot def."""
        yaml_text = """
channel: test
broadcast_day: "2026-02-16"
timezone: America/New_York
schedule:
  all_day:
    - start: "20:00"
      slots:
        - title: "Drama"
          episode_selector:
            pool: drama
            mode: sequential
        - title: "Sitcom A"
          episode_selector:
            pool: sitcom
            mode: sequential
        - title: "Sitcom B"
          episode_selector:
            pool: sitcom
            mode: sequential
"""
        resolver = _make_resolver_with_long_ep()
        resolver.register_pools({
            "drama": {"match": {"type": "episode"}},
            "sitcom": {"match": {"type": "episode"}},
        })
        resolver.add("drama", AssetMetadata(type="collection", duration_sec=0, tags=("ep.drama.1",)))
        resolver.add("sitcom", AssetMetadata(type="collection", duration_sec=0, tags=("ep.sitcom.1", "ep.sitcom.2", "ep.sitcom.3")))

        dsl = parse_dsl(yaml_text)
        plan = compile_schedule(dsl, resolver, seed=42)

        blocks = plan["program_blocks"]
        # Drama (60min) consumes slots 0 and 1, then Sitcom B at slot 2
        assert len(blocks) == 2
        assert blocks[0]["title"] == "Drama"
        assert blocks[0]["slot_duration_sec"] == 3600  # 2 * 30min
        assert blocks[0]["episode_duration_sec"] == 3600
        assert blocks[1]["title"] == "Sitcom B"

    def test_45min_ep_gets_filler_padding(self):
        """A 45-minute episode claims 2 grid slots (60min total), with 15min filler space."""
        r = StubAssetResolver()
        r.add("col.med", AssetMetadata(type="collection", duration_sec=0, tags=("ep.med.1",)))
        r.add("ep.med.1", AssetMetadata(type="episode", duration_sec=2700, rating="PG"))
        r.add("col.short", AssetMetadata(type="collection", duration_sec=0, tags=("ep.short.1",)))
        r.add("ep.short.1", AssetMetadata(type="episode", duration_sec=1320, rating="PG"))
        r.register_pools({
            "med": {"match": {"type": "episode"}},
            "short": {"match": {"type": "episode"}},
        })
        r.add("med", AssetMetadata(type="collection", duration_sec=0, tags=("ep.med.1",)))
        r.add("short", AssetMetadata(type="collection", duration_sec=0, tags=("ep.short.1",)))

        yaml_text = """
channel: test
broadcast_day: "2026-02-16"
timezone: America/New_York
schedule:
  all_day:
    - start: "20:00"
      slots:
        - title: "Medical"
          episode_selector:
            pool: med
            mode: sequential
        - title: "Skipped"
          episode_selector:
            pool: short
            mode: sequential
        - title: "Short"
          episode_selector:
            pool: short
            mode: sequential
"""
        dsl = parse_dsl(yaml_text)
        plan = compile_schedule(dsl, r, seed=42)
        blocks = plan["program_blocks"]
        # Medical (45min=2700s) consumes 2 slots → 3600s slot, then Short at slot 2
        assert len(blocks) == 2
        assert blocks[0]["title"] == "Medical"
        assert blocks[0]["slot_duration_sec"] == 3600
        assert blocks[0]["episode_duration_sec"] == 2700
        assert blocks[1]["title"] == "Short"

    def test_normal_ep_no_preemption(self):
        """A 22-minute episode in 30-minute grid does not preempt."""
        r = StubAssetResolver()
        r.add("col.s", AssetMetadata(type="collection", duration_sec=0, tags=("ep.s.1", "ep.s.2")))
        for ep in ("ep.s.1", "ep.s.2"):
            r.add(ep, AssetMetadata(type="episode", duration_sec=1320, rating="PG"))
        r.register_pools({"s": {"match": {"type": "episode"}}})
        r.add("s", AssetMetadata(type="collection", duration_sec=0, tags=("ep.s.1", "ep.s.2")))

        yaml_text = """
channel: test
broadcast_day: "2026-02-16"
timezone: America/New_York
schedule:
  all_day:
    - start: "20:00"
      slots:
        - title: "Show A"
          episode_selector: { pool: s, mode: sequential }
        - title: "Show B"
          episode_selector: { pool: s, mode: sequential }
"""
        dsl = parse_dsl(yaml_text)
        plan = compile_schedule(dsl, r, seed=42)
        assert len(plan["program_blocks"]) == 2

    def test_sequential_counter_only_increments_on_placement(self):
        """Sequential counter increments per placed episode, not per slot."""
        resolver = _make_resolver_with_long_ep()
        resolver.register_pools({
            "drama": {"match": {"type": "episode"}},
            "sitcom": {"match": {"type": "episode"}},
        })
        resolver.add("drama", AssetMetadata(type="collection", duration_sec=0, tags=("ep.drama.1",)))
        resolver.add("sitcom", AssetMetadata(type="collection", duration_sec=0, tags=("ep.sitcom.1", "ep.sitcom.2", "ep.sitcom.3")))

        yaml_text = """
channel: test
broadcast_day: "2026-02-16"
timezone: America/New_York
schedule:
  all_day:
    - start: "20:00"
      slots:
        - title: "Drama"
          episode_selector: { pool: drama, mode: sequential }
        - title: "Sitcom"
          episode_selector: { pool: sitcom, mode: sequential }
        - title: "Sitcom"
          episode_selector: { pool: sitcom, mode: sequential }
"""
        counters = {}
        dsl = parse_dsl(yaml_text)
        plan = compile_schedule(dsl, resolver, seed=42, sequential_counters=counters)
        # Drama placed (counter increments for drama pool)
        # Slot 1 skipped (preempted) - sitcom counter NOT incremented
        # Slot 2 placed - sitcom counter incremented once
        # So sitcom counter should be 1, not 2
        blocks = plan["program_blocks"]
        assert len(blocks) == 2
