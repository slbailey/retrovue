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


@app.command("reprobe")
def reprobe_asset_cmd(
    asset_uuid: str = typer.Argument(None, help="Asset UUID to reprobe"),
    collection: str = typer.Option(None, "--collection", help="Reprobe all assets in collection UUID"),
    force: bool = typer.Option(False, "--force", help="Include ready assets when reprobing a collection"),
    limit: int = typer.Option(None, "--limit", help="Max assets to reprobe (collection mode only)"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    Re-probe asset(s): reset metadata and re-run the enrichment pipeline.

    Use this when an asset's file has been replaced or corrected and you need
    fresh duration/codec metadata from the actual file on disk.

    Single asset:
        retrovue asset reprobe <uuid>

    Entire collection:
        retrovue asset reprobe --collection <uuid>
        retrovue asset reprobe --collection <uuid> --force   # include ready assets
        retrovue asset reprobe --collection <uuid> --limit 50
    """
    import json as _json
    from ...usecases import asset_reprobe as _uc_reprobe
    from ...infra.uow import session as _session

    if not asset_uuid and not collection:
        typer.echo("Error: provide either an asset UUID or --collection <uuid>", err=True)
        raise typer.Exit(1)

    if asset_uuid and collection:
        typer.echo("Error: provide either an asset UUID or --collection, not both", err=True)
        raise typer.Exit(1)

    try:
        with _session() as db:
            if asset_uuid:
                result = _uc_reprobe.reprobe_asset(db, asset_uuid=asset_uuid)

                if json_output:
                    typer.echo(_json.dumps(result, indent=2, default=str))
                else:
                    typer.echo(f"Reprobed asset {result['uuid']}")
                    typer.echo(f"  State: {result['old_state']} -> {result['new_state']}")
                    old_dur = result['old_duration_ms']
                    new_dur = result['new_duration_ms']
                    old_str = f"{old_dur/1000:.1f}s" if old_dur else "none"
                    new_str = f"{new_dur/1000:.1f}s" if new_dur else "none"
                    typer.echo(f"  Duration: {old_str} -> {new_str}")

            else:
                typer.echo(f"Reprobing collection {collection}...")
                if force:
                    typer.echo("  (--force: including ready assets)")
                if limit:
                    typer.echo(f"  (--limit {limit})")

                result = _uc_reprobe.reprobe_collection(
                    db,
                    collection_uuid=collection,
                    include_ready=force,
                    limit=limit,
                )

                if json_output:
                    typer.echo(_json.dumps(result, indent=2, default=str))
                else:
                    typer.echo(f"Collection: {result['collection_name']}")
                    typer.echo(f"  Total: {result['total']}")
                    typer.echo(f"  Succeeded: {result.get('succeeded', 0)}")
                    typer.echo(f"  Failed: {result.get('failed', 0)}")

                    for r in result.get('results', []):
                        if 'error' in r:
                            typer.echo(f"  ✗ {r['uuid']}: {r['error']}")
                        else:
                            old_dur = r.get('old_duration_ms')
                            new_dur = r.get('new_duration_ms')
                            old_str = f"{old_dur/1000:.1f}s" if old_dur else "none"
                            new_str = f"{new_dur/1000:.1f}s" if new_dur else "none"
                            typer.echo(f"  ✓ {r['uuid']}: {r['old_state']}->{r['new_state']}  duration {old_str}->{new_str}")

    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
