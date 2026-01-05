"""
Asset CLI commands for asset visibility and review workflows.

Surfaces read-only views to help operators verify ingest effects.
"""

from __future__ import annotations

import json

import typer

from ...infra.uow import session
from ...usecases import asset_attention as _uc_asset_attention
from ...usecases import asset_update as _uc_asset_update

app = typer.Typer(name="asset", help="Asset inspection and review operations")


@app.command("attention")
def list_attention(
    collection: str | None = typer.Option(None, "--collection", help="Filter by collection UUID"),
    limit: int = typer.Option(100, "--limit", help="Max rows to return"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    List assets needing attention (downgraded or not broadcastable).
    """
    with session() as db:
        rows = _uc_asset_attention.list_assets_needing_attention(
            db, collection_uuid=collection, limit=limit
        )

    if not rows:
        typer.echo("No assets need attention")
        raise typer.Exit(0)

    if json_output:
        typer.echo(
            json.dumps(
                {
                    "status": "ok",
                    "total": len(rows),
                    "assets": rows,
                },
                indent=2,
            )
        )
        raise typer.Exit(0)
    else:
        for r in rows:
            typer.echo(
                f"{r['uuid']}  {r['state']:<10} approved={r['approved_for_broadcast']}  {r['uri']}"
            )


@app.command("resolve")
def resolve_asset(
    asset_uuid: str = typer.Argument(..., help="Asset UUID to resolve"),
    approve: bool = typer.Option(False, "--approve", help="Approve asset for broadcast"),
    ready: bool = typer.Option(
        False, "--ready", help="Mark asset state=ready (allowed from enriching)"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    Resolve a single asset by approving and/or marking ready.

    When no flags are provided, prints current asset info (read-only).
    """
    with session() as db:
        # Read-only path if no mutation flags
        if not approve and not ready:
            try:
                summary = _uc_asset_update.get_asset_summary(db, asset_uuid=asset_uuid)
            except ValueError as exc:
                typer.echo(f"Error: {exc}")
                raise typer.Exit(1)

            if json_output:
                typer.echo(json.dumps({"status": "ok", "asset": summary}, indent=2))
            else:
                typer.echo(
                    f"{summary['uuid']}  {summary['state']:<10} approved={summary['approved_for_broadcast']}  {summary['uri']}"
                )
            raise typer.Exit(0)

        # Mutation path
        try:
            new_state = "ready" if ready else None
            result = _uc_asset_update.update_asset_review_status(
                db,
                asset_uuid=asset_uuid,
                approved=True if approve else None,
                state=new_state,
            )
        except ValueError as exc:
            typer.echo(f"Error: {exc}")
            raise typer.Exit(1)

    if json_output:
        typer.echo(json.dumps({"status": "ok", "asset": result}, indent=2))
    else:
        typer.echo(f"Asset {result['uuid']} updated")
