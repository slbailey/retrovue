"""
Schedule listing, rescheduling, rebuild, and introspection CLI commands.

Provides `list`, `reschedule`, `rebuild`, `explain`, and `preview` subcommands
for inspecting and mutating Tier 1 (ScheduleRevision) and Tier 2 (PlaylistEvent)
schedule blocks.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import typer


def _ms_to_local(utc_ms: int) -> str:
    """Convert UTC milliseconds to local-timezone datetime string."""
    dt = datetime.fromtimestamp(utc_ms / 1000, tz=timezone.utc).astimezone()
    return dt.strftime("%Y-%m-%d %H:%M %Z")


def _iso_to_local(iso_str: str | None) -> str:
    """Convert an ISO-8601 UTC datetime string to local-timezone display."""
    if not iso_str:
        return "N/A"
    dt = datetime.fromisoformat(iso_str).astimezone()
    return dt.strftime("%Y-%m-%d %H:%M %Z")

app = typer.Typer(name="schedule", help="Schedule listing and rescheduling operations")


def _load_filler_config(channel_slug: str) -> tuple[str, int]:
    """Load filler_uri and filler_duration_ms from channel YAML config.

    Returns defaults if the config cannot be loaded.
    Same source as PlaylistBuilderDaemon (INV-PLAYLOG-PREFILL-001).
    """
    filler_uri = "/opt/retrovue/assets/filler.mp4"
    filler_duration_ms = 3_650_000
    try:
        from pathlib import Path
        from retrovue.runtime.providers import YamlChannelConfigProvider

        yaml_dir = Path("/opt/retrovue/config/channels")
        cfg = None
        if yaml_dir.is_dir():
            cfg = YamlChannelConfigProvider(yaml_dir).get_channel_config(channel_slug)
        if cfg is not None:
            sc = cfg.schedule_config or {}
            filler_uri = sc.get("filler_path", filler_uri)
            filler_duration_ms = sc.get("filler_duration_ms", filler_duration_ms)
    except Exception:
        pass  # fall through to defaults
    return filler_uri, filler_duration_ms


def _load_channel_dsl(channel_slug: str) -> dict | None:
    """Load the raw parsed YAML dict for a channel.

    Returns None if the YAML cannot be loaded. Used by rebuild to resolve
    break_config and traffic policy (INV-TIER2-EXPANSION-CANONICAL-001).
    """
    try:
        from pathlib import Path

        import yaml

        yaml_dir = Path("/opt/retrovue/config/channels")
        yaml_file = yaml_dir / f"{channel_slug}.yaml"
        if yaml_file.is_file():
            with open(yaml_file) as f:
                return yaml.safe_load(f)
    except Exception:
        pass
    return None


@app.command("list")
def list_cmd(
    channel_id: str = typer.Option(None, "--channel", "-c", help="Filter by channel ID"),
    tier: str = typer.Option(None, "--tier", "-t", help="Filter by tier (1 or 2)"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
) -> None:
    """List Tier 1 and Tier 2 blocks eligible for rescheduling (future blocks only)."""
    from datetime import datetime, timezone

    from retrovue.infra.uow import session
    from retrovue.usecases.schedule_reschedule import list_reschedulable

    now = datetime.now(timezone.utc)

    try:
        with session() as db:
            result = list_reschedulable(db, now=now, channel_id=channel_id, tier=tier)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    if json_output:
        typer.echo(json.dumps(result, indent=2, default=str))
        return

    tier1 = result.get("tier1", [])
    tier2 = result.get("tier2", [])

    if not tier1 and not tier2:
        typer.echo("No reschedulable blocks found.")
        return

    if tier1:
        typer.echo("=== Tier 1 (ScheduleRevision) ===")
        typer.echo(
            f"{'UUID':<38} {'CHANNEL':<20} {'BROADCAST_DAY':<14} "
            f"{'START':<24} {'END':<24}"
        )
        for row in tier1:
            typer.echo(
                f"{row['id']:<38} {row['channel_id']:<20} {row['broadcast_day']:<14} "
                f"{_iso_to_local(row['range_start']):<24} "
                f"{_iso_to_local(row['range_end']):<24}"
            )
        typer.echo(f"\n{len(tier1)} Tier 1 row(s)")

    if tier1 and tier2:
        typer.echo("")

    if tier2:
        typer.echo("=== Tier 2 (PlaylistEvent) ===")
        typer.echo(
            f"{'BLOCK_ID':<44} {'CHANNEL':<20} {'BROADCAST_DAY':<14} "
            f"{'START':<24} {'END':<24}"
        )
        for row in tier2:
            typer.echo(
                f"{row['block_id']:<44} {row['channel_slug']:<20} "
                f"{row['broadcast_day']:<14} "
                f"{_ms_to_local(row['start_utc_ms']):<24} "
                f"{_ms_to_local(row['end_utc_ms']):<24}"
            )
        typer.echo(f"\n{len(tier2)} Tier 2 row(s)")


@app.command("reschedule")
def reschedule_cmd(
    identifier: str = typer.Argument(
        ..., help="Revision UUID (Tier 1) or block_id (Tier 2) to reschedule"
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Skip confirmation prompt"
    ),
) -> None:
    """Reschedule a block by its identifier. Deletes it for regeneration on next access."""
    from datetime import datetime, timezone

    from retrovue.infra.uow import session
    from retrovue.usecases.schedule_reschedule import (
        RescheduleRejectedError,
        reschedule_by_id,
    )

    now = datetime.now(timezone.utc)

    if not force:
        confirm = typer.confirm(
            f"Reschedule block {identifier}? This will delete it for regeneration."
        )
        if not confirm:
            typer.echo("Cancelled.")
            raise typer.Exit(0)

    try:
        with session() as db:
            result = reschedule_by_id(db, identifier=identifier, now=now)
    except RescheduleRejectedError as e:
        typer.echo(f"Rejected: {e}", err=True)
        raise typer.Exit(1)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    typer.echo(f"Rescheduled Tier {result['tier']} block.")
    typer.echo(f"  Tier 1 rows deleted: {result['deleted_tier1']}")
    typer.echo(f"  Tier 2 rows deleted: {result['deleted_tier2']}")
    typer.echo("Block(s) will regenerate on next daemon cycle (~30s) or viewer tune-in.")


def _parse_time_arg(value: str) -> datetime:
    """Parse 'now' or an ISO-8601 timestamp into a UTC datetime."""
    if value.lower() == "now":
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        raise typer.BadParameter(f"Invalid timestamp: {value!r}. Use 'now' or ISO-8601.")


@app.command("rebuild")
def rebuild_cmd(
    channel: str = typer.Option(..., "--channel", "-c", help="Channel slug"),
    tier: int = typer.Option(..., "--tier", "-t", help="Tier to rebuild (1 or 2)"),
    from_time: str = typer.Option("now", "--from", help="Start time: 'now' or ISO-8601 timestamp"),
    to_time: str = typer.Option("horizon", "--to", help="End time: 'horizon' or ISO-8601 timestamp"),
    live_safe: bool = typer.Option(False, "--live-safe", help="Skip the currently playing block"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without writing"),
) -> None:
    """Rebuild scheduling tiers for a channel without restarting daemons."""
    if tier not in (1, 2):
        typer.echo("Error: --tier must be 1 or 2", err=True)
        raise typer.Exit(1)

    if tier == 1:
        typer.echo("Error: Tier-1 rebuild is not yet implemented. Use 'retrovue programming rebuild' to supersede revisions.", err=True)
        raise typer.Exit(1)

    # Resolve start time
    start_dt = _parse_time_arg(from_time)
    start_utc_ms = int(start_dt.timestamp() * 1000)

    # Resolve end time
    if to_time.lower() == "horizon":
        # Default Tier-2 horizon: 3 hours from start
        end_dt = start_dt + timedelta(hours=3)
    else:
        end_dt = _parse_time_arg(to_time)
    end_utc_ms = int(end_dt.timestamp() * 1000)

    if end_utc_ms <= start_utc_ms:
        typer.echo("Error: --to must be after --from", err=True)
        raise typer.Exit(1)

    from retrovue.infra.uow import session
    from retrovue.usecases.schedule_rebuild import rebuild_tier2

    if dry_run:
        typer.echo(f"DRY RUN: Tier-2 rebuild for {channel}")
    else:
        typer.echo(f"Rebuilding Tier-2 for {channel}")

    typer.echo(f"  Window: {start_dt.isoformat()} -> {end_dt.isoformat()}")
    if live_safe:
        typer.echo("  Live-safe: enabled (will skip currently playing block)")

    filler_uri, filler_duration_ms = _load_filler_config(channel)
    channel_dsl = _load_channel_dsl(channel)

    try:
        with session() as db:
            result = rebuild_tier2(
                db,
                channel_slug=channel,
                start_utc_ms=start_utc_ms,
                end_utc_ms=end_utc_ms,
                filler_uri=filler_uri,
                filler_duration_ms=filler_duration_ms,
                live_safe=live_safe,
                dry_run=dry_run,
                channel_dsl=channel_dsl,
            )
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    if dry_run:
        typer.echo(f"  Would delete: {result.deleted} Tier-2 block(s)")
        typer.echo("  No changes written.")
        return

    typer.echo(f"  Deleted: {result.deleted} Tier-2 block(s)")
    typer.echo(f"  Rebuilt: {result.rebuilt} Tier-2 block(s)")
    if result.live_safe_skipped:
        typer.echo("  Live-safe: start shifted past currently playing block")
    if result.errors:
        typer.echo(f"  Errors: {len(result.errors)}", err=True)
        for err in result.errors:
            typer.echo(f"    - {err}", err=True)


@app.command("explain")
def explain_cmd(
    channel: str = typer.Option(..., "--channel", "-c", help="Channel slug"),
    time_str: str = typer.Option(..., "--time", help="Time to explain: 'now' or ISO-8601 timestamp"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
) -> None:
    """Explain why a particular program is airing at a given time."""
    at = _parse_time_arg(time_str)

    from retrovue.infra.uow import session
    from retrovue.usecases.schedule_explain import explain_at

    try:
        with session() as db:
            result = explain_at(db, channel_slug=channel, at=at)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    if "error" in result:
        typer.echo(f"Error: {result['error']}", err=True)
        raise typer.Exit(1)

    if json_output:
        typer.echo(json.dumps(result, indent=2, default=str))
        return

    # Human-readable output
    typer.echo(f"=== Schedule Explain: {channel} at {at.isoformat()} ===\n")

    t1 = result["tier1"]
    typer.echo("Tier 1 (ScheduleRevision)")
    typer.echo(f"  Revision ID:    {t1['revision_id']}")
    typer.echo(f"  Broadcast day:  {t1['broadcast_day']}")
    typer.echo(f"  Status:         {t1['revision_status']}")
    typer.echo(f"  Created by:     {t1['revision_created_by']}")

    si = result["schedule_item"]
    typer.echo(f"\nScheduleItem (slot {si['slot_index']})")
    typer.echo(f"  Title:          {si.get('title', 'N/A')}")
    typer.echo(f"  Template:       {si.get('template_id') or '(none — legacy block)'}")
    typer.echo(f"  Content type:   {si['content_type']}")
    typer.echo(f"  Slot:           {_iso_to_local(si['slot_start'])} -> {_iso_to_local(si['slot_end'])}")
    typer.echo(f"  Duration:       {si['duration_sec']}s")
    typer.echo(f"  Asset ID:       {si.get('asset_id', 'N/A')}")

    typer.echo(f"\nExpansion path:   {result['expansion_path']}")

    if "compiled_segments" in result:
        segs = result["compiled_segments"]
        typer.echo(f"\nCompiled segments ({len(segs)}):")
        for i, seg in enumerate(segs):
            primary = " [PRIMARY]" if seg.get("is_primary") else ""
            typer.echo(
                f"  {i}: [{seg['segment_type']}] {seg.get('asset_id', '?')}"
                f"  dur={seg.get('segment_duration_ms') or seg.get('duration_ms', '?')}ms"
                f"  source={seg.get('source_type', '?')}:{seg.get('source_name', '?')}"
                f"{primary}"
            )
    elif "legacy_info" in result:
        li = result["legacy_info"]
        typer.echo(f"\nLegacy expansion info:")
        typer.echo(f"  Asset ID (raw): {li.get('asset_id_raw', 'N/A')}")
        typer.echo(f"  Episode dur:    {li.get('episode_duration_sec', 'N/A')}s")
        if li.get("selector"):
            typer.echo(f"  Selector:       {json.dumps(li['selector'])}")
        typer.echo(f"  Note:           {li.get('note', '')}")


@app.command("preview")
def preview_cmd(
    channel: str = typer.Option(..., "--channel", "-c", help="Channel slug"),
    time_str: str = typer.Option(..., "--time", help="Time to preview: 'now' or ISO-8601 timestamp"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
) -> None:
    """Preview the Tier-2 playout segments for the block at a given time."""
    at = _parse_time_arg(time_str)

    from retrovue.infra.uow import session
    from retrovue.usecases.schedule_preview import preview_at

    try:
        with session() as db:
            result = preview_at(
                db,
                channel_slug=channel,
                at=at,
            )
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    if "error" in result:
        typer.echo(f"Error: {result['error']}", err=True)
        raise typer.Exit(1)

    if json_output:
        typer.echo(json.dumps(result, indent=2, default=str))
        return

    # Human-readable output
    typer.echo(f"=== Segment Preview: {channel} at {at.isoformat()} ===\n")
    typer.echo(f"Block:    {result['block_id']}")
    typer.echo(f"Start:    {_iso_to_local(result['block_start'])}")
    typer.echo(f"End:      {_iso_to_local(result['block_end'])}")
    typer.echo(f"Duration: {result['block_duration_ms']}ms")
    typer.echo(f"Segments: {result['segment_count']}\n")

    typer.echo(
        f"{'IDX':<5} {'TYPE':<12} {'START':<26} {'DURATION':<12} {'ASSET'}"
    )
    typer.echo("-" * 90)
    for seg in result["segments"]:
        typer.echo(
            f"{seg['index']:<5} {seg['segment_type']:<12} "
            f"{_iso_to_local(seg['start_time']):<26} "
            f"{seg['duration_display']:<12} {seg['asset_uri']}"
        )
