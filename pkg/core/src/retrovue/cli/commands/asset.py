"""
Asset CLI commands for asset visibility and review workflows.

Surfaces read-only views to help operators verify ingest effects.
"""

from __future__ import annotations

import json
import uuid as _uuid_mod

import typer

from ...domain.entities import Asset, AssetTag
from ...domain.tag_normalization import normalize_tag_set
from ...infra.uow import session
from ...usecases import asset_attention as _uc_asset_attention
from ...usecases import asset_update as _uc_asset_update

app = typer.Typer(name="asset", help="Asset inspection and review operations")


def resolve_asset_selector(db, asset_id: str) -> Asset:
    """Resolve an asset by UUID string. Raises typer.Exit(1) if not found."""
    try:
        uid = _uuid_mod.UUID(asset_id)
    except Exception:
        typer.echo(f"Error: invalid asset UUID: {asset_id!r}", err=True)
        raise typer.Exit(1)
    asset = db.get(Asset, uid)
    if asset is None:
        typer.echo(f"Error: asset not found: {asset_id}", err=True)
        raise typer.Exit(1)
    return asset


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



@app.command("update")
def update_asset(
    asset_id: str = typer.Argument(..., help="Asset UUID to update"),
    tags: str | None = typer.Option(
        None,
        "--tags",
        help="Comma-separated tag set to assign (REPLACE semantics). "
             "Tags are normalized: stripped, lowercased, deduplicated.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without writing"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    Update asset attributes.

    Currently supports: --tags (REPLACE semantics per AssetTaggingContract.md).

    Examples:
        retrovue asset update <uuid> --tags "hbo,1982"
        retrovue asset update <uuid> --tags "classic,noir" --dry-run
        retrovue asset update <uuid> --tags "drama" --json
    """
    if tags is None:
        typer.echo("Error: at least one update flag is required (e.g. --tags)", err=True)
        raise typer.Exit(1)

    try:
        with session() as db:
            asset = resolve_asset_selector(db, asset_id)

            # D-4: soft-deleted assets reject tagging
            if asset.is_deleted:
                typer.echo(
                    f"Error: asset {asset_id} is deleted; tagging is not permitted.",
                    err=True,
                )
                raise typer.Exit(1)

            # Compute old tag set
            existing_tags = db.query(AssetTag).filter_by(asset_uuid=asset.uuid).all()
            old_tag_set = sorted(t.tag for t in existing_tags)

            # B-1/B-2: normalize and deduplicate
            raw_tags = [t.strip() for t in tags.split(",")]
            new_tag_set = normalize_tag_set(raw_tags)

            changed = old_tag_set != new_tag_set

            if not dry_run and changed:
                # D-3: single Unit of Work — delete then insert
                db.query(AssetTag).filter_by(asset_uuid=asset.uuid).delete()
                for tag_val in new_tag_set:
                    db.add(AssetTag(asset_uuid=asset.uuid, tag=tag_val, source="operator"))
                db.commit()

            status = "changed" if changed else "no_change"

            if json_output:
                typer.echo(
                    json.dumps(
                        {
                            "status": status,
                            "asset_uuid": str(asset.uuid),
                            "dry_run": dry_run,
                            "changes": {
                                "tags": {
                                    "old": old_tag_set,
                                    "new": new_tag_set,
                                }
                            },
                        },
                        indent=2,
                    )
                )
            else:
                typer.echo(f"Asset:  {asset.uuid}")
                typer.echo(f"Old tags: {old_tag_set}")
                typer.echo(f"New tags: {new_tag_set}")
                if dry_run:
                    typer.echo("[dry-run: no changes written]")
                elif changed:
                    typer.echo("Tags updated.")
                else:
                    typer.echo("No change (tag set identical).")

    except typer.Exit:
        raise
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
