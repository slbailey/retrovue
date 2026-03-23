"""Channel DSL commands: compile, inspect, simulate.

Offline commands that work directly from channel YAML files
without requiring a running database. Uses the schedule compiler
pipeline with a DB-backed asset resolver when available.

Usage:
    retrovue channel compile config/channels/hbo.yaml
    retrovue channel inspect config/channels/hbo.yaml
    retrovue channel simulate config/channels/hbo.yaml --time 2026-04-01T20:30:00
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Any

import typer

from retrovue.config.config_loader import load_defaults
from retrovue.runtime.schedule_compiler import compile_schedule, parse_dsl


app = typer.Typer(name="channel-dsl", help="Channel DSL compilation and inspection")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_and_compile(yaml_path: str, broadcast_day: str | None = None) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    """Load a channel YAML, resolve assets, and compile.

    Returns (plan, resolver, dsl) so callers can look up asset metadata
    and read channel configuration (traffic profiles, etc.).
    """
    path = Path(yaml_path)
    if not path.exists():
        typer.echo(f"Error: {yaml_path} not found", err=True)
        raise typer.Exit(1)

    dsl = parse_dsl(path.read_text())

    # Set broadcast_day if not in DSL and not provided
    if "broadcast_day" not in dsl:
        if broadcast_day:
            dsl["broadcast_day"] = broadcast_day
        else:
            dsl["broadcast_day"] = date.today().isoformat()

    # Load resolved config (scheduling constants)
    resolved_config = dict(load_defaults())

    # Build resolver from DB
    resolver = _build_resolver()

    plan = compile_schedule(
        dsl,
        resolver,
        resolved_config=resolved_config,
    )
    return plan, resolver, dsl


def _build_resolver():
    """Build a CatalogAssetResolver from the database."""
    try:
        from retrovue.infra.uow import session
        from retrovue.runtime.catalog_resolver import CatalogAssetResolver
        with session() as db:
            return CatalogAssetResolver(db)
    except Exception as e:
        typer.echo(f"Error: Could not connect to database: {e}", err=True)
        typer.echo("The compile/inspect/simulate commands require database access", err=True)
        typer.echo("to resolve asset pools and metadata.", err=True)
        raise typer.Exit(1)


def _fmt_ms(ms: int) -> str:
    """Format milliseconds as human-readable duration."""
    total_sec = ms // 1000
    h = total_sec // 3600
    m = (total_sec % 3600) // 60
    s = total_sec % 60
    if h > 0:
        return f"{h}h{m:02d}m{s:02d}s"
    if m > 0:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def _fmt_time(iso_str: str) -> str:
    """Format ISO datetime to short local time."""
    dt = datetime.fromisoformat(iso_str)
    return dt.strftime("%H:%M:%S")


def _resolve_traffic_profile(dsl: dict[str, Any], block: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve the traffic profile that applies to a block.

    Returns the profile dict or None if no traffic config exists.
    """
    traffic = dsl.get("traffic", {})
    if not traffic:
        return None

    profiles = traffic.get("profiles", {})
    if not profiles:
        return None

    # Block-level override → channel default
    profile_name = block.get("traffic_profile") or traffic.get("default") or traffic.get("default_profile")
    if not profile_name or profile_name not in profiles:
        return None

    profile = dict(profiles[profile_name])
    profile["_name"] = profile_name
    return profile


AVG_AD_DURATION_MS = 30_000  # 30 seconds assumed for slot estimation


def _preview_break_fill(dur_ms: int, channel_slug: str) -> list[dict]:
    """Query available traffic assets and simulate packing a break.

    Returns a list of {filename, duration_ms, type} dicts showing what
    would fill the break. Read-only — does not log plays or modify state.
    """
    try:
        from retrovue.infra.uow import session
        from retrovue.catalog.db_asset_library import DatabaseAssetLibrary
    except ImportError:
        return []

    try:
        with session() as db:
            lib = DatabaseAssetLibrary(db, channel_slug=channel_slug)
            # Get candidates that fit (generous count for variety)
            candidates = lib.get_filler_assets(max_duration_ms=dur_ms, count=50)
            if not candidates:
                return []

            # Simulate greedy packing
            packed = []
            remaining = dur_ms
            for c in candidates:
                if remaining <= 0:
                    break
                if c.duration_ms <= remaining:
                    packed.append({
                        "filename": Path(c.asset_uri).name if c.asset_uri else "?",
                        "duration_ms": c.duration_ms,
                        "type": c.asset_type or "filler",
                    })
                    remaining -= c.duration_ms
            return packed
    except Exception:
        return []


def _asset_label(asset_id: str, resolver: Any) -> str:
    """Resolve an asset_id to a human-readable label: 'filename (short_id)'."""
    if not asset_id:
        return ""
    try:
        meta = resolver.lookup(asset_id)
        filename = Path(meta.file_uri).name if meta.file_uri else ""
        short_id = asset_id[:8] if len(asset_id) > 8 else asset_id
        if filename:
            return f"{filename} ({short_id})"
        if meta.title:
            return f"{meta.title} ({short_id})"
        return short_id
    except (KeyError, AttributeError):
        short_id = asset_id[:8] if len(asset_id) > 8 else asset_id
        return short_id


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command("compile")
def compile_cmd(
    yaml_path: str = typer.Argument(..., help="Path to channel YAML file"),
    broadcast_day: str = typer.Option(None, "--day", help="Broadcast day (YYYY-MM-DD). Default: today."),
    pretty: bool = typer.Option(True, "--pretty/--compact", help="Pretty-print JSON output"),
):
    """Compile a channel YAML into a program schedule.

    Runs the full schedule compiler pipeline and outputs the compiled
    plan as JSON to stdout. The output includes compiled_segments with
    break-aware content acts, filler placeholders, and presentation.
    """
    plan, _resolver, _dsl = _load_and_compile(yaml_path, broadcast_day)
    indent = 2 if pretty else None
    typer.echo(json.dumps(plan, indent=indent, default=str))


@app.command("inspect")
def inspect_cmd(
    yaml_path: str = typer.Argument(..., help="Path to channel YAML file"),
    broadcast_day: str = typer.Option(None, "--day", help="Broadcast day (YYYY-MM-DD). Default: today."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show individual segment details"),
    traffic_preview: bool = typer.Option(False, "--traffic-preview", help="Show break fill preview for filler segments"),
):
    """Inspect a compiled channel schedule in human-readable form.

    Shows blocks, their compiled segments, durations, and structure
    without requiring you to parse raw JSON.

    With --traffic-preview, filler segments show what traffic profile
    will fill them and how many ad slots are estimated.
    """
    plan, resolver, dsl = _load_and_compile(yaml_path, broadcast_day)

    typer.echo(f"Channel:       {plan.get('channel_id', '?')}")
    typer.echo(f"Broadcast day: {plan.get('broadcast_day', '?')}")
    typer.echo(f"Timezone:      {plan.get('timezone', '?')}")
    typer.echo(f"Blocks:        {len(plan.get('program_blocks', []))}")
    typer.echo(f"Hash:          {plan.get('hash', '?')}")
    typer.echo()

    blocks = plan.get("program_blocks", [])
    for i, block in enumerate(blocks):
        cs = block.get("compiled_segments", [])
        slot_ms = block["slot_duration_sec"] * 1000
        ep_ms = block["episode_duration_sec"] * 1000

        content_ms = sum(s["duration_ms"] for s in cs if s.get("segment_type") == "content")
        filler_ms = sum(s["duration_ms"] for s in cs if s.get("segment_type") == "filler")
        pres_ms = sum(s["duration_ms"] for s in cs if s.get("segment_type") == "presentation")
        other_ms = sum(s["duration_ms"] for s in cs if s.get("segment_type") not in ("content", "filler", "presentation"))
        seg_total = sum(s["duration_ms"] for s in cs)

        content_count = sum(1 for s in cs if s.get("segment_type") == "content")
        filler_count = sum(1 for s in cs if s.get("segment_type") == "filler")

        typer.echo(f"  [{i:3d}] {_fmt_time(block['start_at'])}  {block['title']}")
        typer.echo(f"        slot={_fmt_ms(slot_ms)}  content={_fmt_ms(content_ms)} ({content_count} acts)  "
                   f"filler={_fmt_ms(filler_ms)} ({filler_count} breaks)  pres={_fmt_ms(pres_ms)}")

        conservation = "OK" if seg_total == slot_ms else f"VIOLATION delta={seg_total - slot_ms}ms"
        typer.echo(f"        segments={len(cs)}  sum={_fmt_ms(seg_total)}  conservation={conservation}")

        if verbose or traffic_preview:
            # Resolve traffic profile once per block (for traffic preview)
            block_profile = _resolve_traffic_profile(dsl, block) if traffic_preview else None

            for j, seg in enumerate(cs):
                seg_type = seg.get("segment_type", "?")
                dur = seg.get("duration_ms", 0)
                offset = seg.get("asset_start_offset_ms", 0)
                asset_id = seg.get("asset_id", "")
                label = _asset_label(asset_id, resolver)
                primary = " [PRIMARY]" if seg.get("is_primary") else ""
                tr_out = seg.get("transition_out", "")
                tr_label = " ~fade~" if tr_out == "TRANSITION_FADE" else ""

                if seg_type == "filler" and traffic_preview:
                    # Traffic preview: show break structure with sample assets
                    typer.echo(f"          {j:2d}. [{'break':12s}] {_fmt_ms(dur)}")
                    if block_profile:
                        profile_name = block_profile.get("_name", "?")
                        pools = block_profile.get("allowed_pools",
                                block_profile.get("allowed_types", []))
                        pools_str = ", ".join(pools) if pools else "(none)"
                        typer.echo(f"              -> profile: {profile_name}  pools: {pools_str}")

                        # Show actual assets that would fill this break
                        channel_slug = plan.get("channel_id", "")
                        packed = _preview_break_fill(dur, channel_slug)
                        if packed:
                            filled_ms = 0
                            for k, spot in enumerate(packed):
                                typer.echo(f"              -> [{k+1}] {spot['filename']}  "
                                           f"{_fmt_ms(spot['duration_ms'])}  ({spot['type']})")
                                filled_ms += spot["duration_ms"]
                            gap = dur - filled_ms
                            if gap > 0:
                                typer.echo(f"              -> [{len(packed)+1}] (pad) {_fmt_ms(gap)}")
                        else:
                            typer.echo(f"              -> (no traffic assets available — would use filler.mp4)")
                    else:
                        typer.echo(f"              -> no traffic profile")
                elif seg_type == "filler":
                    typer.echo(f"          {j:2d}. [{seg_type:12s}] {_fmt_ms(dur)}")
                else:
                    typer.echo(f"          {j:2d}. [{seg_type:12s}] {_fmt_ms(dur)}  offset={_fmt_ms(offset)}  "
                               f"{label}{primary}{tr_label}")

        if other_ms > 0:
            typer.echo(f"        other={_fmt_ms(other_ms)}")
        typer.echo()

    # Summary
    total_content = sum(
        s["duration_ms"]
        for b in blocks for s in b.get("compiled_segments", [])
        if s.get("segment_type") == "content"
    )
    total_filler = sum(
        s["duration_ms"]
        for b in blocks for s in b.get("compiled_segments", [])
        if s.get("segment_type") == "filler"
    )
    total_slot = sum(b["slot_duration_sec"] * 1000 for b in blocks)
    typer.echo(f"  Total: {len(blocks)} blocks  slot={_fmt_ms(total_slot)}  "
               f"content={_fmt_ms(total_content)}  filler={_fmt_ms(total_filler)}")


@app.command("simulate")
def simulate_cmd(
    yaml_path: str = typer.Argument(..., help="Path to channel YAML file"),
    time: str = typer.Option(None, "--time", "-t", help="ISO datetime to simulate. Default: now."),
    broadcast_day: str = typer.Option(None, "--day", help="Broadcast day (YYYY-MM-DD). Default: today."),
):
    """Simulate what is playing at a given time.

    Compiles the schedule and determines which segment would be airing
    at the specified time, including the offset into the content.
    """
    plan, resolver, _dsl = _load_and_compile(yaml_path, broadcast_day)

    # Parse target time
    if time:
        try:
            target = datetime.fromisoformat(time)
        except ValueError:
            typer.echo(f"Error: Invalid time format: {time}", err=True)
            typer.echo("Expected ISO 8601, e.g.: 2026-04-01T20:30:00", err=True)
            raise typer.Exit(1)
    else:
        target = datetime.now(timezone.utc)

    if target.tzinfo is None:
        tz_name = plan.get("timezone", "UTC")
        from zoneinfo import ZoneInfo
        target = target.replace(tzinfo=ZoneInfo(tz_name))

    target_utc_ms = int(target.timestamp() * 1000)

    # Find the block covering this time
    blocks = plan.get("program_blocks", [])
    active_block = None
    active_idx = None
    for i, block in enumerate(blocks):
        start_ms = int(datetime.fromisoformat(block["start_at"]).timestamp() * 1000)
        end_ms = start_ms + block["slot_duration_sec"] * 1000
        if start_ms <= target_utc_ms < end_ms:
            active_block = block
            active_idx = i
            break

    if active_block is None:
        typer.echo(f"No block covers {target.isoformat()}")
        typer.echo(f"Schedule has {len(blocks)} blocks:")
        if blocks:
            typer.echo(f"  First: {blocks[0]['start_at']}")
            last = blocks[-1]
            last_end_ms = int(datetime.fromisoformat(last["start_at"]).timestamp() * 1000) + last["slot_duration_sec"] * 1000
            last_end = datetime.fromtimestamp(last_end_ms / 1000, tz=timezone.utc)
            typer.echo(f"  Last ends: {last_end.isoformat()}")
        raise typer.Exit(1)

    block_start_ms = int(datetime.fromisoformat(active_block["start_at"]).timestamp() * 1000)
    offset_into_block_ms = target_utc_ms - block_start_ms

    typer.echo(f"Time:    {target.isoformat()}")
    typer.echo(f"Block:   [{active_idx}] {active_block['title']}")
    typer.echo(f"         starts {_fmt_time(active_block['start_at'])}  slot={_fmt_ms(active_block['slot_duration_sec'] * 1000)}")
    typer.echo(f"         offset into block: {_fmt_ms(offset_into_block_ms)}")
    typer.echo()

    # Walk segments to find what's playing
    cs = active_block.get("compiled_segments", [])
    cursor_ms = 0
    active_seg = None
    active_seg_idx = None
    offset_into_seg = 0

    for j, seg in enumerate(cs):
        dur = seg.get("duration_ms", 0)
        if cursor_ms + dur > offset_into_block_ms:
            active_seg = seg
            active_seg_idx = j
            offset_into_seg = offset_into_block_ms - cursor_ms
            break
        cursor_ms += dur

    if active_seg is None:
        typer.echo("  (past end of segments)")
        raise typer.Exit(0)

    seg_type = active_seg.get("segment_type", "?")
    seg_dur = active_seg.get("duration_ms", 0)
    remaining = seg_dur - offset_into_seg

    typer.echo(f"  NOW PLAYING:")
    typer.echo(f"    segment [{active_seg_idx}] {seg_type}")
    if active_seg.get("asset_id"):
        typer.echo(f"    asset:    {_asset_label(active_seg['asset_id'], resolver)}")
    typer.echo(f"    duration: {_fmt_ms(seg_dur)}")
    typer.echo(f"    offset:   {_fmt_ms(offset_into_seg)} into segment")
    if seg_type == "content":
        asset_offset = active_seg.get("asset_start_offset_ms", 0) + offset_into_seg
        typer.echo(f"    playhead: {_fmt_ms(asset_offset)} into source asset")
    typer.echo(f"    remaining: {_fmt_ms(remaining)}")

    # Next segment
    if active_seg_idx + 1 < len(cs):
        next_seg = cs[active_seg_idx + 1]
        typer.echo()
        typer.echo(f"  UP NEXT:")
        typer.echo(f"    segment [{active_seg_idx + 1}] {next_seg.get('segment_type', '?')}")
        if next_seg.get("asset_id"):
            typer.echo(f"    asset:    {_asset_label(next_seg['asset_id'], resolver)}")
        typer.echo(f"    duration: {_fmt_ms(next_seg.get('duration_ms', 0))}")
        typer.echo(f"    starts in: {_fmt_ms(remaining)}")
    elif active_idx + 1 < len(blocks):
        next_block = blocks[active_idx + 1]
        typer.echo()
        typer.echo(f"  NEXT BLOCK:")
        typer.echo(f"    [{active_idx + 1}] {next_block['title']}")
        typer.echo(f"    starts {_fmt_time(next_block['start_at'])}")
