from __future__ import annotations

import json
import uuid as _uuid

import typer
from sqlalchemy import func, select

from ...domain.entities import Channel, Program, SchedulePlan, SchedulePlanLabel
from ...infra.db import get_sessionmaker
from ...infra.settings import settings
from ...infra.uow import session
from ...usecases import channel_add as _uc_channel_add
from ...usecases import channel_update as _uc_channel_update
from ...usecases import channel_validate as _uc_channel_validate
from ...usecases import plan_add as _uc_plan_add
from ...usecases import plan_delete as _uc_plan_delete
from ...usecases import plan_list as _uc_plan_list
from ...usecases import plan_show as _uc_plan_show
from ...usecases import plan_update as _uc_plan_update
from ...usecases.plan_show import _resolve_plan as _uc_resolve_plan
from ._ops.planning_session import PlanningSession

app = typer.Typer(name="channel", help="Broadcast channel management operations")


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
    """List all channels (simple view)."""

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


# Plan management subcommands (channel-level only)
# Structure: retrovue channel plan <channel> <command>
plan_mgmt_app = typer.Typer(name="plan", help="Schedule plan management operations")
app.add_typer(plan_mgmt_app)


@plan_mgmt_app.callback(invoke_without_command=True)
def plan_mgmt_callback(
    ctx: typer.Context,
    channel_selector: str = typer.Argument(..., help="Channel identifier: UUID or slug"),
):
    """Schedule plan management for a specific channel."""
    ctx.ensure_object(dict)
    ctx.obj["channel_selector"] = channel_selector
    # If no subcommand was invoked, show help
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


@plan_mgmt_app.command("add")
def add_plan(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Plan name (must be unique within channel)"),
    description: str | None = typer.Option(None, "--description", help="Human-readable description"),
    cron: str | None = typer.Option(None, "--cron", help="Cron expression (hour/min ignored)"),
    start_date: str | None = typer.Option(None, "--start-date", help="Start date (YYYY-MM-DD)"),
    end_date: str | None = typer.Option(None, "--end-date", help="End date (YYYY-MM-DD)"),
    priority: int | None = typer.Option(None, "--priority", help="Priority (higher number = higher priority)"),
    active: bool | None = typer.Option(None, "--active/--inactive", help="Active status (default: active)"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    test_db: bool = typer.Option(False, "--test-db", help="Use test database context"),
):
    """Create a new schedule plan for a channel per SchedulePlanAddContract.md."""
    channel_selector = ctx.obj.get("channel_selector")
    
    if not channel_selector:
        error_msg = "Channel selector required"
        if json_output:
            typer.echo(json.dumps({"status": "error", "code": "CHANNEL_NOT_FOUND", "message": f"Error: {error_msg}"}, indent=2))
        else:
            typer.echo(f"Error: {error_msg}", err=True)
        raise typer.Exit(1)
    
    # Determine is_active (default True unless --inactive is explicitly set)
    is_active = True if active is None else active
    
    db_cm = _get_db_context(test_db)
    
    with db_cm as db:
        try:
            # Delegate to usecase
            result = _uc_plan_add.add_plan(
                db,
                channel_identifier=channel_selector,
                name=name,
                description=description,
                cron_expression=cron,
                start_date=start_date,
                end_date=end_date,
                priority=priority,
                is_active=is_active,
            )
            
            if json_output:
                payload = {"status": "ok", "plan": result}
                typer.echo(json.dumps(payload, indent=2))
            else:
                # Resolve channel for display
                channel = _resolve_channel(db, channel_selector)
                typer.echo("Plan created:")
                typer.echo(f"  ID: {result['id']}")
                typer.echo(f"  Channel: {channel.title} ({result['channel_id']})")
                typer.echo(f"  Name: {result['name']}")
                if result.get("description"):
                    typer.echo(f"  Description: {result['description']}")
                if result.get("cron_expression"):
                    typer.echo(f"  Cron: {result['cron_expression']}")
                if result.get("start_date"):
                    typer.echo(f"  Start Date: {result['start_date']}")
                if result.get("end_date"):
                    typer.echo(f"  End Date: {result['end_date']}")
                typer.echo(f"  Priority: {result['priority']}")
                typer.echo(f"  Active: {result['is_active']}")
                if result.get("created_at"):
                    typer.echo(f"  Created: {result['created_at']}")
            return
        except typer.Exit:
            raise
        except ValueError as e:
            error_msg = str(e)
            # Map error messages to error codes per contract
            error_code = "VALIDATION_ERROR"
            if "Channel" in error_msg and "not found" in error_msg:
                error_code = "CHANNEL_NOT_FOUND"
            elif "already exists" in error_msg:
                error_code = "PLAN_NAME_DUPLICATE"
            elif "Invalid date format" in error_msg:
                error_code = "INVALID_DATE_FORMAT"
            elif "start_date must be <= end_date" in error_msg:
                error_code = "INVALID_DATE_RANGE"
            elif "Invalid cron expression" in error_msg:
                error_code = "INVALID_CRON"
            elif "Priority must be non-negative" in error_msg:
                error_code = "INVALID_PRIORITY"
            
            if json_output:
                typer.echo(json.dumps({"status": "error", "code": error_code, "message": f"Error: {error_msg}"}, indent=2))
            else:
                typer.echo(f"Error: {error_msg}", err=True)
            raise typer.Exit(1)
        except Exception as e:
            error_msg = str(e)
            if json_output:
                typer.echo(json.dumps({"status": "error", "code": "UNKNOWN_ERROR", "message": f"Error: {error_msg}"}, indent=2))
            else:
                typer.echo(f"Error creating plan: {error_msg}", err=True)
            raise typer.Exit(1)


@plan_mgmt_app.command("build")
def build_plan(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Plan name (must be unique within channel)"),
    description: str | None = typer.Option(None, "--description", help="Human-readable description"),
    cron: str | None = typer.Option(None, "--cron", help="Cron expression (hour/min ignored)"),
    start_date: str | None = typer.Option(None, "--start-date", help="Start date (YYYY-MM-DD)"),
    end_date: str | None = typer.Option(None, "--end-date", help="End date (YYYY-MM-DD)"),
    priority: int | None = typer.Option(None, "--priority", help="Priority (higher number = higher priority)"),
    active: bool | None = typer.Option(None, "--active/--inactive", help="Active status (default: active)"),
    test_db: bool = typer.Option(False, "--test-db", help="Use test database context"),
):
    """Create a new schedule plan and enter interactive REPL mode per SchedulePlanBuildContract.md."""
    channel_selector = ctx.obj.get("channel_selector")
    
    if not channel_selector:
        typer.echo("Error: Channel selector required", err=True)
        raise typer.Exit(1)
    
    # Determine is_active (default True unless --inactive is explicitly set)
    is_active = True if active is None else active
    
    db_cm = _get_db_context(test_db)
    
    with db_cm as db:
        try:
            # Use the same validation logic as plan add, but don't commit yet
            # We'll create the plan and enter REPL, committing only on 'save'
            from ...usecases.plan_add import (
                _check_name_uniqueness,
                _resolve_channel,
                _validate_cron_expression,
                _validate_date_format,
                _validate_date_range,
                _validate_priority,
            )
            
            # B-1: Resolve channel
            channel = _resolve_channel(db, channel_selector)
            
            # B-2: Check name uniqueness
            _check_name_uniqueness(db, channel.id, name)
            
            # B-3: Validate date range
            parsed_start_date = _validate_date_format(start_date) if start_date else None
            parsed_end_date = _validate_date_format(end_date) if end_date else None
            _validate_date_range(parsed_start_date, parsed_end_date)
            
            # B-4: Validate cron expression
            _validate_cron_expression(cron)
            
            # B-5: Validate priority
            validated_priority = _validate_priority(priority)
            
            # Create plan (not committed yet)
            plan = SchedulePlan(
                channel_id=channel.id,
                name=name,
                description=description,
                cron_expression=cron,
                start_date=parsed_start_date,
                end_date=parsed_end_date,
                priority=validated_priority,
                is_active=is_active,
            )
            
            db.add(plan)
            # Don't commit yet - REPL will commit on 'save' or rollback on 'discard'
            
            # Enter REPL
            session = PlanningSession(
                db=db,
                channel_id=str(channel.id),
                plan_id=str(plan.id),
                plan_name=name,
            )
            
            exit_code = session.run()
            raise typer.Exit(exit_code)
            
        except typer.Exit:
            raise
        except ValueError as e:
            error_msg = str(e)
            typer.echo(f"Error: {error_msg}", err=True)
            raise typer.Exit(1)
        except Exception as e:
            error_msg = str(e)
            typer.echo(f"Error creating plan: {error_msg}", err=True)
            raise typer.Exit(1)


@plan_mgmt_app.command("list")
def list_plans(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    active_only: bool = typer.Option(False, "--active-only", help="Filter to active plans only (reserved for future)"),
    inactive_only: bool = typer.Option(False, "--inactive-only", help="Filter to inactive plans only (reserved for future)"),
    limit: int | None = typer.Option(None, "--limit", help="Limit number of results (reserved for future)"),
    offset: int | None = typer.Option(None, "--offset", help="Offset for pagination (reserved for future)"),
    test_db: bool = typer.Option(False, "--test-db", help="Use test database context"),
):
    """List all plans for a channel per SchedulePlanListContract.md."""
    channel_selector = ctx.obj.get("channel_selector")
    
    if not channel_selector:
        error_msg = "Channel selector required"
        if json_output:
            typer.echo(json.dumps({"status": "error", "code": "CHANNEL_NOT_FOUND", "message": f"Error: {error_msg}"}, indent=2))
        else:
            typer.echo(f"Error: {error_msg}", err=True)
        raise typer.Exit(1)
    
    # B-5: Warn about reserved flags (future-safe)
    warnings = []
    if active_only:
        warnings.append("--active-only is reserved for future implementation")
    if inactive_only:
        warnings.append("--inactive-only is reserved for future implementation")
    if limit is not None:
        warnings.append("--limit is reserved for future implementation")
    if offset is not None:
        warnings.append("--offset is reserved for future implementation")
    
    db_cm = _get_db_context(test_db)
    
    with db_cm as db:
        try:
            # Delegate to usecase
            result = _uc_plan_list.list_plans(
                db,
                channel_identifier=channel_selector,
            )
            
            # B-7: Handle zero results
            if result["total"] == 0:
                if json_output:
                    typer.echo(json.dumps(result, indent=2))
                else:
                    channel = _resolve_channel(db, channel_selector)
                    channel_name = channel.title if channel else channel_selector
                    typer.echo(f"No plans found for channel {channel_name}")
                return
            
            if json_output:
                typer.echo(json.dumps(result, indent=2))
            else:
                # B-8: Human-readable output with consistent field order
                channel = _resolve_channel(db, channel_selector)
                channel_name = channel.title if channel else channel_selector
                typer.echo(f"Plans for channel {channel_name}:")
                for plan in result["plans"]:
                    typer.echo(f"  ID: {plan['id']}")
                    typer.echo(f"  Name: {plan['name']}")
                    if plan.get("description"):
                        typer.echo(f"  Description: {plan['description']}")
                    else:
                        typer.echo("  Description: -")
                    if plan.get("cron_expression"):
                        typer.echo(f"  Cron: {plan['cron_expression']} (hour/min ignored)")
                    else:
                        typer.echo("  Cron: null")
                    if plan.get("start_date"):
                        typer.echo(f"  Start Date: {plan['start_date']}")
                    else:
                        typer.echo("  Start Date: -")
                    if plan.get("end_date"):
                        typer.echo(f"  End Date: {plan['end_date']}")
                    else:
                        typer.echo("  End Date: -")
                    typer.echo(f"  Priority: {plan['priority']}")
                    typer.echo(f"  Active: {plan['is_active']}")
                    if plan.get("created_at"):
                        typer.echo(f"  Created: {plan['created_at']}")
                    typer.echo("")
                typer.echo(f"Total: {result['total']} plans")
            return
        except typer.Exit:
            raise
        except ValueError as e:
            error_msg = str(e)
            error_code = "CHANNEL_NOT_FOUND" if "Channel" in error_msg and "not found" in error_msg else "VALIDATION_ERROR"
            
            if json_output:
                typer.echo(json.dumps({"status": "error", "code": error_code, "message": f"Error: {error_msg}"}, indent=2))
            else:
                typer.echo(f"Error: {error_msg}", err=True)
            raise typer.Exit(1)
        except Exception as e:
            error_msg = str(e)
            if json_output:
                typer.echo(json.dumps({"status": "error", "code": "UNKNOWN_ERROR", "message": f"Error: {error_msg}"}, indent=2))
            else:
                typer.echo(f"Error listing plans: {error_msg}", err=True)
            raise typer.Exit(1)


@plan_mgmt_app.command("show")
def show_plan(
    ctx: typer.Context,
    plan_selector: str = typer.Argument(..., help="Plan identifier: UUID or name"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    with_contents: bool = typer.Option(False, "--with-contents", help="Include lightweight summaries of Zones and Patterns"),
    computed: bool = typer.Option(False, "--computed", help="Include computed fields (effective_today, next_applicable_date)"),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output"),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress extraneous output lines"),
    test_db: bool = typer.Option(False, "--test-db", help="Use test database context"),
):
    """Show a schedule plan per SchedulePlanShowContract.md."""
    channel_selector = ctx.obj.get("channel_selector")
    
    if not channel_selector or not plan_selector:
        error_msg = "Channel and plan selectors required"
        if json_output:
            typer.echo(json.dumps({"status": "error", "code": "CHANNEL_NOT_FOUND", "message": f"Error: {error_msg}"}, indent=2))
        else:
            typer.echo(f"Error: {error_msg}", err=True)
        raise typer.Exit(1)
    
    db_cm = _get_db_context(test_db)
    
    with db_cm as db:
        try:
            # Delegate to usecase
            result = _uc_plan_show.show_plan(
                db,
                channel_identifier=channel_selector,
                plan_identifier=plan_selector,
                with_contents=with_contents,
                computed=computed,
            )
            
            if json_output:
                # Usecase already returns correct JSON structure
                typer.echo(json.dumps(result, indent=2))
            else:
                # Human-readable output
                plan = result["plan"]
                channel = _resolve_channel(db, channel_selector)
                channel_name = channel.title if channel else channel_selector
                
                if not quiet:
                    typer.echo("Plan:")
                typer.echo(f"  ID: {plan['id']}")
                typer.echo(f"  Channel: {channel_name} ({plan['channel_id']})")
                typer.echo(f"  Name: {plan['name']}")
                if plan.get("description"):
                    typer.echo(f"  Description: {plan['description']}")
                if plan.get("cron_expression"):
                    typer.echo(f"  Cron: {plan['cron_expression']} (hour/min ignored)")
                if plan.get("start_date"):
                    typer.echo(f"  Start Date: {plan['start_date']}")
                if plan.get("end_date"):
                    typer.echo(f"  End Date: {plan['end_date']}")
                typer.echo(f"  Priority: {plan['priority']}")
                typer.echo(f"  Active: {plan['is_active']}")
                if plan.get("created_at"):
                    typer.echo(f"  Created: {plan['created_at']}")
                if plan.get("updated_at"):
                    typer.echo(f"  Updated: {plan['updated_at']}")
                
                # B-6: Add zones and patterns if with_contents
                if with_contents and "zones" in result.get("plan", {}):
                    typer.echo("")
                    typer.echo(f"Zones (count: {len(result['plan'].get('zones', []))}):")
                    for _zone in result["plan"].get("zones", []):
                        # TODO: Format zone output when Zone entity exists
                        pass
                if with_contents and "patterns" in result.get("plan", {}):
                    typer.echo("")
                    typer.echo(f"Patterns (count: {len(result['plan'].get('patterns', []))}):")
                    for _pattern in result["plan"].get("patterns", []):
                        # TODO: Format pattern output when Pattern entity exists
                        pass
            return
        except typer.Exit:
            raise
        except ValueError as e:
            error_msg = str(e)
            # Map error messages to error codes per contract
            # Check "does not belong" FIRST, before "Plan" and "not found"
            error_code = "VALIDATION_ERROR"
            if "Channel" in error_msg and "not found" in error_msg:
                error_code = "CHANNEL_NOT_FOUND"
            elif "does not belong" in error_msg:
                error_code = "PLAN_WRONG_CHANNEL"
            elif "Plan" in error_msg and "not found" in error_msg:
                error_code = "PLAN_NOT_FOUND"
            
            if json_output:
                typer.echo(json.dumps({"status": "error", "code": error_code, "message": f"Error: {error_msg}"}, indent=2))
            else:
                typer.echo(f"Error: {error_msg}", err=True)
            raise typer.Exit(1)
        except Exception as e:
            error_msg = str(e)
            if json_output:
                typer.echo(json.dumps({"status": "error", "code": "UNKNOWN_ERROR", "message": f"Error: {error_msg}"}, indent=2))
            else:
                typer.echo(f"Error showing plan: {error_msg}", err=True)
            raise typer.Exit(1)


@plan_mgmt_app.command("update")
def update_plan(
    ctx: typer.Context,
    plan_selector: str = typer.Argument(..., help="Plan identifier: UUID or name"),
    name: str | None = typer.Option(None, "--name", help="Update plan name (must be unique within channel)"),
    description: str | None = typer.Option(None, "--description", help="Update description"),
    cron: str | None = typer.Option(None, "--cron", help="Update cron expression (hour/min ignored)"),
    start_date: str | None = typer.Option(None, "--start-date", help="Update start date (YYYY-MM-DD)"),
    end_date: str | None = typer.Option(None, "--end-date", help="Update end date (YYYY-MM-DD)"),
    priority: int | None = typer.Option(None, "--priority", help="Update priority"),
    active: bool | None = typer.Option(None, "--active", help="Set active status"),
    inactive: bool = typer.Option(False, "--inactive", help="Set inactive status"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    test_db: bool = typer.Option(False, "--test-db", help="Use test database context"),
):
    """Update a schedule plan per SchedulePlanUpdateContract.md."""
    channel_selector = ctx.obj.get("channel_selector")
    
    if not channel_selector or not plan_selector:
        error_msg = "Channel and plan selectors required"
        if json_output:
            typer.echo(json.dumps({"status": "error", "code": "CHANNEL_NOT_FOUND", "message": f"Error: {error_msg}"}, indent=2))
        else:
            typer.echo(f"Error: {error_msg}", err=True)
        raise typer.Exit(1)
    
    # Handle --active/--inactive flags
    is_active = None
    if active:
        is_active = True
    elif inactive:
        is_active = False
    
    db_cm = _get_db_context(test_db)
    
    with db_cm as db:
        try:
            # Delegate to usecase
            result = _uc_plan_update.update_plan(
                db,
                channel_identifier=channel_selector,
                plan_identifier=plan_selector,
                name=name,
                description=description,
                cron_expression=cron,
                start_date=start_date,
                end_date=end_date,
                priority=priority,
                is_active=is_active,
            )
            
            if json_output:
                # Usecase already returns correct JSON structure
                typer.echo(json.dumps(result, indent=2))
            else:
                # Human-readable output
                plan = result["plan"]
                channel = _resolve_channel(db, channel_selector)
                channel_name = channel.title if channel else channel_selector
                typer.echo("Plan updated:")
                typer.echo(f"  ID: {plan['id']}")
                typer.echo(f"  Channel: {channel_name} ({plan['channel_id']})")
                typer.echo(f"  Name: {plan['name']}")
                if plan.get("description"):
                    typer.echo(f"  Description: {plan['description']}")
                if plan.get("cron_expression"):
                    typer.echo(f"  Cron: {plan['cron_expression']} (hour/min ignored)")
                if plan.get("start_date"):
                    typer.echo(f"  Start Date: {plan['start_date']}")
                if plan.get("end_date"):
                    typer.echo(f"  End Date: {plan['end_date']}")
                typer.echo(f"  Priority: {plan['priority']}")
                typer.echo(f"  Active: {plan['is_active']}")
                if plan.get("created_at"):
                    typer.echo(f"  Created: {plan['created_at']}")
                if plan.get("updated_at"):
                    typer.echo(f"  Updated: {plan['updated_at']}")
            return
        except typer.Exit:
            raise
        except ValueError as e:
            error_msg = str(e)
            # Map error messages to error codes per contract
            error_code = "VALIDATION_ERROR"
            if "Channel" in error_msg and "not found" in error_msg:
                error_code = "CHANNEL_NOT_FOUND"
            elif "does not belong" in error_msg:
                error_code = "PLAN_WRONG_CHANNEL"
            elif "Plan" in error_msg and "not found" in error_msg:
                error_code = "PLAN_NOT_FOUND"
            elif "already exists" in error_msg:
                error_code = "PLAN_NAME_DUPLICATE"
            elif "Invalid date format" in error_msg:
                error_code = "INVALID_DATE_FORMAT"
            elif "start_date must be <= end_date" in error_msg:
                error_code = "INVALID_DATE_RANGE"
            elif "Invalid cron expression" in error_msg:
                error_code = "INVALID_CRON"
            elif "Priority must be non-negative" in error_msg:
                error_code = "INVALID_PRIORITY"
            elif "At least one field must be provided" in error_msg:
                error_code = "NO_FIELDS_PROVIDED"
            
            exit_code = 2 if error_code == "NO_FIELDS_PROVIDED" else 1
            
            if json_output:
                typer.echo(json.dumps({"status": "error", "code": error_code, "message": f"Error: {error_msg}"}, indent=2))
            else:
                typer.echo(f"Error: {error_msg}", err=True)
            raise typer.Exit(exit_code)
        except Exception as e:
            error_msg = str(e)
            if json_output:
                typer.echo(json.dumps({"status": "error", "code": "UNKNOWN_ERROR", "message": f"Error: {error_msg}"}, indent=2))
            else:
                typer.echo(f"Error updating plan: {error_msg}", err=True)
            raise typer.Exit(1)


@plan_mgmt_app.command("delete")
def delete_plan(
    ctx: typer.Context,
    plan_selector: str = typer.Argument(..., help="Plan identifier: UUID or name"),
    yes: bool = typer.Option(False, "--yes", help="Confirm deletion (non-interactive)"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    test_db: bool = typer.Option(False, "--test-db", help="Use test database context"),
):
    """Delete a schedule plan per SchedulePlanDeleteContract.md."""
    channel_selector = ctx.obj.get("channel_selector")
    
    if not channel_selector or not plan_selector:
        error_msg = "Channel and plan selectors required"
        if json_output:
            typer.echo(json.dumps({"status": "error", "code": "CHANNEL_NOT_FOUND", "message": f"Error: {error_msg}"}, indent=2))
        else:
            typer.echo(f"Error: {error_msg}", err=True)
        raise typer.Exit(1)
    
    # B-3: Confirmation
    if not yes:
        if json_output:
            typer.echo(json.dumps({"status": "error", "code": "CONFIRMATION_REQUIRED", "message": "Error: Confirmation required (--yes)"}, indent=2))
        else:
            typer.echo("Deletion requires --yes confirmation", err=True)
        raise typer.Exit(1)
    
    db_cm = _get_db_context(test_db)
    
    with db_cm as db:
        try:
            # Delegate to usecase
            result = _uc_plan_delete.delete_plan(
                db,
                channel_identifier=channel_selector,
                plan_identifier=plan_selector,
            )
            
            if json_output:
                typer.echo(json.dumps(result, indent=2))
            else:
                # Human-readable output - use plan name if available, otherwise ID
                typer.echo(f"Plan deleted: {plan_selector}")
            return
        except typer.Exit:
            raise
        except ValueError as e:
            error_msg = str(e)
            # Map error messages to error codes per contract
            # Check "does not belong" FIRST, before "Plan" and "not found"
            error_code = "VALIDATION_ERROR"
            if "Channel" in error_msg and "not found" in error_msg:
                error_code = "CHANNEL_NOT_FOUND"
            elif "does not belong" in error_msg:
                error_code = "PLAN_WRONG_CHANNEL"
            elif "Plan" in error_msg and "not found" in error_msg:
                error_code = "PLAN_NOT_FOUND"
            elif "Cannot delete" in error_msg or "has" in error_msg and "zone" in error_msg.lower():
                error_code = "PLAN_HAS_DEPENDENCIES"
            
            if json_output:
                typer.echo(json.dumps({"status": "error", "code": error_code, "message": f"Error: {error_msg}"}, indent=2))
            else:
                typer.echo(f"Error: {error_msg}", err=True)
            raise typer.Exit(1)
        except Exception as e:
            error_msg = str(e)
            if json_output:
                typer.echo(json.dumps({"status": "error", "code": "UNKNOWN_ERROR", "message": f"Error: {error_msg}"}, indent=2))
            else:
                typer.echo(f"Error deleting plan: {error_msg}", err=True)
            raise typer.Exit(1)


# Program subcommands (require both channel and plan)
# Structure: retrovue channel program <channel> <plan> <command>
# We use a separate command path for programs to avoid conflicts
program_cmd_app = typer.Typer(name="program", help="Program management operations (requires channel and plan)")
app.add_typer(program_cmd_app)


@program_cmd_app.callback(invoke_without_command=True)
def program_cmd_callback(
    ctx: typer.Context,
    channel_selector: str = typer.Argument(..., help="Channel identifier: UUID or slug"),
    plan_selector: str = typer.Argument(..., help="Plan identifier: UUID"),
):
    """Program operations that require both channel and plan."""
    ctx.ensure_object(dict)
    ctx.obj["channel_selector"] = channel_selector
    ctx.obj["plan_selector"] = plan_selector
    # If no subcommand was invoked, show help
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


program_app = typer.Typer(name="program", help="Program management operations")
program_cmd_app.add_typer(program_app)


def _resolve_channel(db, selector: str) -> Channel:
    """Resolve channel by UUID or slug."""
    channel = None
    try:
        _ = _uuid.UUID(selector)
        channel = db.execute(select(Channel).where(Channel.id == selector)).scalars().first()
    except Exception:
        pass
    
    if not channel:
        channel = (
            db.execute(select(Channel).where(func.lower(Channel.slug) == selector.lower()))
            .scalars()
            .first()
        )
    
    if not channel:
        raise ValueError(f"Channel '{selector}' not found")
    
    return channel  # type: ignore[no-any-return]


def _resolve_plan(db, channel_id: _uuid.UUID, selector: str) -> SchedulePlan:
    """Resolve plan by UUID or name (case-insensitive, trimmed).
    
    Uses the usecase's _resolve_plan for consistent resolution logic.
    """
    return _uc_resolve_plan(db, channel_id, selector)


def _validate_time_format(time_str: str) -> None:
    """Validate HH:MM format."""
    parts = time_str.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time format: {time_str}. Expected HH:MM")
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        if not (0 <= hours < 24 and 0 <= minutes < 60):
            raise ValueError(f"Time out of range: {time_str}")
    except (ValueError, AttributeError) as e:
        raise ValueError(f"Invalid time format: {time_str}") from e


@program_app.command("add")
def add_program(
    ctx: typer.Context,
    start: str = typer.Option(..., "--start", help="Start time in HH:MM format (schedule-time)"),
    duration: int = typer.Option(..., "--duration", help="Duration in minutes"),
    series: str | None = typer.Option(None, "--series", help="Series identifier or name"),
    asset: str | None = typer.Option(None, "--asset", help="Asset UUID"),
    virtual_asset: str | None = typer.Option(None, "--virtual-asset", help="VirtualAsset UUID"),
    rule: str | None = typer.Option(None, "--rule", help="Rule JSON for filtered selection"),
    random: str | None = typer.Option(None, "--random", help="Random selection rule JSON"),
    episode_policy: str | None = typer.Option(None, "--episode-policy", help="Episode selection policy (sequential, syndication, random, seasonal)"),
    label_id: str | None = typer.Option(None, "--label-id", help="SchedulePlanLabel UUID for visual grouping"),
    operator_intent: str | None = typer.Option(None, "--operator-intent", help="Operator-defined metadata describing programming intent"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    test_db: bool = typer.Option(False, "--test-db", help="Use test database context"),
):
    """
    Add a program to a schedule plan.
    
    A program defines what content runs when within a plan. You must specify
    one content type: --series, --asset, --virtual-asset, --rule, or --random.
    
    Examples:
        retro channel abc plan xyz program add --start 06:00 --duration 30 --series "Cheers"
        retro channel abc plan xyz program add --start 20:00 --duration 120 --asset <uuid>
        retro channel abc plan xyz program add --start 22:00 --duration 120 --virtual-asset <uuid>
    """
    channel_selector = ctx.obj.get("channel_selector")
    plan_selector = ctx.obj.get("plan_selector")
    
    if not channel_selector or not plan_selector:
        if json_output:
            typer.echo(json.dumps({"status": "error", "error": "Channel and plan selectors required"}, indent=2))
        else:
            typer.echo("Error: Channel and plan selectors required", err=True)
        raise typer.Exit(1)
    
    db_cm = _get_db_context(test_db)
    
    with db_cm as db:
        try:
            # Validate content type selection
            content_types = [series, asset, virtual_asset, rule, random]
            selected_count = sum(1 for ct in content_types if ct is not None)
            
            if selected_count == 0:
                if json_output:
                    typer.echo(json.dumps({"status": "error", "error": "Must specify one content type: --series, --asset, --virtual-asset, --rule, or --random"}, indent=2))
                else:
                    typer.echo("Error: Must specify one content type: --series, --asset, --virtual-asset, --rule, or --random", err=True)
                raise typer.Exit(1)
            
            if selected_count > 1:
                if json_output:
                    typer.echo(json.dumps({"status": "error", "error": "Must specify only one content type"}, indent=2))
                else:
                    typer.echo("Error: Must specify only one content type", err=True)
                raise typer.Exit(1)
            
            # Validate start time format
            try:
                _validate_time_format(start)
            except ValueError as e:
                if json_output:
                    typer.echo(json.dumps({"status": "error", "error": str(e)}, indent=2))
                else:
                    typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(1)
            
            # Validate duration
            if duration <= 0:
                error_msg = "Duration must be a positive integer"
                if json_output:
                    typer.echo(json.dumps({"status": "error", "error": error_msg}, indent=2))
                else:
                    typer.echo(f"Error: {error_msg}", err=True)
                raise typer.Exit(1)
            
            # Resolve channel
            try:
                channel = _resolve_channel(db, channel_selector)
            except ValueError as e:
                if json_output:
                    typer.echo(json.dumps({"status": "error", "error": str(e)}, indent=2))
                else:
                    typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(1)
            
            # Resolve plan
            try:
                plan = _resolve_plan(db, channel.id, plan_selector)
            except ValueError as e:
                if json_output:
                    typer.echo(json.dumps({"status": "error", "error": str(e)}, indent=2))
                else:
                    typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(1)
            
            # Determine content type and reference
            if series:
                content_type = "series"
                content_ref = series
            elif asset:
                content_type = "asset"
                content_ref = asset
            elif virtual_asset:
                content_type = "virtual_package"
                content_ref = virtual_asset
            elif rule:
                content_type = "rule"
                content_ref = rule
            else:  # random
                content_type = "random"
                assert random is not None  # Validated above that exactly one content type is set
                content_ref = random
            
            # Resolve label_id if provided
            label_uuid = None
            if label_id:
                try:
                    label_uuid = _uuid.UUID(label_id)
                    label_exists = db.execute(
                        select(SchedulePlanLabel).where(SchedulePlanLabel.id == label_uuid)
                    ).scalars().first()
                    if not label_exists:
                        raise ValueError(f"Label '{label_id}' not found")
                except ValueError as e:
                    if json_output:
                        typer.echo(json.dumps({"status": "error", "error": str(e)}, indent=2))
                    else:
                        typer.echo(f"Error: {e}", err=True)
                    raise typer.Exit(1)
            
            # Create program
            program = Program(
                channel_id=channel.id,
                plan_id=plan.id,
                start_time=start,
                duration=duration,
                content_type=content_type,
                content_ref=content_ref,
                episode_policy=episode_policy,
                label_id=label_uuid,
                operator_intent=operator_intent,
            )
            
            db.add(program)
            db.commit()
            db.refresh(program)
            
            result = {
                "id": str(program.id),
                "channel_id": str(program.channel_id),
                "plan_id": str(program.plan_id),
                "start_time": program.start_time,
                "duration": program.duration,
                "content_type": program.content_type,
                "content_ref": program.content_ref,
                "created_at": program.created_at.isoformat() if program.created_at else None,
            }
            
            if json_output:
                typer.echo(json.dumps({"status": "ok", "program": result}, indent=2))
            else:
                typer.echo("Program created:")
                typer.echo(f"  ID: {result['id']}")
                typer.echo(f"  Start: {result['start_time']}")
                typer.echo(f"  Duration: {result['duration']} minutes")
                typer.echo(f"  Content Type: {result['content_type']}")
            return
        except typer.Exit:
            raise
        except Exception as e:
            if json_output:
                typer.echo(json.dumps({"status": "error", "error": str(e)}, indent=2))
            else:
                typer.echo(f"Error adding program: {e}", err=True)
            raise typer.Exit(1)


@program_app.command("list")
def list_programs(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    test_db: bool = typer.Option(False, "--test-db", help="Use test database context"),
):
    """
    List all programs in a schedule plan.
    
    Examples:
        retro channel abc plan xyz program list
        retro channel abc plan xyz program list --json
    """
    channel_selector = ctx.obj.get("channel_selector")
    plan_selector = ctx.obj.get("plan_selector")
    
    if not channel_selector or not plan_selector:
        if json_output:
            typer.echo(json.dumps({"status": "error", "error": "Channel and plan selectors required"}, indent=2))
        else:
            typer.echo("Error: Channel and plan selectors required", err=True)
        raise typer.Exit(1)
    
    db_cm = _get_db_context(test_db)
    
    with db_cm as db:
        try:
            # Resolve channel
            try:
                channel = _resolve_channel(db, channel_selector)
            except ValueError as e:
                if json_output:
                    typer.echo(json.dumps({"status": "error", "error": str(e)}, indent=2))
                else:
                    typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(1)
            
            # Resolve plan
            try:
                plan = _resolve_plan(db, channel.id, plan_selector)
            except ValueError as e:
                if json_output:
                    typer.echo(json.dumps({"status": "error", "error": str(e)}, indent=2))
                else:
                    typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(1)
            
            # Query programs for the plan, ordered by start_time
            programs = (
                db.execute(
                    select(Program)
                    .where(Program.plan_id == plan.id)
                    .order_by(Program.start_time)
                )
                .scalars()
                .all()
            )
            
            items = [
                {
                    "id": str(p.id),
                    "start_time": p.start_time,
                    "duration": p.duration,
                    "content_type": p.content_type,
                    "content_ref": p.content_ref,
                    "episode_policy": p.episode_policy,
                    "operator_intent": p.operator_intent,
                    "label_id": str(p.label_id) if p.label_id else None,
                }
                for p in programs
            ]
            
            if json_output:
                typer.echo(json.dumps({"status": "ok", "total": len(items), "programs": items}, indent=2))
            else:
                if not items:
                    typer.echo("No programs found")
                else:
                    typer.echo("Programs:")
                    for p in items:
                        typer.echo(f"  ID: {p['id']}")
                        typer.echo(f"  Start: {p['start_time']}")
                        typer.echo(f"  Duration: {p['duration']} minutes")
                        typer.echo(f"  Content Type: {p['content_type']}")
                        if p.get("episode_policy"):
                            typer.echo(f"  Episode Policy: {p['episode_policy']}")
                        typer.echo("")
                    typer.echo(f"Total: {len(items)} programs")
            return
        except typer.Exit:
            raise
        except Exception as e:
            if json_output:
                typer.echo(json.dumps({"status": "error", "error": str(e)}, indent=2))
            else:
                typer.echo(f"Error listing programs: {e}", err=True)
            raise typer.Exit(1)


@program_app.command("delete")
def delete_program(
    ctx: typer.Context,
    program_id: str = typer.Argument(..., help="Program UUID to delete"),
    yes: bool = typer.Option(False, "--yes", help="Confirm deletion (non-interactive)"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    test_db: bool = typer.Option(False, "--test-db", help="Use test database context"),
):
    """
    Delete a program from a schedule plan.
    
    Examples:
        retro channel abc plan xyz program delete 1234
        retro channel abc plan xyz program delete 1234 --yes
    """
    channel_selector = ctx.obj.get("channel_selector")
    plan_selector = ctx.obj.get("plan_selector")
    
    if not channel_selector or not plan_selector:
        if json_output:
            typer.echo(json.dumps({"status": "error", "error": "Channel and plan selectors required"}, indent=2))
        else:
            typer.echo("Error: Channel and plan selectors required", err=True)
        raise typer.Exit(1)
    
    db_cm = _get_db_context(test_db)
    
    with db_cm as db:
        try:
            # Confirmation
            if not yes:
                if json_output:
                    typer.echo(json.dumps({"status": "error", "error": "Confirmation required (--yes)"}, indent=2))
                else:
                    typer.echo("Deletion requires --yes confirmation", err=True)
                raise typer.Exit(1)
            
            # Resolve channel
            try:
                channel = _resolve_channel(db, channel_selector)
            except ValueError as e:
                if json_output:
                    typer.echo(json.dumps({"status": "error", "error": str(e)}, indent=2))
                else:
                    typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(1)
            
            # Resolve plan
            try:
                plan = _resolve_plan(db, channel.id, plan_selector)
            except ValueError as e:
                if json_output:
                    typer.echo(json.dumps({"status": "error", "error": str(e)}, indent=2))
                else:
                    typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(1)
            
            # Resolve program
            try:
                program_uuid = _uuid.UUID(program_id)
            except ValueError:
                error_msg = f"Invalid program UUID: {program_id}"
                if json_output:
                    typer.echo(json.dumps({"status": "error", "error": error_msg}, indent=2))
                else:
                    typer.echo(f"Error: {error_msg}", err=True)
                raise typer.Exit(1)
            
            program = (
                db.execute(
                    select(Program).where(
                        Program.id == program_uuid,
                        Program.plan_id == plan.id,
                    )
                )
                .scalars()
                .first()
            )
            
            if not program:
                error_msg = f"Program '{program_id}' not found in plan"
                if json_output:
                    typer.echo(json.dumps({"status": "error", "error": error_msg}, indent=2))
                else:
                    typer.echo(f"Error: {error_msg}", err=True)
                raise typer.Exit(1)
            
            # Delete program
            db.delete(program)
            db.commit()
            
            if json_output:
                typer.echo(json.dumps({"status": "ok", "deleted": 1, "id": program_id}, indent=2))
            else:
                typer.echo(f"Program deleted: {program_id}")
            return
        except typer.Exit:
            raise
        except Exception as e:
            if json_output:
                typer.echo(json.dumps({"status": "error", "error": str(e)}, indent=2))
            else:
                typer.echo(f"Error deleting program: {e}", err=True)
            raise typer.Exit(1)