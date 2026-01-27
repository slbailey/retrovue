#!/usr/bin/env python3
"""
Phase 0–4 + 2.5 demo: show concrete output at sample times.

Run from pkg/core with:  PYTHONPATH=src python examples/phase_demo.py

No server, no HTTP. Phase 2.5: Asset metadata (authoritative duration/path) drives Phase 3/4.
"""

from __future__ import annotations

from datetime import datetime, timezone

# Ensure we can import from src
if __name__ == "__main__":
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

from retrovue.runtime.clock import SteppedMasterClock
from retrovue.runtime.grid import grid_start, grid_end, elapsed_in_grid, remaining_in_grid, GRID_MINUTES, GRID_DURATION_MS
from retrovue.runtime.mock_schedule import get_mock_channel_plan, ScheduleItem
from retrovue.runtime.active_item_resolver import resolve_active_item, MockDurationConfig
from retrovue.runtime.asset_metadata import SAMPLECONTENT, FILLER
from retrovue.runtime.playout_pipeline import build_playout_segment

CHANNEL_ID = "mock"


def main() -> None:
    tz = timezone.utc
    base = datetime(2025, 1, 15, 0, 0, 0, tzinfo=tz)

    # Sample "now" times (Phase 0: we could use SteppedMasterClock; here we use fixed datetimes)
    sample_times = [
        base.replace(hour=10, minute=0, second=0, microsecond=0),   # 10:00
        base.replace(hour=10, minute=7, second=0, microsecond=0),   # 10:07
        base.replace(hour=10, minute=26, second=0, microsecond=0),  # 10:26
        base.replace(hour=10, minute=29, second=59, microsecond=0), # 10:29:59
        base.replace(hour=10, minute=30, second=0, microsecond=0),  # 10:30 (new grid)
    ]

    print("=" * 80)
    print("Phase 0 – Clock (sample: SteppedMasterClock)")
    print("=" * 80)
    clock = SteppedMasterClock(start=100.0)
    print(f"  clock.now() = {clock.now()}")
    clock.advance(10.0)
    print(f"  after advance(10): clock.now() = {clock.now()}")
    print()

    print("=" * 80)
    print("Phase 2 – Mock plan (duration-free)")
    print("=" * 80)
    plan = get_mock_channel_plan()
    items = plan.items_per_grid()
    print(f"  plan: {plan.name} (channel_id={plan.channel_id})")
    print(f"  items_per_grid: [ {items[0].id}, {items[1].id} ]")
    print()

    print("=" * 80)
    print("Phase 2.5 – Asset metadata (authoritative, no runtime I/O)")
    print("=" * 80)
    print(f"  SAMPLECONTENT: {SAMPLECONTENT.asset_path}  duration_ms={SAMPLECONTENT.duration_ms}")
    print(f"  FILLER:        {FILLER.asset_path}  duration_ms={FILLER.duration_ms}")
    print()
    print("Phase 3 – Duration config (from Phase 2.5 Assets)")
    print("=" * 80)
    cfg = MockDurationConfig.from_assets(SAMPLECONTENT)
    print(f"  filler_start_ms = samplecontent.duration_ms = {cfg.filler_start_ms}")
    print(f"  grid_duration_ms = {cfg.grid_duration_ms} (Phase 1)")
    print()

    print("=" * 80)
    print("Phase 1 + 3 – Grid and active item at sample times")
    print("=" * 80)
    print(f"  {'now':<12} | {'grid_start':<12} | {'grid_end':<12} | {'elapsed':<10} | {'remaining':<10} | elapsed_ms   | active_item")
    print("-" * 80)

    for now in sample_times:
        start = grid_start(now)
        end = grid_end(now)
        elapsed_td = elapsed_in_grid(now)
        remaining_td = remaining_in_grid(now)
        elapsed_ms = int(elapsed_td.total_seconds() * 1000)
        item = resolve_active_item(elapsed_ms, config=cfg)

        now_str = now.strftime("%H:%M:%S")
        start_str = start.strftime("%H:%M:%S")
        end_str = end.strftime("%H:%M:%S")
        elapsed_str = f"{int(elapsed_td.total_seconds()) // 60}:{(int(elapsed_td.total_seconds()) % 60):02d}"
        remaining_str = f"{int(remaining_td.total_seconds()) // 60}:{(int(remaining_td.total_seconds()) % 60):02d}"

        print(f"  {now_str:<12} | {start_str:<12} | {end_str:<12} | {elapsed_str:<10} | {remaining_str:<10} | {elapsed_ms:>11} | {item.id}")

    print()
    print("Phase 1 constants:")
    print(f"  GRID_MINUTES = {GRID_MINUTES},  GRID_DURATION_MS = {GRID_DURATION_MS}")
    print()
    print("Rule: elapsed_in_grid_ms < filler_start_ms → samplecontent;  else → filler")
    print(f"      filler_start_ms = samplecontent.duration_ms = {SAMPLECONTENT.duration_ms}")
    print()

    print("=" * 80)
    print("Phase 4 – PlayoutSegment at sample times (asset_path, start_offset_ms, hard_stop_time_ms)")
    print("=" * 80)
    print(f"  {'now':<12} | {'active_item':<12} | asset_path              | start_offset_ms | hard_stop_time_ms")
    print("-" * 80)

    for now in sample_times:
        start = grid_start(now)
        end = grid_end(now)
        elapsed_ms = int(elapsed_in_grid(now).total_seconds() * 1000)
        item = resolve_active_item(elapsed_ms, config=cfg)
        segment, cid = build_playout_segment(
            item, start, end, elapsed_ms, CHANNEL_ID,
            samplecontent_asset=SAMPLECONTENT, filler_asset=FILLER,
        )
        now_str = now.strftime("%H:%M:%S")
        path_short = (segment.asset_path.replace("assets/", "").replace(".mp4", "") or segment.asset_path)[:22]
        print(f"  {now_str:<12} | {item.id:<12} | {path_short:<22} | {segment.start_offset_ms:>15} | {segment.hard_stop_time_ms}")

    print()
    print("PlayoutRequest = PlayoutSegment + channel_id (envelope only; not a wire type).")
    print("LoadPreview carries: asset_path, start_offset_ms, hard_stop_time_ms.")


if __name__ == "__main__":
    main()
