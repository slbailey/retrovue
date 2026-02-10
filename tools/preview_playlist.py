#!/usr/bin/env python3
"""Preview Playlists produced by PlaylistScheduleManager or a static JSON schedule.

Operator verification tool.  Prints a human-readable table of segments,
validates tiling and frame math, and reports any anomalies.

Usage:
    # Default: 6-hour window starting 2026-02-07T06:00:00-05:00
    python tools/preview_playlist.py

    # Custom window (ISO 8601, timezone-aware)
    python tools/preview_playlist.py 2026-02-07T11:00:00Z 2026-02-07T23:00:00Z

    # Custom channel id
    python tools/preview_playlist.py --channel retrovue-classic

    # Static JSON schedule (no Core venv required)
    python tools/preview_playlist.py --json tools/static_schedule.json

Requires the Core venv (unless using --json):
    source pkg/core/.venv/bin/activate
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FPS: int = 30
EPSILON: float = 1e-9

# Default window: 6 hours starting at 2026-02-07 06:00 ET (11:00 UTC)
_DEFAULT_START = datetime(2026, 2, 7, 11, 0, 0, tzinfo=timezone.utc)
_DEFAULT_END = _DEFAULT_START + timedelta(hours=6)
_DEFAULT_CHANNEL = "retrovue-classic"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _time_short(dt: datetime) -> str:
    """HH:MM:SS.ffffff, trimming trailing zeros from microseconds."""
    base = dt.strftime("%H:%M:%S")
    if dt.microsecond:
        frac = f".{dt.microsecond:06d}".rstrip("0")
        return base + frac
    return base


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _basename(path: str) -> str:
    return Path(path).name


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate(playlists: list, fps: int) -> list[str]:
    """Run contract-level checks.  Return list of warning strings."""
    warnings: list[str] = []

    for pi, pl in enumerate(playlists):
        segs = pl.segments
        if not segs:
            warnings.append(f"Playlist {pi}: has 0 segments")
            continue

        # First segment starts at window start.
        if segs[0].start_at != pl.window_start_at:
            warnings.append(
                f"Playlist {pi}: first segment start {_iso(segs[0].start_at)} "
                f"!= window_start_at {_iso(pl.window_start_at)}"
            )

        # Abutment and frame math per segment.
        for i, seg in enumerate(segs):
            # duration_seconds == frame_count / fps
            expected_dur = seg.frame_count / fps
            if abs(seg.duration_seconds - expected_dur) > EPSILON:
                warnings.append(
                    f"Playlist {pi} seg {i} ({seg.segment_id}): "
                    f"duration_seconds={seg.duration_seconds} != "
                    f"frame_count/fps={expected_dur}"
                )

            # Non-negative frame_count
            if seg.frame_count < 0:
                warnings.append(
                    f"Playlist {pi} seg {i} ({seg.segment_id}): "
                    f"frame_count={seg.frame_count} is negative"
                )

            # Abutment with next segment (frame-based).
            if i < len(segs) - 1:
                seg_end = seg.start_at + timedelta(seconds=seg.frame_count / fps)
                next_start = segs[i + 1].start_at
                if seg_end != next_start:
                    delta_us = (next_start - seg_end).total_seconds() * 1_000_000
                    warnings.append(
                        f"Playlist {pi} seg {i}->{i+1}: gap/overlap "
                        f"({delta_us:+.1f} us) end={_iso(seg_end)} "
                        f"next_start={_iso(next_start)}"
                    )

        # Last segment closes window.
        last = segs[-1]
        computed_end = last.start_at + timedelta(seconds=last.frame_count / fps)
        if computed_end != pl.window_end_at:
            delta_us = (pl.window_end_at - computed_end).total_seconds() * 1_000_000
            warnings.append(
                f"Playlist {pi}: last segment end {_iso(computed_end)} "
                f"!= window_end_at {_iso(pl.window_end_at)} "
                f"(delta={delta_us:+.1f} us)"
            )

    # Multi-playlist abutment.
    for i in range(len(playlists) - 1):
        if playlists[i].window_end_at != playlists[i + 1].window_start_at:
            warnings.append(
                f"Playlist {i}->{i+1}: window gap "
                f"{_iso(playlists[i].window_end_at)} != "
                f"{_iso(playlists[i+1].window_start_at)}"
            )

    return warnings


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def _print_playlist(pi: int, pl, fps: int) -> None:
    segs = pl.segments

    print()
    print(f"=== PLAYLIST {pi + 1} ===")
    print(f"Window: {_iso(pl.window_start_at)}  ->  {_iso(pl.window_end_at)}")
    print(f"Channel: {pl.channel_id}   Timezone: {pl.channel_timezone}   Source: {pl.source}")
    print(f"Generated: {_iso(pl.generated_at)}")
    print(f"Segments: {len(segs)}")
    print()

    # Column widths.
    w_idx = 5
    w_type = 15
    w_time = 18
    w_frames = 8
    w_secs = 10
    w_asset = 30

    hdr = (
        f"{'Idx':<{w_idx}}"
        f"{'Type':<{w_type}}"
        f"{'Start':<{w_time}}"
        f"{'End':<{w_time}}"
        f"{'Frames':>{w_frames}}"
        f"{'Seconds':>{w_secs}}"
        f"  {'Asset':<{w_asset}}"
    )
    sep = (
        f"{'-' * w_idx}"
        f"+{'-' * (w_type - 1)}"
        f"+{'-' * (w_time - 1)}"
        f"+{'-' * (w_time - 1)}"
        f"+{'-' * w_frames}"
        f"+{'-' * w_secs}"
        f"+{'-' * (w_asset + 2)}"
    )

    print(hdr)
    print(sep)

    total_frames = 0
    for i, seg in enumerate(segs):
        seg_end = seg.start_at + timedelta(seconds=seg.frame_count / fps)
        total_frames += seg.frame_count
        print(
            f"{i:<{w_idx}}"
            f"{seg.type:<{w_type}}"
            f"{_time_short(seg.start_at):<{w_time}}"
            f"{_time_short(seg_end):<{w_time}}"
            f"{seg.frame_count:>{w_frames}}"
            f"{seg.duration_seconds:>{w_secs}.1f}"
            f"  {_basename(seg.asset_path):<{w_asset}}"
        )

    print()

    # Summary.
    window_seconds = (pl.window_end_at - pl.window_start_at).total_seconds()
    expected_frames = int(window_seconds * fps + 0.5)  # round_half_up
    delta = total_frames - expected_frames

    print(f"Total frames:    {total_frames}")
    print(f"Expected frames: {expected_frames}  (window={window_seconds:.1f}s * {fps}fps)")
    print(f"Delta:           {delta}")

    if delta != 0:
        print(f"  ** WARNING: frame delta is {delta}, expected 0 **")


# ---------------------------------------------------------------------------
# Static JSON schedule preview
# ---------------------------------------------------------------------------

def _ms_to_hms(ms: int) -> str:
    """Convert milliseconds to HH:MM:SS.mmm."""
    total_s, remainder_ms = divmod(ms, 1000)
    h, remainder_s = divmod(total_s, 3600)
    m, s = divmod(remainder_s, 60)
    if remainder_ms:
        return f"{h:02d}:{m:02d}:{s:02d}.{remainder_ms:03d}"
    return f"{h:02d}:{m:02d}:{s:02d}"


def _print_static_schedule(schedule: dict) -> None:
    blocks = schedule["blocks"]
    block_dur = schedule["block_duration_ms"]
    pad_tail = schedule["pad_tail_ms"]

    print()
    print("=" * 100)
    print("  Static Schedule Preview")
    print(f"  Channel:    {schedule['channel_id']}")
    print(f"  Generated:  {schedule['generated_at']}")
    print(f"  Blocks:     {schedule['total_blocks']}")
    print(f"  Duration:   {schedule['total_duration_ms'] / 3_600_000:.0f}h "
          f"({schedule['total_duration_ms']:,} ms)")
    print(f"  Block size: {block_dur / 60_000:.0f} min  "
          f"Pad tail: {pad_tail / 1000:.0f}s")
    print(f"  Filler:     {_basename(schedule['filler_path'])}")
    print()

    # Episode summary
    print("  Episodes in rotation:")
    for ep in schedule["episodes"]:
        print(f"    {ep['title']:<45s}  "
              f"{ep['duration_ms'] / 1000:8.1f}s  "
              f"({_ms_to_hms(ep['duration_ms'])})")
    print()
    print("=" * 100)
    print()

    # Column headers
    w_blk = 6
    w_time = 14
    w_type = 9
    w_dur = 12
    w_hms = 12
    w_asset = 45

    hdr = (
        f"{'Blk':<{w_blk}}"
        f"{'Abs Start':<{w_time}}"
        f"{'Abs End':<{w_time}}"
        f"{'Type':<{w_type}}"
        f"{'Duration ms':>{w_dur}}"
        f"{'Duration':>{w_hms}}"
        f"  {'Asset':<{w_asset}}"
    )
    sep = "-" * len(hdr)

    print(hdr)
    print(sep)

    warnings: list[str] = []

    for blk in blocks:
        bi = blk["block_index"]
        blk_start = blk["block_start_offset_ms"]
        seg_offset = blk_start

        seg_total = 0
        for seg in blk["segments"]:
            seg_ms = seg["segment_duration_ms"]
            seg_end = seg_offset + seg_ms
            seg_total += seg_ms

            asset = _basename(seg.get("asset_uri", "")) if seg.get("asset_uri") else "(black)"

            print(
                f"{bi:<{w_blk}}"
                f"{_ms_to_hms(seg_offset):<{w_time}}"
                f"{_ms_to_hms(seg_end):<{w_time}}"
                f"{seg['segment_type']:<{w_type}}"
                f"{seg_ms:>{w_dur},d}"
                f"{_ms_to_hms(seg_ms):>{w_hms}}"
                f"  {asset:<{w_asset}}"
            )
            seg_offset = seg_end

        # Validate block totals
        if seg_total != block_dur:
            warnings.append(
                f"Block {bi}: segment sum {seg_total:,} ms "
                f"!= block_duration {block_dur:,} ms"
            )
        if seg_offset != blk_start + block_dur:
            warnings.append(
                f"Block {bi}: end offset {seg_offset:,} ms "
                f"!= expected {blk_start + block_dur:,} ms"
            )

        # Check pad segment is last and correct duration
        last_seg = blk["segments"][-1]
        if last_seg["segment_type"] != "pad":
            warnings.append(f"Block {bi}: last segment is not pad")
        elif last_seg["segment_duration_ms"] != pad_tail:
            warnings.append(
                f"Block {bi}: pad is {last_seg['segment_duration_ms']} ms, "
                f"expected {pad_tail} ms"
            )

        # Print block separator
        print(f"{'':>{w_blk}}"
              f"{'--- block boundary ---'}")

    # Total duration check
    expected_total = len(blocks) * block_dur
    actual_total = schedule["total_duration_ms"]
    if actual_total != expected_total:
        warnings.append(
            f"total_duration_ms {actual_total:,} != "
            f"{len(blocks)} blocks * {block_dur:,} = {expected_total:,}"
        )

    # Contiguity check
    for i in range(1, len(blocks)):
        prev_end = blocks[i - 1]["block_start_offset_ms"] + block_dur
        curr_start = blocks[i]["block_start_offset_ms"]
        if prev_end != curr_start:
            warnings.append(
                f"Block {i-1}->{i}: gap/overlap "
                f"prev_end={prev_end:,} curr_start={curr_start:,}"
            )

    print()
    print(f"Total blocks:    {len(blocks)}")
    print(f"Total duration:  {actual_total:,} ms  "
          f"({actual_total / 3_600_000:.1f}h)")
    print()

    if warnings:
        print(f"WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  !! {w}")
    else:
        print("Validation: ALL CHECKS PASSED")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_dt(s: str) -> datetime:
    """Parse an ISO 8601 datetime string."""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise argparse.ArgumentTypeError(
            f"Datetime must be timezone-aware: {s!r}  (append Z or +HH:MM)"
        )
    return dt


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preview Playlists from PlaylistScheduleManager or a static JSON schedule."
    )
    parser.add_argument(
        "window_start",
        nargs="?",
        default=None,
        help="Window start (ISO 8601, tz-aware). Default: 2026-02-07T11:00:00Z",
    )
    parser.add_argument(
        "window_end",
        nargs="?",
        default=None,
        help="Window end (ISO 8601, tz-aware). Default: start + 6h",
    )
    parser.add_argument(
        "--channel",
        default=_DEFAULT_CHANNEL,
        help="Channel ID (default: retrovue-classic)",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=FPS,
        help="Frames per second for validation (default: 30)",
    )
    parser.add_argument(
        "--json",
        metavar="FILE",
        default=None,
        help="Path to a static JSON schedule file (no Core venv required)",
    )
    args = parser.parse_args()

    # -------------------------------------------------------------------
    # Static JSON path — no Core imports needed.
    # -------------------------------------------------------------------
    if args.json is not None:
        with open(args.json) as f:
            schedule = json.load(f)
        _print_static_schedule(schedule)
        return

    # -------------------------------------------------------------------
    # Dynamic playlist path — requires Core venv.
    # -------------------------------------------------------------------
    # Ensure pkg/core/src is importable when run from repo root.
    _CORE_SRC = Path(__file__).resolve().parent.parent / "pkg" / "core" / "src"
    if str(_CORE_SRC) not in sys.path:
        sys.path.insert(0, str(_CORE_SRC))

    from retrovue.scheduling.playlist_schedule_manager import PlaylistScheduleManager

    if args.window_start is not None:
        window_start = _parse_dt(args.window_start)
    else:
        window_start = _DEFAULT_START

    if args.window_end is not None:
        window_end = _parse_dt(args.window_end)
    else:
        window_end = window_start + timedelta(hours=6)

    fps = args.fps
    channel_id = args.channel

    # -----------------------------------------------------------------------
    # Produce playlists.
    # -----------------------------------------------------------------------

    psm = PlaylistScheduleManager()
    playlists = psm.get_playlists(channel_id, window_start, window_end)

    print("=" * 72)
    print("  PlaylistScheduleManager Preview")
    print(f"  Window: {_iso(window_start)}  ->  {_iso(window_end)}")
    print(f"  Channel: {channel_id}   FPS: {fps}")
    print(f"  Playlists returned: {len(playlists)}")
    print("=" * 72)

    for pi, pl in enumerate(playlists):
        _print_playlist(pi, pl, fps)

    # -----------------------------------------------------------------------
    # Aggregate summary across all playlists.
    # -----------------------------------------------------------------------

    all_segs = [s for pl in playlists for s in pl.segments]
    total_frames = sum(s.frame_count for s in all_segs)
    window_seconds = (window_end - window_start).total_seconds()
    expected_frames = int(window_seconds * fps + 0.5)

    if len(playlists) > 1:
        print()
        print("--- Aggregate (all playlists) ---")
        print(f"Total segments:  {len(all_segs)}")
        print(f"Total frames:    {total_frames}")
        print(f"Expected frames: {expected_frames}")
        print(f"Delta:           {total_frames - expected_frames}")

    # -----------------------------------------------------------------------
    # Validation.
    # -----------------------------------------------------------------------

    warnings = _validate(playlists, fps)

    print()
    if warnings:
        print(f"WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  !! {w}")
    else:
        print("Validation: ALL CHECKS PASSED")

    print()


if __name__ == "__main__":
    main()
