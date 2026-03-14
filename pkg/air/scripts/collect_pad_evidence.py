#!/usr/bin/env python3
"""
Evidence collection: correlate black-frame (PAD) events with cause.

Extracts from an AIR log:
  - FRAME_ALIGNMENT_AHEAD_PAD  (ahead-of-scheduler path)
  - TAKE_PAD_ENTER / TAKE_PAD_EXIT
  - INV-HANDOFF-DIAG
  - Underflow-related (INV-VIDEO-LOOKAHEAD-001: UNDERFLOW, AUDIO_UNDERFLOW_SILENCE, SEAM_DEBUG_UNDERFLOW)

Goal: prove whether intermittent black frames come from the ahead-of-scheduler PAD path
      or from another PAD/underflow/transition path.

Usage:
  python3 pkg/air/scripts/collect_pad_evidence.py pkg/air/logs/hbo-air.log
  python3 pkg/air/scripts/collect_pad_evidence.py pkg/air/logs/hbo-air.log --csv > pad_evidence.csv
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


# Patterns: (key for output, pattern)
EVENT_PATTERNS = [
    ("PAD_CAUSE", re.compile(r"\[PipelineManager\] PAD_CAUSE\s+tick=(\d+)\s+cause=(\S+)")),
    ("FRAME_ALIGNMENT_AHEAD_PAD", re.compile(r"\[PipelineManager\] FRAME_ALIGNMENT_AHEAD_PAD\s+tick=(\d+)\s+selected_src=(\d+)\s+front_index=(\d+)")),
    ("TAKE_PAD_ENTER", re.compile(r"\[PipelineManager\] TAKE_PAD_ENTER\s+tick=(\d+)\s+slot=(\w+)")),
    ("TAKE_PAD_EXIT", re.compile(r"\[PipelineManager\] TAKE_PAD_EXIT\s+tick=(\d+)\s+slot=(\w+)\s+block=([^\s]+)")),
    ("INV-HANDOFF-DIAG", re.compile(r"\[PipelineManager\] INV-HANDOFF-DIAG\s+tick=(\d+)\s+selected_src=(\d+)\s+actual_src_emitted=(\d+)\s+frame_gap=(-?\d+)")),
    ("VIDEO_UNDERFLOW", re.compile(r"\[PipelineManager\] INV-VIDEO-LOOKAHEAD-001: UNDERFLOW\s+frame=(\d+)")),
    ("AUDIO_UNDERFLOW", re.compile(r"\[PipelineManager\] AUDIO_UNDERFLOW_SILENCE\s+frame=(\d+)")),
    ("SEAM_UNDERFLOW", re.compile(r"\[PipelineManager\] SEAM_DEBUG_UNDERFLOW\s+tick=(\d+)")),
    ("PAD_SEAM_OVERRIDE", re.compile(r"\[PipelineManager\] PAD_SEAM_OVERRIDE\s+tick=(\d+)")),
]


@dataclass
class Event:
    kind: str
    tick: int
    line_no: int
    raw: str
    extra: dict = field(default_factory=dict)

    def __lt__(self, other: Event) -> bool:
        return (self.tick, self.line_no) < (other.tick, other.line_no)


def parse_log(path: Path) -> list[Event]:
    events: list[Event] = []
    with open(path, "r", errors="replace") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.rstrip()
            for kind, pat in EVENT_PATTERNS:
                m = pat.search(line)
                if m:
                    g = m.groups()
                    tick = int(g[0])
                    extra = {}
                    if kind == "PAD_CAUSE" and len(g) >= 2:
                        extra = {"cause": g[1]}
                    elif kind == "FRAME_ALIGNMENT_AHEAD_PAD" and len(g) >= 3:
                        extra = {"selected_src": g[1], "front_index": g[2]}
                    elif kind == "TAKE_PAD_ENTER" and len(g) >= 2:
                        extra = {"slot": g[1]}
                    elif kind == "TAKE_PAD_EXIT" and len(g) >= 3:
                        extra = {"slot": g[1], "block": g[2]}
                    elif kind == "INV-HANDOFF-DIAG" and len(g) >= 4:
                        extra = {"selected_src": g[1], "actual_src_emitted": g[2], "frame_gap": g[3]}
                    if kind == "PAD_SEAM_OVERRIDE" and len(g) >= 1:
                        extra = {}
                    events.append(Event(kind=kind, tick=tick, line_no=line_no, raw=line.strip(), extra=extra))
                    break
    return sorted(events)


def build_pad_intervals(events: list[Event]) -> list[tuple[int, int, list[Event]]]:
    """Build (tick_start, tick_end, events_in_interval) for each PAD run."""
    intervals: list[tuple[int, int, list[Event]]] = []
    pad_enters = [e for e in events if e.kind == "TAKE_PAD_ENTER"]
    pad_exits = [e for e in events if e.kind == "TAKE_PAD_EXIT"]
    # Match ENTER to next EXIT by tick order
    for enter in pad_enters:
        t_start = enter.tick
        exits_after = [e for e in pad_exits if e.tick >= t_start]
        t_end = exits_after[0].tick if exits_after else t_start
        in_interval = [e for e in events if t_start <= e.tick <= t_end]
        intervals.append((t_start, t_end, in_interval))
    return intervals


def infer_cause(interval_events: list[Event]) -> str:
    kinds = {e.kind for e in interval_events}
    # Explicit PAD_CAUSE from pipeline: one label per tick; use dominant cause in interval.
    pad_causes = [e.extra.get("cause") for e in interval_events if e.kind == "PAD_CAUSE" and e.extra.get("cause")]
    if pad_causes:
        from collections import Counter
        return Counter(pad_causes).most_common(1)[0][0]
    # Legacy / logs without PAD_CAUSE: infer from other events.
    if "FRAME_ALIGNMENT_AHEAD_PAD" in kinds:
        return "ahead_of_scheduler"
    if "VIDEO_UNDERFLOW" in kinds or "AUDIO_UNDERFLOW" in kinds or "SEAM_UNDERFLOW" in kinds:
        return "underflow"
    if any(e.tick == 0 for e in interval_events if e.kind == "TAKE_PAD_ENTER"):
        return "startup"
    if "PAD_SEAM_OVERRIDE" in kinds:
        return "pad_seam"
    # Decoder behind: INV-HANDOFF-DIAG with frame_gap < 0 in this interval (repeat/PAD due to missing frame).
    if any(e.kind == "INV-HANDOFF-DIAG" and int(e.extra.get("frame_gap", 0)) < 0 for e in interval_events):
        return "decoder_behind"
    return "unknown_fallback"


def report_text(events: list[Event], path: Path) -> None:
    print(f"# PAD / alignment / underflow evidence: {path}")
    print(f"# Total events extracted: {len(events)}")
    print()

    # Counts by kind
    from collections import Counter
    counts = Counter(e.kind for e in events)
    print("## Counts by event type")
    for kind, n in counts.most_common():
        print(f"  {kind}: {n}")
    print()

    # FRAME_ALIGNMENT_AHEAD_PAD: how many and when
    ahead = [e for e in events if e.kind == "FRAME_ALIGNMENT_AHEAD_PAD"]
    print("## FRAME_ALIGNMENT_AHEAD_PAD (ahead-of-scheduler PAD path)")
    if not ahead:
        print("  (none in this log)")
    else:
        for e in ahead:
            print(f"  tick={e.tick} selected_src={e.extra.get('selected_src')} front_index={e.extra.get('front_index')}  # line {e.line_no}")
    print()

    # PAD intervals with inferred cause
    intervals = build_pad_intervals(events)
    cause_counts: dict[str, int] = {}
    print("## PAD intervals (TAKE_PAD_ENTER → TAKE_PAD_EXIT) with inferred cause")
    print("  [tick_start, tick_end] duration cause")
    print("  ----------------------------------------")
    for t_start, t_end, in_ev in intervals:
        cause = infer_cause(in_ev)
        cause_counts[cause] = cause_counts.get(cause, 0) + 1
        duration = t_end - t_start + 1 if t_end >= t_start else 0
        print(f"  [{t_start}, {t_end}] duration={duration}  cause={cause}")
    print()
    print("## Cause summary (PAD intervals) — rank for next mitigation")
    ranked = sorted(cause_counts.items(), key=lambda x: -x[1])
    for c, n in ranked:
        print(f"  {c}: {n} intervals")
    print()
    print("  Named causes: block_transition, segment_transition, live_buffer_empty, startup_bootstrap, ahead_no_hold, unknown_fallback.")
    print()

    # Chronological snippet: first 100 events
    print("## Chronological event list (first 150 events)")
    for e in events[:150]:
        extra_str = " ".join(f"{k}={v}" for k, v in e.extra.items())
        print(f"  L{e.line_no} tick={e.tick} {e.kind} {extra_str}")


def report_csv(events: list[Event], path: Path) -> None:
    import csv
    w = csv.writer(sys.stdout)
    w.writerow(["line_no", "tick", "kind", "selected_src", "actual_src_emitted", "frame_gap", "front_index", "slot", "block"])
    for e in events:
        row = [
            e.line_no,
            e.tick,
            e.kind,
            e.extra.get("selected_src", ""),
            e.extra.get("actual_src_emitted", ""),
            e.extra.get("frame_gap", ""),
            e.extra.get("front_index", ""),
            e.extra.get("slot", ""),
            e.extra.get("block", ""),
        ]
        w.writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract PAD/alignment/underflow events from AIR log for cause correlation.")
    ap.add_argument("log", type=Path, help="Path to AIR log (e.g. pkg/air/logs/hbo-air.log)")
    ap.add_argument("--csv", action="store_true", help="Output CSV instead of text report")
    args = ap.parse_args()
    if not args.log.exists():
        print(f"Error: {args.log} not found", file=sys.stderr)
        return 1
    events = parse_log(args.log)
    if args.csv:
        report_csv(events, args.log)
    else:
        report_text(events, args.log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
