"""
Schedule listing and rescheduling CLI commands.

Provides `list` and `reschedule` subcommands for inspecting and mutating
Tier 1 (ScheduleRevision) and Tier 2 (PlaylistEvent) schedule blocks.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

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
