#!/usr/bin/env python3
"""
Analyze FENCE_AUDIO_PAD warnings in AIR logs (Hypothesis H1).

Finds every "WARNING FENCE_AUDIO_PAD: audio not primed" and extracts context:
- Nearest preceding SEGMENT_TAKE_COMMIT and whether to_segment is PAD
- VideoBuffer:PAD_A_VIDEO_BUFFER / PAD_B_VIDEO_BUFFER StartFilling
- PADDED_GAP_ENTER, TAKE_PAD_ENTER, DEGRADED_TAKE_MODE, FENCE_* lines
- fps / RationalFps mentions and tick numbers

Output: summary table, per-occurrence reports, and a JSON file for diffing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


WARNING_PATTERN = "WARNING FENCE_AUDIO_PAD: audio not primed"
SEGMENT_TAKE_COMMIT_PATTERN = re.compile(
    r"SEGMENT_TAKE_COMMIT\s+tick=(\d+)\s+from_segment=\d+\s+to_segment=\d+\s+\((\w+)\)"
)
TICK_PATTERN = re.compile(r"tick=(\d+)")
PAD_B_STARTFILLING = "PAD_B_VIDEO_BUFFER"
PAD_A_STARTFILLING = "PAD_A_VIDEO_BUFFER"
PADDED_GAP_ENTER = "PADDED_GAP_ENTER"
TAKE_PAD_ENTER = "TAKE_PAD_ENTER"
DEGRADED_TAKE_MODE = "DEGRADED_TAKE_MODE"
FENCE_PREFIX = "FENCE_"
FPS_PATTERN = re.compile(r"fps[=\s]|\d+fps|RationalFps|30000/1001|60/1", re.I)


def find_default_log() -> Path | None:
    """Return path to cheers-24-7-air.log if it exists in common locations."""
    candidates = [
        Path("cheers-24-7-air.log"),
        Path("pkg/air/logs/cheers-24-7-air.log"),
        Path(__file__).resolve().parent.parent / "pkg/air/logs/cheers-24-7-air.log",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def parse_args() -> argparse.Namespace:
    default_log = find_default_log()
    parser = argparse.ArgumentParser(
        description="Analyze WARNING FENCE_AUDIO_PAD in AIR logs (Hypothesis H1)."
    )
    parser.add_argument(
        "log_path",
        nargs="?" if default_log else None,
        default=str(default_log) if default_log else None,
        type=Path,
        help="Log file path (default: cheers-24-7-air.log if present in cwd or pkg/air/logs)",
    )
    parser.add_argument(
        "-b", "--before",
        type=int,
        default=250,
        help="Context lines before each warning (default: 250)",
    )
    parser.add_argument(
        "-a", "--after",
        type=int,
        default=50,
        help="Context lines after each warning (default: 50)",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Only print summary table and JSON path; skip per-occurrence reports",
    )
    args = parser.parse_args()
    if args.log_path is None:
        parser.error("Log file path required (cheers-24-7-air.log not found).")
    args.log_path = Path(args.log_path)
    return args


def load_lines(path: Path) -> list[str]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.readlines()


def extract_tick(line: str) -> int | None:
    m = TICK_PATTERN.search(line)
    return int(m.group(1)) if m else None


def analyze_window(
    lines: list[str],
    warn_line_idx: int,
    before: int,
    after: int,
) -> dict:
    """Build one record for a single warning occurrence."""
    start = max(0, warn_line_idx - before)
    end = min(len(lines), warn_line_idx + after + 1)
    window = lines[start:end]
    warn_line = lines[warn_line_idx]
    warn_tick = extract_tick(warn_line)

    # Nearest preceding SEGMENT_TAKE_COMMIT (search backward from warning line in window)
    warn_pos_in_window = warn_line_idx - start
    nearest_commit_line: str | None = None
    nearest_commit_tick: int | None = None
    to_segment_pad = False
    for i in range(warn_pos_in_window - 1, -1, -1):
        line = window[i]
        if "SEGMENT_TAKE_COMMIT" in line:
            nearest_commit_line = line.strip()
            m = SEGMENT_TAKE_COMMIT_PATTERN.search(line)
            if m:
                nearest_commit_tick = int(m.group(1))
                to_segment_pad = m.group(2) == "PAD"
            break

    has_pad_b_startfilling = any(
        PAD_B_STARTFILLING in ln and "StartFilling" in ln for ln in window
    )
    has_pad_a_startfilling = any(
        PAD_A_STARTFILLING in ln and "StartFilling" in ln for ln in window
    )

    padded_gap_lines = [ln.strip() for ln in window if PADDED_GAP_ENTER in ln]
    take_pad_lines = [ln.strip() for ln in window if TAKE_PAD_ENTER in ln]
    degraded_lines = [ln.strip() for ln in window if DEGRADED_TAKE_MODE in ln]
    fence_lines = [ln.strip() for ln in window if FENCE_PREFIX in ln and "FENCE_AUDIO_PAD" not in ln]
    fps_mentions = [ln.strip() for ln in window if FPS_PATTERN.search(ln)]

    # Tick from nearest StartFilling in window (for report)
    pad_b_tick: int | None = None
    pad_a_tick: int | None = None
    for ln in window:
        if PAD_B_STARTFILLING in ln and "StartFilling" in ln:
            t = extract_tick(ln)
            if t is not None:
                pad_b_tick = t
        if PAD_A_STARTFILLING in ln and "StartFilling" in ln:
            t = extract_tick(ln)
            if t is not None:
                pad_a_tick = t

    return {
        "warning_line_number": warn_line_idx + 1,
        "warning_tick": warn_tick,
        "nearest_commit_line": nearest_commit_line,
        "nearest_commit_tick": nearest_commit_tick,
        "to_segment_pad": to_segment_pad,
        "has_pad_b_startfilling": has_pad_b_startfilling,
        "has_pad_a_startfilling": has_pad_a_startfilling,
        "pad_b_startfilling_tick": pad_b_tick,
        "pad_a_startfilling_tick": pad_a_tick,
        "padded_gap_enter_lines": padded_gap_lines,
        "take_pad_enter_lines": take_pad_lines,
        "degraded_take_mode_lines": degraded_lines,
        "fence_marker_lines": fence_lines[:20],
        "fps_mentions": fps_mentions[:10],
    }


def run(log_path: Path, before: int, after: int, quiet: bool) -> list[dict]:
    lines = load_lines(log_path)
    warning_indices = [i for i, ln in enumerate(lines) if WARNING_PATTERN in ln]
    records = []
    for idx in warning_indices:
        rec = analyze_window(lines, idx, before, after)
        rec["warning_line_content"] = lines[idx].strip()
        records.append(rec)
    return records


def summary_table(records: list[dict]) -> str:
    total = len(records)
    with_commit_pad = sum(1 for r in records if r.get("to_segment_pad"))
    with_pad_b = sum(1 for r in records if r.get("has_pad_b_startfilling"))
    with_pad_a = sum(1 for r in records if r.get("has_pad_a_startfilling"))
    with_both = sum(
        1 for r in records
        if r.get("to_segment_pad") and r.get("has_pad_b_startfilling")
    )
    with_padded_gap = sum(
        1 for r in records
        if r.get("padded_gap_enter_lines")
    )
    lines = [
        "Summary (FENCE_AUDIO_PAD: audio not primed)",
        "=" * 60,
        f"  total warnings                              {total}",
        f"  warnings with to_segment=PAD commit nearby  {with_commit_pad}",
        f"  warnings with PAD_B StartFilling present   {with_pad_b}",
        f"  warnings with PAD_A StartFilling present   {with_pad_a}",
        f"  warnings with both (to_segment=PAD + PAD_B) {with_both}",
        f"  warnings with PADDED_GAP_ENTER nearby       {with_padded_gap}",
        "=" * 60,
    ]
    return "\n".join(lines)


def occurrence_report(index: int, rec: dict) -> str:
    parts = [
        f"[{index + 1}] tick={rec.get('warning_tick', '?')}",
        f"  nearest commit: {rec.get('nearest_commit_line') or 'none'}",
        f"  to_segment=PAD: {rec.get('to_segment_pad', False)}",
        f"  PAD_A StartFilling: {rec.get('has_pad_a_startfilling', False)}",
        f"  PAD_B StartFilling: {rec.get('has_pad_b_startfilling', False)}",
        f"  markers: PADDED_GAP_ENTER={bool(rec.get('padded_gap_enter_lines'))}, "
        f"DEGRADED_TAKE_MODE={bool(rec.get('degraded_take_mode_lines'))}, "
        f"TAKE_PAD_ENTER={bool(rec.get('take_pad_enter_lines'))}",
    ]
    return "\n".join(parts)


def main() -> int:
    args = parse_args()
    if not args.log_path.is_file():
        print(f"Error: log file not found: {args.log_path}", file=sys.stderr)
        return 1

    records = run(args.log_path, args.before, args.after, args.quiet)

    print(summary_table(records))
    print()

    if not args.quiet and records:
        print("Per-occurrence reports")
        print("-" * 60)
        for i, rec in enumerate(records[:50]):  # cap at 50 to avoid huge output
            print(occurrence_report(i, rec))
            print()
        if len(records) > 50:
            print(f"... ({len(records) - 50} more occurrences omitted)")
            print()

    out_json = args.log_path.with_suffix(args.log_path.suffix + ".fence_audio_pad.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(
            {"log_path": str(args.log_path), "total_warnings": len(records), "records": records},
            f,
            indent=2,
        )
    print(f"JSON written: {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
