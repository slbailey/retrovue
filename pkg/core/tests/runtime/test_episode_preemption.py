"""
Tests for episode duration vs grid slot behavior in the V2 compiler.

When an episode's duration exceeds a grid slot, bleed expands the slot.
When bleed is false, oversized episodes are rejected.
"""

from __future__ import annotations

from datetime import datetime, timezone as tz_mod

import pytest

from retrovue.runtime.asset_resolver import AssetMetadata, StubAssetResolver
from retrovue.runtime.schedule_compiler import (
    compile_schedule,
    parse_dsl,
)


def _make_resolver() -> StubAssetResolver:
    """Resolver with various episode durations."""
    r = StubAssetResolver()
    # Drama: 60-minute episodes (exceed 30-min grid)
    r.add("col.drama", AssetMetadata(
        type="collection", duration_sec=0,
        tags=("ep.drama.1",),
    ))
    r.register_collection("col.drama", ["ep.drama.1"])
    r.add("ep.drama.1", AssetMetadata(type="episode", duration_sec=3600, rating="PG"))

    # Sitcom: 22-minute episodes (fit in 30-min grid)
    r.add("col.sitcom", AssetMetadata(
        type="collection", duration_sec=0,
        tags=("ep.sitcom.1", "ep.sitcom.2", "ep.sitcom.3"),
    ))
    r.register_collection("col.sitcom", ["ep.sitcom.1", "ep.sitcom.2", "ep.sitcom.3"])
    for ep in ("ep.sitcom.1", "ep.sitcom.2", "ep.sitcom.3"):
        r.add(ep, AssetMetadata(type="episode", duration_sec=1320, rating="PG"))

    # Medical: 45-minute episodes
    r.add("col.medical", AssetMetadata(
        type="collection", duration_sec=0,
        tags=("ep.med.1",),
    ))
    r.register_collection("col.medical", ["ep.med.1"])
    r.add("ep.med.1", AssetMetadata(type="episode", duration_sec=2700, rating="PG"))
    return r


class TestBleedSlotExpansion:
    def test_60min_ep_with_bleed_expands_slot(self):
        """A 60-minute episode with bleed=true gets a 60-minute grid slot."""
        yaml_text = """
channel: test
broadcast_day: "2026-02-16"
timezone: America/New_York
pools:
  drama:
    match: { type: episode, collection: col.drama }
programs:
  p_drama:
    pool: drama
    grid_blocks: 1
    fill_mode: single
schedule:
  all_day:
    - start: "20:00"
      slots: 1
      program: p_drama
      progression: sequential
      bleed: true
"""
        resolver = _make_resolver()
        dsl = parse_dsl(yaml_text)
        plan = compile_schedule(dsl, resolver, seed=42)
        blocks = plan["program_blocks"]
        assert len(blocks) == 1
        assert blocks[0]["slot_duration_sec"] == 3600  # expanded to fit 60min
        assert blocks[0]["episode_duration_sec"] == 3600

    def test_45min_ep_with_bleed_gets_padded_slot(self):
        """A 45-minute episode with bleed=true gets a 60-minute slot (ceil to grid)."""
        yaml_text = """
channel: test
broadcast_day: "2026-02-16"
timezone: America/New_York
pools:
  medical:
    match: { type: episode, collection: col.medical }
programs:
  p_med:
    pool: medical
    grid_blocks: 1
    fill_mode: single
schedule:
  all_day:
    - start: "20:00"
      slots: 1
      program: p_med
      progression: sequential
      bleed: true
"""
        resolver = _make_resolver()
        dsl = parse_dsl(yaml_text)
        plan = compile_schedule(dsl, resolver, seed=42)
        blocks = plan["program_blocks"]
        assert len(blocks) == 1
        assert blocks[0]["slot_duration_sec"] == 3600  # 45min ceil to 60min grid
        assert blocks[0]["episode_duration_sec"] == 2700

    def test_normal_ep_fits_in_slot(self):
        """A 22-minute episode in 30-minute grid fits without expansion."""
        yaml_text = """
channel: test
broadcast_day: "2026-02-16"
timezone: America/New_York
pools:
  sitcom:
    match: { type: episode, collection: col.sitcom }
programs:
  p_sitcom:
    pool: sitcom
    grid_blocks: 1
    fill_mode: single
schedule:
  all_day:
    - start: "20:00"
      slots: 2
      program: p_sitcom
      progression: sequential
"""
        resolver = _make_resolver()
        dsl = parse_dsl(yaml_text)
        plan = compile_schedule(dsl, resolver, seed=42)
        blocks = plan["program_blocks"]
        assert len(blocks) == 2
        for b in blocks:
            assert b["slot_duration_sec"] == 1800  # 30min grid slot
            assert b["episode_duration_sec"] == 1320  # 22min fits

    def test_sequential_cursor_advances_per_execution(self):
        """Sequential cursor advances once per program execution."""
        yaml_text = """
channel: test
broadcast_day: "2026-02-16"
timezone: America/New_York
pools:
  sitcom:
    match: { type: episode, collection: col.sitcom }
programs:
  p_sitcom:
    pool: sitcom
    grid_blocks: 1
    fill_mode: single
schedule:
  all_day:
    - start: "20:00"
      slots: 3
      program: p_sitcom
      progression: sequential
"""
        from retrovue.runtime.progression_cursor import CursorStore
        resolver = _make_resolver()
        cursor_store = CursorStore()
        dsl = parse_dsl(yaml_text)
        plan = compile_schedule(dsl, resolver, seed=42, cursor_store=cursor_store)
        blocks = plan["program_blocks"]
        assert len(blocks) == 3
        # Each block should have a different asset (sequential progression)
        asset_ids = [b["asset_id"] for b in blocks]
        assert asset_ids[0] != asset_ids[1]
