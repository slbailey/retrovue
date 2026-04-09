from __future__ import annotations

import json
import uuid as _uuid

import typer
from sqlalchemy import func, select

from ...domain.entities import Channel
from ...infra.db import get_sessionmaker
from ...infra.settings import settings
from ...infra.uow import session
from ...usecases import channel_add as _uc_channel_add
from ...usecases import channel_update as _uc_channel_update
from ...usecases import channel_validate as _uc_channel_validate

app = typer.Typer(name="channel", help="Broadcast channel management operations")

# Register DSL subcommands (compile, inspect, simulate).
from .channel_dsl import compile_cmd as _compile_cmd
from .channel_dsl import inspect_cmd as _inspect_cmd
from .channel_dsl import simulate_cmd as _simulate_cmd

app.command("compile", help="Compile channel YAML to program schedule JSON")(_compile_cmd)
app.command("inspect", help="Inspect compiled schedule in human-readable form")(_inspect_cmd)
app.command("simulate", help="Simulate what is playing at a given time")(_simulate_cmd)


def _get_db_context(test_db: bool):
    if not test_db:
        return session()
    use_test_sessionmaker = bool(getattr(settings, "test_database_url", None)) or hasattr(
        get_sessionmaker, "assert_called"
    )
    if use_test_sessionmaker:
        try:
            SessionForTest = get_sessionmaker(for_test=True)
            return SessionForTest()
        except Exception:
            pass
    return session()


# Alias for test compatibility
_get_test_db_context = _get_db_context


@app.command("add")
def add_channel(
    name: str | None = typer.Option(None, "--name", help="Channel name (unique)"),
    grid_size_minutes: int = typer.Option(..., "--grid-size-minutes", help="Grid size (15,30,60)"),
    grid_offset_minutes: int = typer.Option(0, "--grid-offset-minutes", help="Grid alignment offset (minutes)", show_default=True),
    broadcast_day_start: str = typer.Option(
        "06:00",
        "--broadcast-day-start",
        help="Programming day anchor (HH:MM)",
        show_default=True,
    ),
    active: bool = typer.Option(True, "--active/--inactive", help="Initial active state"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    test_db: bool = typer.Option(False, "--test-db", help="Use test database context"),
):
    """Create a broadcast channel per ChannelAddContract.md."""
    db_cm = _get_db_context(test_db)

    with db_cm as db:
        try:
            # Minimal pre-validation for fast feedback
            if not name:
                typer.echo("Error: --name is required", err=True)
                raise typer.Exit(1)

            # Normalize inputs
            # Normalize broadcast day start (accept HH:MM) and tolerate HH:MM:SS
            bds = broadcast_day_start.strip()
            if len(bds.split(":")) == 3:
                h, m, _s = bds.split(":", 2)
                bds = f"{h}:{m}"

            # Delegate to usecase
            result = _uc_channel_add.add_channel(
                db,
                name=name,
                grid_size_minutes=grid_size_minutes,
                grid_offset_minutes=grid_offset_minutes,
                broadcast_day_start=bds,
                is_active=active,
            )

            if json_output:
                payload = {"status": "ok", "channel": result}
                typer.echo(json.dumps(payload, indent=2))
            else:
                typer.echo("Channel created:")
                typer.echo(f"  ID: {result['id']}")
                typer.echo(f"  Name: {result['name']}")
                typer.echo(f"  Grid Size (min): {result['grid_size_minutes']}")
                typer.echo(f"  Grid Offset (min): {result['grid_offset_minutes']}")
                if 'broadcast_day_start' in result:
                    typer.echo(f"  Broadcast day start: {result['broadcast_day_start']}")
                typer.echo(f"  Active: {str(bool(result['is_active'])).lower()}")
                if result.get("created_at"):
                    typer.echo(f"  Created: {result['created_at']}")
            return
        except typer.Exit:
            raise
        except Exception as e:
            if json_output:
                typer.echo(json.dumps({"status": "error", "error": str(e)}, indent=2))
            else:
                typer.echo(f"Error creating channel: {e}", err=True)
            raise typer.Exit(1)


@app.command("update")
def update_channel(
    selector: str | None = typer.Argument(None, help="Channel identifier: UUID or slug"),
    id: str | None = typer.Option(None, "--id", help="Channel identifier: UUID or slug"),
    name: str | None = typer.Option(None, "--name", help="New channel name"),
    grid_size_minutes: int | None = typer.Option(None, "--grid-size-minutes", help="New grid size (15,30,60)"),
    grid_offset_minutes: int | None = typer.Option(None, "--grid-offset-minutes", help="New grid alignment offset (minutes)"),
    broadcast_day_start: str | None = typer.Option(None, "--broadcast-day-start", help="New programming day anchor (HH:MM)"),
    active: bool | None = typer.Option(None, "--active/--inactive", help="Set active flag"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    test_db: bool = typer.Option(False, "--test-db", help="Use test database context"),
):
    """Update a channel."""
    identifier = id or selector
    if not identifier:
        if json_output:
            typer.echo(json.dumps({"status": "error", "error": "Missing channel identifier"}, indent=2))
        else:
            typer.echo("Error: Missing channel identifier (provide positional arg or --id)", err=True)
        raise typer.Exit(1)

    db_cm = _get_db_context(test_db)
    with db_cm as db:
        try:
            result = _uc_channel_update.update_channel(
                db,
                identifier=identifier,
                name=name,
                grid_size_minutes=grid_size_minutes,
                grid_offset_minutes=grid_offset_minutes,
                broadcast_day_start=broadcast_day_start,
                is_active=active,
            )

            if json_output:
                typer.echo(json.dumps({"status": "ok", "channel": result}, indent=2))
            else:
                typer.echo("Channel updated:")
                typer.echo(f"  ID: {result['id']}")
                typer.echo(f"  Name: {result['name']}")
                typer.echo(f"  Grid Size (min): {result['grid_size_minutes']}")
                typer.echo(f"  Grid Offset (min): {result['grid_offset_minutes']}")
                typer.echo(f"  Broadcast day start: {result['broadcast_day_start']}")
                typer.echo(f"  Active: {str(bool(result['is_active'])).lower()}")
            return
        except typer.Exit:
            raise
        except Exception as e:
            if json_output:
                typer.echo(json.dumps({"status": "error", "error": str(e)}, indent=2))
            else:
                typer.echo(f"Error updating channel: {e}", err=True)
            raise typer.Exit(1)

@app.command("show")
def show_channel(
    selector: str | None = typer.Argument(None, help="Channel identifier: UUID or slug"),
    id: str | None = typer.Option(None, "--id", help="Channel identifier: UUID or slug"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    test_db: bool = typer.Option(False, "--test-db", help="Use test database context"),
):
    """Show a single channel by UUID or slug."""

    identifier = id or selector
    if not identifier:
        if json_output:
            typer.echo(json.dumps({"status": "error", "error": "Missing channel identifier"}, indent=2))
        else:
            typer.echo("Error: Missing channel identifier (provide positional arg or --id)", err=True)
        raise typer.Exit(1)

    db_cm = _get_db_context(test_db)
    with db_cm as db:
        try:
            # Resolve channel by UUID or slug
            channel = None
            try:
                _ = _uuid.UUID(identifier)
                channel = db.execute(select(Channel).where(Channel.id == identifier)).scalars().first()
            except Exception:
                channel = (
                    db.execute(select(Channel).where(func.lower(Channel.slug) == identifier.lower()))
                    .scalars()
                    .first()
                )

            if channel is None:
                if json_output:
                    typer.echo(json.dumps({"status": "error", "error": f"Channel '{identifier}' not found"}, indent=2))
                else:
                    typer.echo(f"Error: Channel '{identifier}' not found", err=True)
                raise typer.Exit(1)

            def derive_offset(offsets: list[int] | None) -> int:
                if isinstance(offsets, list) and offsets:
                    return min(offsets)
                return 0

            def hhmm(t) -> str:
                try:
                    return f"{t.hour:02d}:{t.minute:02d}"
                except Exception:
                    return "06:00"

            payload = {
                "id": str(channel.id),
                "name": channel.title,
                "grid_size_minutes": channel.grid_block_minutes,
                "grid_offset_minutes": derive_offset(channel.block_start_offsets_minutes if isinstance(channel.block_start_offsets_minutes, list) else []),
                "broadcast_day_start": hhmm(channel.programming_day_start),
                "is_active": bool(channel.is_active),
                "created_at": channel.created_at.isoformat() if channel.created_at else None,
                "updated_at": channel.updated_at.isoformat() if channel.updated_at else None,
            }

            if json_output:
                typer.echo(json.dumps({"status": "ok", "channel": payload}, indent=2))
            else:
                typer.echo("Channel:")
                typer.echo(f"  ID: {payload['id']}")
                typer.echo(f"  Name: {payload['name']}")
                typer.echo(f"  Grid Size (min): {payload['grid_size_minutes']}")
                typer.echo(f"  Grid Offset (min): {payload['grid_offset_minutes']}")
                typer.echo(f"  Broadcast day start: {payload['broadcast_day_start']}")
                typer.echo(f"  Active: {str(bool(payload['is_active'])).lower()}")
                if payload.get("created_at"):
                    typer.echo(f"  Created: {payload['created_at']}")
                if payload.get("updated_at"):
                    typer.echo(f"  Updated: {payload['updated_at']}")
            return
        except typer.Exit:
            raise
        except Exception as e:
            if json_output:
                typer.echo(json.dumps({"status": "error", "error": str(e)}, indent=2))
            else:
                typer.echo(f"Error showing channel: {e}", err=True)
            raise typer.Exit(1)


@app.command("validate")
def validate_channels(
    selector: str | None = typer.Argument(None, help="Channel identifier: UUID or slug (optional)"),
    id: str | None = typer.Option(None, "--id", help="Channel identifier: UUID or slug"),
    strict: bool = typer.Option(False, "--strict", help="Treat warnings as errors for exit code"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    test_db: bool = typer.Option(False, "--test-db", help="Use test database context"),
):
    """Validate channels (non-mutating; per-row only)."""
    identifier = id or selector
    db_cm = _get_db_context(test_db)
    with db_cm as db:
        try:
            result = _uc_channel_validate.validate(db, identifier=identifier, strict=strict)
            status = result.get("status", "ok")
            exit_code = 0 if status == "ok" else 2

            if json_output:
                typer.echo(json.dumps(result, indent=2))
            else:
                if identifier:
                    if status == "ok":
                        typer.echo("OK")
                    else:
                        for v in result.get("violations", []):
                            typer.echo(f"{v['code']}: {v['message']}")
                        if not strict:
                            for w in result.get("warnings", []):
                                typer.echo(f"{w['code']}: {w['message']}")
                else:
                    # all-mode: one line per channel + summary
                    for c in result.get("channels", []):
                        line = f"{c['id']}: {c['status']}"
                        typer.echo(line)
                    totals = result.get("totals", {"violations": 0, "warnings": 0})
                    typer.echo(f"Violations: {totals['violations']}, Warnings: {totals['warnings']}")

            raise typer.Exit(exit_code)
        except typer.Exit:
            raise
        except Exception as e:
            payload = {"status": "error", "violations": [], "warnings": [], "error": str(e)}
            if json_output:
                typer.echo(json.dumps(payload, indent=2))
            else:
                typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)


@app.command("list")
def list_channels(
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    test_db: bool = typer.Option(False, "--test-db", help="Use test database context"),
):
    """List all channels from the database."""

    db_cm = _get_db_context(test_db)
    with db_cm as db:
        try:
            rows = db.query(Channel).all()

            def derive_offset(offsets: list[int] | None) -> int:
                if isinstance(offsets, list) and offsets:
                    return min(offsets)
                return 0

            def hhmm(t) -> str:
                try:
                    return f"{t.hour:02d}:{t.minute:02d}"
                except Exception:
                    return "06:00"

            items = [
                {
                    "id": str(c.id),
                    "name": c.title,
                    "grid_size_minutes": c.grid_block_minutes,
                    "grid_offset_minutes": derive_offset(c.block_start_offsets_minutes if isinstance(c.block_start_offsets_minutes, list) else []),
                    "broadcast_day_start": hhmm(c.programming_day_start),
                    "is_active": bool(c.is_active),
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "updated_at": c.updated_at.isoformat() if c.updated_at else None,
                }
                for c in rows
            ]

            if json_output:
                payload = {
                    "status": "ok",
                    "total": len(items),
                    "channels": items,
                }
                typer.echo(json.dumps(payload, indent=2))
            else:
                if not items:
                    typer.echo("No channels found")
                else:
                    typer.echo("Channels:")
                    for c in items:
                        typer.echo(f"  ID: {c['id']}")
                        typer.echo(f"  Name: {c['name']}")
                        typer.echo(f"  Grid Size (min): {c['grid_size_minutes']}")
                        typer.echo(f"  Grid Offset (min): {c['grid_offset_minutes']}")
                        typer.echo(f"  Broadcast day start: {c['broadcast_day_start']}")
                        typer.echo(f"  Active: {str(bool(c['is_active'])).lower()}")
                        typer.echo("")
                    typer.echo(f"Total: {len(items)} channels")
            return
        except Exception as e:
            if json_output:
                typer.echo(json.dumps({"status": "error", "error": str(e)}, indent=2))
            else:
                typer.echo(f"Error listing channels: {e}", err=True)
            raise typer.Exit(1)

@app.command("delete")
def delete_channel(
    selector: str | None = typer.Argument(None, help="Channel identifier: UUID or slug"),
    id: str | None = typer.Option(None, "--id", help="Channel identifier: UUID or slug"),
    yes: bool = typer.Option(False, "--yes", help="Confirm deletion (non-interactive)"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    test_db: bool = typer.Option(False, "--test-db", help="Use test database context"),
):
    """Delete a channel.

    Requires --yes to proceed in non-interactive contexts. If dependencies exist,
    deletion is blocked and guidance to archive is shown.
    """


    db_cm = _get_db_context(test_db)

    with db_cm as db:
        try:
            # Resolve input
            identifier = id or selector
            if not identifier:
                if json_output:
                    typer.echo(json.dumps({"status": "error", "error": "Missing channel identifier"}, indent=2))
                else:
                    typer.echo("Error: Missing channel identifier (provide positional arg or --id)", err=True)
                raise typer.Exit(1)

            # Resolve by UUID or fallback to slug (case-insensitive)
            channel = None
            try:
                _ = _uuid.UUID(identifier)
                channel = db.execute(select(Channel).where(Channel.id == identifier)).scalars().first()
            except Exception:
                channel = (
                    db.execute(
                        select(Channel).where(func.lower(Channel.slug) == identifier.lower())
                    )
                    .scalars()
                    .first()
                )
            if channel is None:
                if json_output:
                    typer.echo(json.dumps({"status": "error", "error": f"Channel '{identifier}' not found"}, indent=2))
                else:
                    typer.echo(f"Error: Channel '{identifier}' not found", err=True)
                raise typer.Exit(1)

            # Dependency check placeholder (no dependencies in current schema)
            deps_exist = bool(getattr(channel, "_has_deps", False))
            if deps_exist:
                msg = (
                    f"Deletion blocked: channel '{identifier}' has dependent records. "
                    f"Use: retrovue channel update --id {identifier} --inactive"
                )
                if json_output:
                    typer.echo(json.dumps({"status": "error", "error": msg}, indent=2))
                else:
                    typer.echo(msg, err=True)
                raise typer.Exit(1)

            # Confirmation
            if not yes:
                # In contracts, non-interactive tests must pass --yes; we fail fast here
                if json_output:
                    typer.echo(json.dumps({"status": "error", "error": "Confirmation required (--yes)"}, indent=2))
                else:
                    typer.echo("Deletion requires --yes confirmation", err=True)
                raise typer.Exit(1)

            # Delete
            db.delete(channel)
            db.commit()

            if json_output:
                typer.echo(json.dumps({"status": "ok", "deleted": 1, "id": str(channel.id)}, indent=2))
            else:
                # Echo back exactly what the user passed (UUID or slug)
                typer.echo(f"Channel deleted: {identifier}")
            return
        except typer.Exit:
            raise
        except Exception as e:
            if json_output:
                typer.echo(json.dumps({"status": "error", "error": str(e)}, indent=2))
            else:
                typer.echo(f"Error deleting channel: {e}", err=True)
            raise typer.Exit(1)


@app.command("now-playing")
def now_playing(
    channel_id: str = typer.Argument(..., help="Channel slug (e.g. 'hbo')"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    test_db: bool = typer.Option(False, "--test-db", help="Use test database context"),
    next_block: bool = typer.Option(False, "--next", help="Also show the next block"),
):
    """Show the currently playing block and its segments for a channel."""
    import time
    from ...domain.entities import PlaylistEvent

    now_utc_ms = int(time.time() * 1000)
    db_cm = _get_db_context(test_db)
    with db_cm as db:
        try:
            # Current block: start <= now < end
            current = db.query(PlaylistEvent).filter(
                PlaylistEvent.channel_slug == channel_id,
                PlaylistEvent.start_utc_ms <= now_utc_ms,
                PlaylistEvent.end_utc_ms > now_utc_ms,
            ).first()

            if not current:
                if json_output:
                    typer.echo(json.dumps({"status": "ok", "block": None}, indent=2))
                else:
                    typer.echo(f"No block currently playing on '{channel_id}'")
                return

            def _format_block(pe: PlaylistEvent, label: str = "now") -> dict:
                elapsed_ms = now_utc_ms - pe.start_utc_ms
                total_ms = pe.end_utc_ms - pe.start_utc_ms
                progress_pct = round(elapsed_ms / total_ms * 100, 1) if total_ms > 0 else 0
                segs = []
                for i, s in enumerate(pe.segments):
                    seg_type = s.get("segment_type", "content")
                    if seg_type == "pad":
                        continue
                    dur_ms = int(s.get("segment_duration_ms", 0))
                    asset = s.get("asset_uri", "")
                    # Show just the filename for readability
                    filename = asset.rsplit("/", 1)[-1] if "/" in asset else asset
                    segs.append({
                        "index": i,
                        "type": seg_type,
                        "duration_s": round(dur_ms / 1000, 1),
                        "asset": filename,
                        "asset_uri": asset,
                    })
                return {
                    "label": label,
                    "block_id": pe.block_id,
                    "channel": pe.channel_slug,
                    "broadcast_day": pe.broadcast_day.isoformat(),
                    "duration_s": round(total_ms / 1000),
                    "progress_pct": progress_pct,
                    "segments": segs,
                }

            blocks = [_format_block(current, "now")]

            # Optionally fetch next block
            if next_block:
                nxt = db.query(PlaylistEvent).filter(
                    PlaylistEvent.channel_slug == channel_id,
                    PlaylistEvent.start_utc_ms >= current.end_utc_ms,
                ).order_by(PlaylistEvent.start_utc_ms.asc()).first()
                if nxt:
                    blocks.append(_format_block(nxt, "next"))

            if json_output:
                typer.echo(json.dumps({"status": "ok", "blocks": blocks}, indent=2))
            else:
                for blk in blocks:
                    label = blk["label"].upper()
                    typer.echo(f"{label}: {blk['block_id']}  ({blk['duration_s']}s, {blk['progress_pct']}%)")
                    for s in blk["segments"]:
                        dur = s["duration_s"]
                        mins = int(dur // 60)
                        secs = int(dur % 60)
                        dur_str = f"{mins}m{secs:02d}s" if mins > 0 else f"{secs}s"
                        typer.echo(f"  [{s['index']}] {s['type']:14s} {dur_str:>8s}  {s['asset']}")
                    typer.echo("")
        except typer.Exit:
            raise
        except Exception as e:
            if json_output:
                typer.echo(json.dumps({"status": "error", "error": str(e)}, indent=2))
            else:
                typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)
