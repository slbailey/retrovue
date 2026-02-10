#!/usr/bin/env python3
"""
Generate a static 24-hour JSON schedule for burn-in testing.

Produces 48 × 30-minute blocks, rotating through 3 Cheers episodes.
Each block: [episode][filler][pad (10 s)]

Usage:
    python tools/gen_static_schedule.py
    python tools/gen_static_schedule.py -o schedules/my_day.json

Output is written to tools/static_schedule.json by default.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# ──────────────────────────────────────────────────────────────────────
# Block timing constants (must match burn_in.py)
# ──────────────────────────────────────────────────────────────────────
BLOCK_DURATION_MS = 30 * 60 * 1000          # 1,800,000 ms
PAD_TAIL_MS       = 10_000                   # 10 s
PLANNED_WINDOW_MS = BLOCK_DURATION_MS - PAD_TAIL_MS  # 1,790,000 ms

BLOCKS_PER_DAY = 48  # 24 h / 0.5 h

FILLER_PATH = "/opt/retrovue/assets/filler.mp4"

# ──────────────────────────────────────────────────────────────────────
# Episodes — durations from PlaylistScheduleManager (ffprobe values)
# ──────────────────────────────────────────────────────────────────────
EPISODES = [
    {
        "title": "S01E01 - Give Me a Ring Sometime",
        "asset_path": (
            "/opt/retrovue/assets/"
            "Cheers (1982) - S01E01 - Give Me a Ring Sometime "
            "[Bluray-720p][AAC 2.0][x264]-Bordure.mp4"
        ),
        "duration_ms": 1_501_625,   # 1501.625125 s → int(… * 1000)
    },
    {
        "title": "S01E02 - Sam's Women",
        "asset_path": (
            "/opt/retrovue/assets/"
            "Cheers (1982) - S01E02 - Sams Women "
            "[AMZN WEBDL-720p][AAC 2.0][x264]-Trollhd.mp4"
        ),
        "duration_ms": 1_333_457,   # 1333.457125 s
    },
    {
        "title": "S01E03 - The Tortelli Tort",
        "asset_path": (
            "/opt/retrovue/assets/"
            "Cheers (1982) - S01E03 - The Tortelli Tort "
            "[Bluray-720p][AAC 2.0][x264]-Bordure.mp4"
        ),
        "duration_ms": 1_499_873,   # 1499.873375 s
    },
]


def generate_schedule() -> dict:
    blocks = []

    for i in range(BLOCKS_PER_DAY):
        ep = EPISODES[i % len(EPISODES)]
        ep_ms = min(ep["duration_ms"], PLANNED_WINDOW_MS)
        filler_ms = PLANNED_WINDOW_MS - ep_ms
        pad_ms = PAD_TAIL_MS

        # Sanity: gap-free
        assert ep_ms + filler_ms + pad_ms == BLOCK_DURATION_MS, (
            f"Block {i}: {ep_ms} + {filler_ms} + {pad_ms} "
            f"!= {BLOCK_DURATION_MS}"
        )

        segments = [
            {
                "segment_type": "episode",
                "segment_index": 0,
                "asset_uri": ep["asset_path"],
                "asset_start_offset_ms": 0,
                "segment_duration_ms": ep_ms,
            },
            {
                "segment_type": "filler",
                "segment_index": 1,
                "asset_uri": FILLER_PATH,
                "asset_start_offset_ms": 0,
                "segment_duration_ms": filler_ms,
            },
            {
                "segment_type": "pad",
                "segment_index": 2,
                "segment_duration_ms": pad_ms,
            },
        ]

        block_start_offset_ms = i * BLOCK_DURATION_MS

        blocks.append({
            "block_index": i,
            "block_start_offset_ms": block_start_offset_ms,
            "block_duration_ms": BLOCK_DURATION_MS,
            "episode_title": ep["title"],
            "segments": segments,
        })

    schedule = {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "description": (
            "Static 24-hour burn-in schedule. "
            "48 × 30-min blocks rotating 3 Cheers episodes. "
            "Each block: [episode][filler][pad 10s]."
        ),
        "channel_id": "retrovue-classic",
        "block_duration_ms": BLOCK_DURATION_MS,
        "pad_tail_ms": PAD_TAIL_MS,
        "total_blocks": BLOCKS_PER_DAY,
        "total_duration_ms": BLOCKS_PER_DAY * BLOCK_DURATION_MS,
        "filler_path": FILLER_PATH,
        "episodes": [
            {
                "title": ep["title"],
                "asset_path": ep["asset_path"],
                "duration_ms": ep["duration_ms"],
            }
            for ep in EPISODES
        ],
        "blocks": blocks,
    }

    return schedule


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a static 24-hour burn-in schedule JSON."
    )
    default_out = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "static_schedule.json",
    )
    parser.add_argument(
        "-o", "--output",
        default=default_out,
        help=f"Output file path (default: {default_out})",
    )
    args = parser.parse_args()

    schedule = generate_schedule()

    with open(args.output, "w") as f:
        json.dump(schedule, f, indent=2)

    # Print summary
    print(f"Wrote {args.output}")
    print(f"  {schedule['total_blocks']} blocks, "
          f"{schedule['total_duration_ms'] / 3_600_000:.0f}h")
    for i, blk in enumerate(schedule["blocks"][:6]):
        ep_seg = blk["segments"][0]
        fl_seg = blk["segments"][1]
        pd_seg = blk["segments"][2]
        print(
            f"  Block {blk['block_index']:2d}  "
            f"{blk['episode_title']:<40s}  "
            f"ep={ep_seg['segment_duration_ms']/1000:7.1f}s  "
            f"filler={fl_seg['segment_duration_ms']/1000:6.1f}s  "
            f"pad={pd_seg['segment_duration_ms']/1000:4.1f}s"
        )
    if len(schedule["blocks"]) > 6:
        print(f"  ... ({len(schedule['blocks']) - 6} more blocks)")


if __name__ == "__main__":
    main()
