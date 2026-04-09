"""
Pool CLI commands for programming pool management.

Thin presentation layer: parse args + IO only, delegate to workflow.
INV-CLI-NO-BUSINESS-LOGIC-001, INV-POOL-CLI-DELEGATES-001.
"""

from __future__ import annotations

import json
from typing import Any

import typer
import yaml

from ...infra.uow import session
from ...workflows.pool_management import (
    assign_pool as wf_assign_pool,
)
from ...workflows.pool_management import (
    create_pool as wf_create_pool,
)
from ...workflows.pool_management import (
    inspect_pool as wf_inspect_pool,
)
from ...workflows.pool_management import (
    list_pools as wf_list_pools,
)

app = typer.Typer(name="pool", help="Programming pool management operations")


def _parse_match_criteria(raw: str) -> dict[str, Any]:
    """Parse match criteria from JSON or YAML string."""
    # Try JSON first
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
        raise typer.BadParameter("Match criteria must be a JSON/YAML mapping")
    except json.JSONDecodeError:
        pass
    # Try YAML
    try:
        parsed = yaml.safe_load(raw)
        if isinstance(parsed, dict):
            return parsed
        raise typer.BadParameter("Match criteria must be a JSON/YAML mapping")
    except yaml.YAMLError:
        pass
    raise typer.BadParameter("Match criteria must be valid JSON or YAML")


@app.command("create")
def create(
    name: str = typer.Argument(..., help="Pool name"),
    match: str = typer.Option(..., "--match", help="Match criteria as JSON or YAML string"),
    description: str | None = typer.Option(None, "--description", help="Pool description"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """Create a named programming pool."""
    try:
        match_criteria = _parse_match_criteria(match)
    except typer.BadParameter as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    try:
        with session() as db:
            pool = wf_create_pool(db, name=name, match_criteria=match_criteria, description=description)

            if json_output:
                typer.echo(json.dumps({
                    "status": "ok",
                    "pool": {
                        "id": str(pool.id),
                        "name": pool.name,
                        "description": pool.description,
                        "match_criteria": pool.match_criteria,
                        "created_at": str(pool.created_at) if pool.created_at else None,
                    },
                }, default=str))
            else:
                typer.echo(f"Pool '{pool.name}' created.")
                typer.echo(f"  Match: {json.dumps(pool.match_criteria)}")
                if pool.description:
                    typer.echo(f"  Description: {pool.description}")
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command("list")
def list_cmd(
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """List all programming pools."""
    try:
        with session() as db:
            pools = wf_list_pools(db)

            if json_output:
                typer.echo(json.dumps({
                    "status": "ok",
                    "total": len(pools),
                    "pools": [
                        {
                            "id": str(p.id),
                            "name": p.name,
                            "description": p.description,
                            "match_criteria": p.match_criteria,
                            "created_at": str(p.created_at) if p.created_at else None,
                        }
                        for p in pools
                    ],
                }, default=str))
            else:
                if not pools:
                    typer.echo("No pools configured")
                else:
                    for p in pools:
                        typer.echo(f"  {p.name}")
                        typer.echo(f"    Match: {json.dumps(p.match_criteria)}")
                        if p.description:
                            typer.echo(f"    Description: {p.description}")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command("inspect")
def inspect(
    name: str = typer.Argument(..., help="Pool name to inspect"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """Inspect a pool: resolve match criteria and show diagnostics."""
    try:
        from ...runtime.catalog_resolver import CatalogAssetResolver

        with session() as db:
            resolver = CatalogAssetResolver(db)
            result = wf_inspect_pool(db, resolver, name)

            if json_output:
                typer.echo(json.dumps({
                    "status": "ok",
                    "pool_name": result.pool_name,
                    "match_criteria": result.match_criteria,
                    "matched_count": result.matched_count,
                    "matched_asset_ids": result.matched_asset_ids,
                    "diagnostics": {
                        "total_considered": result.diagnostics.total_considered,
                        "excluded_by_type": result.diagnostics.excluded_by_type,
                        "excluded_by_tags": result.diagnostics.excluded_by_tags,
                        "excluded_by_rating": result.diagnostics.excluded_by_rating,
                        "excluded_by_duration": result.diagnostics.excluded_by_duration,
                        "excluded_by_editorial": result.diagnostics.excluded_by_editorial,
                        "matched": result.diagnostics.matched,
                    },
                }, default=str))
            else:
                typer.echo(f"Pool: {result.pool_name}")
                typer.echo(f"  Match: {json.dumps(result.match_criteria)}")
                typer.echo(f"  Matched assets: {result.matched_count}")
                if result.matched_asset_ids:
                    for aid in result.matched_asset_ids:
                        typer.echo(f"    - {aid}")
                typer.echo("  Diagnostics:")
                typer.echo(f"    Total considered: {result.diagnostics.total_considered}")
                typer.echo(f"    Excluded by type: {result.diagnostics.excluded_by_type}")
                typer.echo(f"    Excluded by tags: {result.diagnostics.excluded_by_tags}")
                typer.echo(f"    Excluded by rating: {result.diagnostics.excluded_by_rating}")
                typer.echo(f"    Excluded by duration: {result.diagnostics.excluded_by_duration}")
                typer.echo(f"    Excluded by editorial: {result.diagnostics.excluded_by_editorial}")
                typer.echo(f"    Matched: {result.diagnostics.matched}")
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command("assign")
def assign(
    pool_name: str = typer.Argument(..., help="Pool name"),
    channel: str = typer.Argument(..., help="Channel slug"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """Assign a pool to a channel."""
    try:
        with session() as db:
            assignment = wf_assign_pool(db, pool_name=pool_name, channel_name=channel)

            if json_output:
                typer.echo(json.dumps({
                    "status": "ok",
                    "assignment": {
                        "id": str(assignment.id),
                        "pool_id": str(assignment.pool_id),
                        "channel_id": str(assignment.channel_id),
                        "created_at": str(assignment.created_at) if assignment.created_at else None,
                    },
                }, default=str))
            else:
                typer.echo(f"Pool '{pool_name}' assigned to channel '{channel}'.")
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
