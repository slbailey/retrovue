from __future__ import annotations

import json

import typer

from ...infra.db import get_sessionmaker
from ...infra.settings import settings
from ...infra.uow import session
from ...usecases import zone_add as _uc_zone_add
from ...usecases import zone_delete as _uc_zone_delete
from ...usecases import zone_list as _uc_zone_list
from ...usecases import zone_update as _uc_zone_update

app = typer.Typer(name="zone", help="Zone (daypart) management operations")


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


@app.command("add")
def add_zone(
    plan: str = typer.Option(..., "--plan", help="Plan identifier: UUID or name"),
    name: str = typer.Option(..., "--name", help="Zone name (e.g., 'Morning Cartoons')"),
    start_time: str = typer.Option(..., "--start", help="Start time in HH:MM format (broadcast day time)"),
    end_time: str = typer.Option(..., "--end", help="End time in HH:MM format (use 24:00 for end of day)"),
    assets: str | None = typer.Option(None, "--assets", help="Comma-separated list of asset/program UUIDs"),
    days: str | None = typer.Option(None, "--days", help="Day filter: comma-separated (MON,TUE,WED,THU,FRI,SAT,SUN)"),
    enabled: bool = typer.Option(True, "--enabled/--disabled", help="Zone active status"),
    effective_start: str | None = typer.Option(None, "--effective-start", help="Start date (YYYY-MM-DD)"),
    effective_end: str | None = typer.Option(None, "--effective-end", help="End date (YYYY-MM-DD)"),
    dst_policy: str | None = typer.Option(None, "--dst-policy", help="DST policy: reject, shrink_one_block, expand_one_block"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    test_db: bool = typer.Option(False, "--test-db", help="Use test database context"),
):
    """Create a new zone (daypart) in a schedule plan.

    Zones are named time windows that organize the broadcast day into logical
    areas like "Morning Cartoons", "Prime Time", or "Late Night Horror".

    Examples:
        retrovue zone add --plan my-plan --name "Morning Cartoons" --start 06:00 --end 12:00
        retrovue zone add --plan my-plan --name "Weekend Movies" --start 19:00 --end 24:00 --days SAT,SUN
    """
    db_cm = _get_db_context(test_db)

    with db_cm as db:
        try:
            # Parse assets list
            schedulable_assets = None
            if assets:
                schedulable_assets = [a.strip() for a in assets.split(",") if a.strip()]

            # Parse day filters
            day_filters = None
            if days:
                day_filters = [d.strip().upper() for d in days.split(",") if d.strip()]

            result = _uc_zone_add.add_zone(
                db,
                plan_identifier=plan,
                name=name,
                start_time=start_time,
                end_time=end_time,
                schedulable_assets=schedulable_assets,
                day_filters=day_filters,
                enabled=enabled,
                effective_start=effective_start,
                effective_end=effective_end,
                dst_policy=dst_policy,
            )

            if json_output:
                payload = {"status": "ok", "zone": result}
                typer.echo(json.dumps(payload, indent=2))
            else:
                typer.echo("Zone created:")
                typer.echo(f"  ID: {result['id']}")
                typer.echo(f"  Plan: {result['plan_id']}")
                typer.echo(f"  Name: {result['name']}")
                typer.echo(f"  Time: {result['start_time']} - {result['end_time']}")
                if result.get("day_filters"):
                    typer.echo(f"  Days: {', '.join(result['day_filters'])}")
                typer.echo(f"  Enabled: {result['enabled']}")
                if result.get("schedulable_assets"):
                    typer.echo(f"  Assets: {len(result['schedulable_assets'])} assigned")
                if result.get("effective_start"):
                    typer.echo(f"  Effective Start: {result['effective_start']}")
                if result.get("effective_end"):
                    typer.echo(f"  Effective End: {result['effective_end']}")
                if result.get("dst_policy"):
                    typer.echo(f"  DST Policy: {result['dst_policy']}")
            return
        except typer.Exit:
            raise
        except ValueError as e:
            error_msg = str(e)
            error_code = "VALIDATION_ERROR"
            if "Plan" in error_msg and "not found" in error_msg:
                error_code = "PLAN_NOT_FOUND"
            elif "already exists" in error_msg:
                error_code = "ZONE_NAME_DUPLICATE"
            elif "Invalid time format" in error_msg:
                error_code = "INVALID_TIME_FORMAT"
            elif "Invalid day filter" in error_msg:
                error_code = "INVALID_DAY_FILTER"
            elif "Invalid date format" in error_msg:
                error_code = "INVALID_DATE_FORMAT"
            elif "effective_start must be <= effective_end" in error_msg:
                error_code = "INVALID_DATE_RANGE"
            elif "Invalid DST policy" in error_msg:
                error_code = "INVALID_DST_POLICY"

            if json_output:
                typer.echo(json.dumps({"status": "error", "code": error_code, "message": error_msg}, indent=2))
            else:
                typer.echo(f"Error: {error_msg}", err=True)
            raise typer.Exit(1)
        except Exception as e:
            if json_output:
                typer.echo(json.dumps({"status": "error", "code": "UNKNOWN_ERROR", "message": str(e)}, indent=2))
            else:
                typer.echo(f"Error creating zone: {e}", err=True)
            raise typer.Exit(1)


@app.command("list")
def list_zones(
    plan: str | None = typer.Option(None, "--plan", help="Filter by plan identifier: UUID or name"),
    enabled_only: bool = typer.Option(False, "--enabled-only", help="Show only enabled zones"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    test_db: bool = typer.Option(False, "--test-db", help="Use test database context"),
):
    """List zones (dayparts), optionally filtered by plan.

    Examples:
        retrovue zone list
        retrovue zone list --plan my-plan
        retrovue zone list --enabled-only --json
    """
    db_cm = _get_db_context(test_db)

    with db_cm as db:
        try:
            result = _uc_zone_list.list_zones(
                db,
                plan_identifier=plan,
                enabled_only=enabled_only,
            )

            if json_output:
                payload = {"status": "ok", "total": result["count"], "zones": result["zones"]}
                typer.echo(json.dumps(payload, indent=2))
            else:
                zones = result["zones"]
                if not zones:
                    typer.echo("No zones found")
                else:
                    typer.echo("Zones:")
                    for z in zones:
                        days_str = ""
                        if z.get("day_filters"):
                            days_str = f" ({', '.join(z['day_filters'])})"
                        status = "✓" if z["enabled"] else "✗"
                        typer.echo(f"  [{status}] {z['name']}: {z['start_time']} - {z['end_time']}{days_str}")
                        typer.echo(f"      ID: {z['id']}")
                        typer.echo(f"      Plan: {z['plan_id']}")
                    typer.echo(f"\nTotal: {result['count']} zones")
            return
        except typer.Exit:
            raise
        except ValueError as e:
            if json_output:
                typer.echo(json.dumps({"status": "error", "code": "PLAN_NOT_FOUND", "message": str(e)}, indent=2))
            else:
                typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)
        except Exception as e:
            if json_output:
                typer.echo(json.dumps({"status": "error", "code": "UNKNOWN_ERROR", "message": str(e)}, indent=2))
            else:
                typer.echo(f"Error listing zones: {e}", err=True)
            raise typer.Exit(1)


@app.command("show")
def show_zone(
    selector: str = typer.Argument(..., help="Zone identifier: UUID or name"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    test_db: bool = typer.Option(False, "--test-db", help="Use test database context"),
):
    """Show details of a zone (daypart).

    Examples:
        retrovue zone show "Morning Cartoons"
        retrovue zone show 123e4567-e89b-12d3-a456-426614174000 --json
    """
    db_cm = _get_db_context(test_db)

    with db_cm as db:
        try:
            result = _uc_zone_list.get_zone(db, zone_identifier=selector)

            if json_output:
                payload = {"status": "ok", "zone": result}
                typer.echo(json.dumps(payload, indent=2))
            else:
                typer.echo("Zone:")
                typer.echo(f"  ID: {result['id']}")
                typer.echo(f"  Plan: {result['plan_id']}")
                typer.echo(f"  Name: {result['name']}")
                typer.echo(f"  Time: {result['start_time']} - {result['end_time']}")
                typer.echo(f"  Enabled: {result['enabled']}")
                if result.get("day_filters"):
                    typer.echo(f"  Days: {', '.join(result['day_filters'])}")
                else:
                    typer.echo("  Days: All days")
                if result.get("schedulable_assets"):
                    typer.echo(f"  Assets: {len(result['schedulable_assets'])} assigned")
                    for asset in result["schedulable_assets"][:5]:
                        typer.echo(f"    - {asset}")
                    if len(result["schedulable_assets"]) > 5:
                        typer.echo(f"    ... and {len(result['schedulable_assets']) - 5} more")
                else:
                    typer.echo("  Assets: None")
                if result.get("effective_start"):
                    typer.echo(f"  Effective Start: {result['effective_start']}")
                if result.get("effective_end"):
                    typer.echo(f"  Effective End: {result['effective_end']}")
                if result.get("dst_policy"):
                    typer.echo(f"  DST Policy: {result['dst_policy']}")
                if result.get("created_at"):
                    typer.echo(f"  Created: {result['created_at']}")
                if result.get("updated_at"):
                    typer.echo(f"  Updated: {result['updated_at']}")
            return
        except typer.Exit:
            raise
        except ValueError as e:
            if json_output:
                typer.echo(json.dumps({"status": "error", "code": "ZONE_NOT_FOUND", "message": str(e)}, indent=2))
            else:
                typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)
        except Exception as e:
            if json_output:
                typer.echo(json.dumps({"status": "error", "code": "UNKNOWN_ERROR", "message": str(e)}, indent=2))
            else:
                typer.echo(f"Error showing zone: {e}", err=True)
            raise typer.Exit(1)


@app.command("update")
def update_zone(
    selector: str = typer.Argument(..., help="Zone identifier: UUID or name"),
    name: str | None = typer.Option(None, "--name", help="New zone name"),
    start_time: str | None = typer.Option(None, "--start", help="New start time in HH:MM format"),
    end_time: str | None = typer.Option(None, "--end", help="New end time in HH:MM format"),
    assets: str | None = typer.Option(None, "--assets", help="New comma-separated list of asset/program UUIDs"),
    days: str | None = typer.Option(None, "--days", help="New day filter: comma-separated (MON,TUE,...)"),
    clear_days: bool = typer.Option(False, "--clear-days", help="Clear day filter (all days)"),
    enabled: bool | None = typer.Option(None, "--enabled/--disabled", help="Zone active status"),
    effective_start: str | None = typer.Option(None, "--effective-start", help="New start date (YYYY-MM-DD)"),
    effective_end: str | None = typer.Option(None, "--effective-end", help="New end date (YYYY-MM-DD)"),
    clear_effective_start: bool = typer.Option(False, "--clear-effective-start", help="Clear effective start date"),
    clear_effective_end: bool = typer.Option(False, "--clear-effective-end", help="Clear effective end date"),
    dst_policy: str | None = typer.Option(None, "--dst-policy", help="New DST policy"),
    clear_dst_policy: bool = typer.Option(False, "--clear-dst-policy", help="Clear DST policy"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    test_db: bool = typer.Option(False, "--test-db", help="Use test database context"),
):
    """Update a zone (daypart).

    Examples:
        retrovue zone update "Morning Cartoons" --name "Cartoon Block"
        retrovue zone update my-zone --start 07:00 --end 11:00
        retrovue zone update my-zone --days MON,TUE,WED,THU,FRI
        retrovue zone update my-zone --clear-days  # all days
        retrovue zone update my-zone --disabled
    """
    db_cm = _get_db_context(test_db)

    with db_cm as db:
        try:
            # Parse assets list
            schedulable_assets = None
            if assets is not None:
                schedulable_assets = [a.strip() for a in assets.split(",") if a.strip()]

            # Parse day filters
            day_filters = None
            if days is not None:
                day_filters = [d.strip().upper() for d in days.split(",") if d.strip()]

            result = _uc_zone_update.update_zone(
                db,
                zone_identifier=selector,
                name=name,
                start_time=start_time,
                end_time=end_time,
                schedulable_assets=schedulable_assets,
                day_filters=day_filters,
                clear_day_filters=clear_days,
                enabled=enabled,
                effective_start=effective_start,
                effective_end=effective_end,
                clear_effective_start=clear_effective_start,
                clear_effective_end=clear_effective_end,
                dst_policy=dst_policy,
                clear_dst_policy=clear_dst_policy,
            )

            if json_output:
                payload = {"status": "ok", "zone": result}
                typer.echo(json.dumps(payload, indent=2))
            else:
                typer.echo("Zone updated:")
                typer.echo(f"  ID: {result['id']}")
                typer.echo(f"  Name: {result['name']}")
                typer.echo(f"  Time: {result['start_time']} - {result['end_time']}")
                typer.echo(f"  Enabled: {result['enabled']}")
                if result.get("day_filters"):
                    typer.echo(f"  Days: {', '.join(result['day_filters'])}")
                else:
                    typer.echo("  Days: All days")
            return
        except typer.Exit:
            raise
        except ValueError as e:
            error_msg = str(e)
            error_code = "VALIDATION_ERROR"
            if "Zone" in error_msg and "not found" in error_msg:
                error_code = "ZONE_NOT_FOUND"
            elif "already exists" in error_msg:
                error_code = "ZONE_NAME_DUPLICATE"

            if json_output:
                typer.echo(json.dumps({"status": "error", "code": error_code, "message": error_msg}, indent=2))
            else:
                typer.echo(f"Error: {error_msg}", err=True)
            raise typer.Exit(1)
        except Exception as e:
            if json_output:
                typer.echo(json.dumps({"status": "error", "code": "UNKNOWN_ERROR", "message": str(e)}, indent=2))
            else:
                typer.echo(f"Error updating zone: {e}", err=True)
            raise typer.Exit(1)


@app.command("delete")
def delete_zone(
    selector: str = typer.Argument(..., help="Zone identifier: UUID or name"),
    yes: bool = typer.Option(False, "--yes", help="Confirm deletion (non-interactive)"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    test_db: bool = typer.Option(False, "--test-db", help="Use test database context"),
):
    """Delete a zone (daypart).

    Requires --yes to confirm deletion.

    Examples:
        retrovue zone delete "Morning Cartoons" --yes
        retrovue zone delete 123e4567-e89b-12d3-a456-426614174000 --yes --json
    """
    if not yes:
        if json_output:
            typer.echo(json.dumps({"status": "error", "code": "CONFIRMATION_REQUIRED", "message": "Deletion requires --yes confirmation"}, indent=2))
        else:
            typer.echo("Deletion requires --yes confirmation", err=True)
        raise typer.Exit(1)

    db_cm = _get_db_context(test_db)

    with db_cm as db:
        try:
            result = _uc_zone_delete.delete_zone(db, zone_identifier=selector)

            if json_output:
                payload = {"status": "ok", "deleted": result}
                typer.echo(json.dumps(payload, indent=2))
            else:
                typer.echo(f"Zone deleted: {result['name']} ({result['id']})")
            return
        except typer.Exit:
            raise
        except ValueError as e:
            if json_output:
                typer.echo(json.dumps({"status": "error", "code": "ZONE_NOT_FOUND", "message": str(e)}, indent=2))
            else:
                typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)
        except Exception as e:
            if json_output:
                typer.echo(json.dumps({"status": "error", "code": "UNKNOWN_ERROR", "message": str(e)}, indent=2))
            else:
                typer.echo(f"Error deleting zone: {e}", err=True)
            raise typer.Exit(1)


# Classic daypart presets
PRESET_ZONES = {
    "saturday-morning-cartoons": {
        "name": "Saturday Morning Cartoons",
        "start_time": "06:00",
        "end_time": "12:00",
        "day_filters": ["SAT"],
    },
    "weekday-afternoon-comedy": {
        "name": "Weekday Afternoon Comedy",
        "start_time": "15:00",
        "end_time": "18:00",
        "day_filters": ["MON", "TUE", "WED", "THU", "FRI"],
    },
    "prime-time": {
        "name": "Prime Time",
        "start_time": "19:00",
        "end_time": "22:00",
        "day_filters": None,
    },
    "late-night-horror": {
        "name": "Late Night Horror",
        "start_time": "22:00",
        "end_time": "02:00",
        "day_filters": ["FRI", "SAT"],
    },
    "overnight-classics": {
        "name": "Overnight Classics",
        "start_time": "02:00",
        "end_time": "06:00",
        "day_filters": None,
    },
}


@app.command("preset")
def add_preset_zone(
    plan: str = typer.Option(..., "--plan", help="Plan identifier: UUID or name"),
    preset: str = typer.Argument(..., help=f"Preset name: {', '.join(PRESET_ZONES.keys())}"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    test_db: bool = typer.Option(False, "--test-db", help="Use test database context"),
):
    """Create a zone from a classic TV daypart preset.

    Available presets:
      - saturday-morning-cartoons: 06:00-12:00 SAT
      - weekday-afternoon-comedy: 15:00-18:00 MON-FRI
      - prime-time: 19:00-22:00 daily
      - late-night-horror: 22:00-02:00 FRI-SAT
      - overnight-classics: 02:00-06:00 daily

    Examples:
        retrovue zone preset saturday-morning-cartoons --plan my-plan
        retrovue zone preset prime-time --plan my-plan --json
    """
    if preset not in PRESET_ZONES:
        if json_output:
            typer.echo(json.dumps({
                "status": "error",
                "code": "INVALID_PRESET",
                "message": f"Invalid preset '{preset}'. Available: {', '.join(PRESET_ZONES.keys())}"
            }, indent=2))
        else:
            typer.echo(f"Error: Invalid preset '{preset}'", err=True)
            typer.echo(f"Available presets: {', '.join(PRESET_ZONES.keys())}")
        raise typer.Exit(1)

    preset_config = PRESET_ZONES[preset]
    db_cm = _get_db_context(test_db)

    with db_cm as db:
        try:
            result = _uc_zone_add.add_zone(
                db,
                plan_identifier=plan,
                name=preset_config["name"],
                start_time=preset_config["start_time"],
                end_time=preset_config["end_time"],
                day_filters=preset_config["day_filters"],
                enabled=True,
            )

            if json_output:
                payload = {"status": "ok", "zone": result, "preset": preset}
                typer.echo(json.dumps(payload, indent=2))
            else:
                typer.echo(f"Created '{preset}' preset zone:")
                typer.echo(f"  ID: {result['id']}")
                typer.echo(f"  Name: {result['name']}")
                typer.echo(f"  Time: {result['start_time']} - {result['end_time']}")
                if result.get("day_filters"):
                    typer.echo(f"  Days: {', '.join(result['day_filters'])}")
                else:
                    typer.echo("  Days: All days")
            return
        except typer.Exit:
            raise
        except ValueError as e:
            if json_output:
                typer.echo(json.dumps({"status": "error", "code": "VALIDATION_ERROR", "message": str(e)}, indent=2))
            else:
                typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)
        except Exception as e:
            if json_output:
                typer.echo(json.dumps({"status": "error", "code": "UNKNOWN_ERROR", "message": str(e)}, indent=2))
            else:
                typer.echo(f"Error creating preset zone: {e}", err=True)
            raise typer.Exit(1)
