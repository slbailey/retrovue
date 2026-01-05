"""
Collection CLI commands for collection management.

Surfaces collection management capabilities including listing, configuration, and enricher attachment.
"""

from __future__ import annotations

import json

import typer

from ...adapters.registry import get_importer
from ...infra.exceptions import ValidationError
from ...infra.uow import session
from ...infra.validation import (
    validate_collection_exists,
    validate_collection_preserved,
    validate_database_consistency,
    validate_no_conflicting_operations,
    validate_no_orphaned_records,
    validate_path_mappings_preserved,
    validate_wipe_prerequisites,
)
from ._ops.collection_ingest_service import CollectionIngestService, resolve_collection_selector

app = typer.Typer(name="collection", help="Collection management operations")


@app.command("list")
def list_collections(
    source: str = typer.Option(..., "--source", help="Source ID to list collections for"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    Show Collections for a Source. For each:
    - ID (collection UUID, truncated for display)
    - Name (collection display name)
    - Sync (enabled/disabled status)
    - Ingestable (yes/no based on sync + path reachability)
    - Path Mappings (plex_path -> local_path mappings)

    Examples:
        retrovue collection list --source "My Plex Server"
        retrovue collection list --source plex-5063d926 --json
    """
    with session() as db:
        from ...content_manager.source_service import SourceService
        from ...domain.entities import Collection, PathMapping

        try:
            source_service = SourceService(db)

            # Find the source
            source_obj = source_service.get_source_by_id(source)
            if not source_obj:
                typer.echo(f"Error: Source '{source}' not found", err=True)
                raise typer.Exit(1)

            # Get collections for this source
            collections = db.query(Collection).filter(Collection.source_id == source_obj.id).all()

            if not collections:
                typer.echo(f"No collections found for source '{source_obj.name}'")
                return

            # Build collection data with path mappings
            collection_data = []
            for collection in collections:
                # Get path mappings for this collection
                path_mappings = (
                    db.query(PathMapping).filter(PathMapping.collection_id == collection.uuid).all()
                )

                # Build mapping pairs
                mapping_pairs = []
                for mapping in path_mappings:
                    mapping_pairs.append(
                        {"plex_path": mapping.plex_path, "local_path": mapping.local_path}
                    )

                # Use persisted ingestible field
                ingestable = collection.ingestible

                collection_data.append(
                    {
                        "collection_id": str(collection.uuid),
                        "external_id": collection.external_id,
                        "display_name": collection.name,
                        "source_path": collection.config.get("plex_section_ref", "")
                        if collection.config
                        else "",
                        "sync_enabled": collection.sync_enabled,
                        "ingestable": ingestable,
                        "mapping_pairs": mapping_pairs,
                    }
                )

            if json_output:
                import json

                typer.echo(json.dumps(collection_data, indent=2))
            else:
                # Display as Rich table
                from rich.console import Console
                from rich.table import Table

                console = Console()

                # Create main table
                table = Table(title=f"Collections for source '{source_obj.name}'")
                table.add_column("ID", style="cyan", width=8)
                table.add_column("Name", style="green")
                table.add_column("Sync", style="yellow")
                table.add_column("Ingestable", style="red")
                table.add_column("Path Mappings", style="white", width=50)

                for collection in collection_data:
                    sync_status = "Enabled" if collection["sync_enabled"] else "Disabled"
                    ingestable_status = "Yes" if collection["ingestable"] else "No"

                    # Format path mappings as a compact string
                    if collection["mapping_pairs"]:
                        mapping_text = "\n".join(
                            [
                                f"• {mapping['plex_path']} -> {mapping['local_path'] or '(unmapped)'}"
                                for mapping in collection["mapping_pairs"]
                            ]
                        )
                    else:
                        mapping_text = "No mappings"

                    table.add_row(
                        collection["collection_id"][:8] + "...",  # Truncate UUID for display
                        collection["display_name"],
                        sync_status,
                        ingestable_status,
                        mapping_text,
                    )

                console.print(table)

        except Exception as e:
            typer.echo(f"Error listing collections: {e}", err=True)
            raise typer.Exit(1)


@app.command("list-all")
def list_all_collections(
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    List all collections across all sources.

    Shows:
    - UUID: Collection identifier
    - Name: Collection display name
    - Source: Source name and type
    - Sync: Whether sync is enabled
    - Ingestible: Whether the collection is ingestible

    Examples:
        retrovue collection list-all
        retrovue collection list-all --json
    """
    with session() as db:
        from ...content_manager.source_service import SourceService
        from ...domain.entities import Collection, Source

        try:
            SourceService(db)

            # Get all collections across all sources
            collections = db.query(Collection).join(Source).all()

            collection_data = []
            for collection in collections:
                # Use persisted ingestible field
                ingestable = collection.ingestible

                collection_data.append(
                    {
                        "collection_id": str(collection.uuid),
                        "name": collection.name,
                        "source_name": collection.source.name,
                        "source_type": collection.source.type,
                        "sync_enabled": collection.sync_enabled,
                        "ingestible": ingestable,
                    }
                )

            if json_output:
                import json

                typer.echo(json.dumps(collection_data, indent=2))
            else:
                # Display as Rich table
                from rich.console import Console
                from rich.table import Table

                console = Console()

                # Create main table
                table = Table(title="All Collections Across All Sources")
                table.add_column("UUID", style="cyan", width=36)
                table.add_column("Name", style="green")
                table.add_column("Source", style="blue")
                table.add_column("Sync", style="yellow")
                table.add_column("Ingestible", style="red")

                for collection in collection_data:
                    sync_status = "Enabled" if collection["sync_enabled"] else "Disabled"
                    ingestible_status = "Yes" if collection["ingestible"] else "No"

                    table.add_row(
                        collection["collection_id"],  # Show full UUID
                        collection["name"],
                        f"{collection['source_name']} ({collection['source_type']})",
                        sync_status,
                        ingestible_status,
                    )

                console.print(table)

        except Exception as e:
            typer.echo(f"Error listing all collections: {e}", err=True)
            raise typer.Exit(1)


@app.command("update")
def update_collection(
    collection_id: str = typer.Argument(..., help="Collection ID, external ID, or name to update"),
    sync_enabled: bool | None = typer.Option(
        None, "--sync-enabled", help="Enable or disable collection sync"
    ),
    local_path: str | None = typer.Option(None, "--local-path", help="Override local path mapping"),
    # TODO: Add --map flag for path mapping like --map "/mnt/media/Horror=Z:\Horror"
    # map_paths: Optional[str] = typer.Option(None, "--map", help="Path mapping in format 'plex_path=local_path'"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    Enable/disable ingest for that Collection. Configure or change the local path mapping for that Collection.

    This operation is atomic (all-or-nothing) and MUST run under a unit-of-work.

    Parameters:
    - collection_id: Collection UUID, external ID, or name (case-insensitive)
    - --sync-enabled: Enable or disable collection sync
    - --local-path: Override local path mapping

    Examples:
        retrovue collection update "TV Shows" --sync-enabled true
        retrovue collection update collection-movies-1 --local-path /new/path
        retrovue collection update 2a3cd8d1-2345-6789-abcd-ef1234567890 --sync-enabled true
    """
    with session() as db:
        import os

        from ...content_manager.source_service import SourceService
        from ...domain.entities import Collection, PathMapping

        try:
            SourceService(db)

            # Find the collection by ID (try UUID first, then external_id, then name)
            import uuid

            collection = None

            # Try to find by UUID first
            try:
                if len(collection_id) == 36 and collection_id.count("-") == 4:
                    collection_uuid = uuid.UUID(collection_id)
                    collection = (
                        db.query(Collection).filter(Collection.uuid == collection_uuid).first()
                    )
            except (ValueError, TypeError):
                pass

            # If not found by UUID, try by external_id
            if not collection:
                collection = (
                    db.query(Collection).filter(Collection.external_id == collection_id).first()
                )

            # If not found by external_id, try by name (case-insensitive)
            if not collection:
                name_matches = (
                    db.query(Collection).filter(Collection.name.ilike(collection_id)).all()
                )
                if len(name_matches) == 1:
                    collection = name_matches[0]
                elif len(name_matches) > 1:
                    typer.echo(
                        f"Error: Multiple collections found with name '{collection_id}':", err=True
                    )
                    for match in name_matches:
                        typer.echo(f"  - {match.name} (UUID: {match.id})", err=True)
                    typer.echo("Use the full UUID to specify which collection to update.", err=True)
                    raise typer.Exit(1)

            if not collection:
                typer.echo(f"Error: Collection '{collection_id}' not found", err=True)
                raise typer.Exit(1)

            # Validate updates
            updates = {}
            validation_errors = []

            if sync_enabled is not None:
                updates["sync_enabled"] = sync_enabled

                # If enabling sync, check if collection is ingestible
                if sync_enabled:
                    # Check if collection is ingestible using persisted field
                    if not collection.ingestible:
                        validation_errors.append(
                            "Cannot enable sync: collection is not ingestible (no valid local path mappings)"
                        )

            if local_path is not None:
                updates["local_path"] = local_path

                # Validate the local path
                if not os.path.exists(local_path):
                    validation_errors.append(f"Local path does not exist: {local_path}")
                elif not os.path.isdir(local_path):
                    validation_errors.append(f"Local path is not a directory: {local_path}")
                elif not os.access(local_path, os.R_OK):
                    validation_errors.append(f"Local path is not readable: {local_path}")

            if validation_errors:
                typer.echo("Validation errors:", err=True)
                for error in validation_errors:
                    typer.echo(f"  - {error}", err=True)
                raise typer.Exit(1)

            if not updates:
                typer.echo("No updates provided", err=True)
                raise typer.Exit(1)

            # TODO: Implement path mapping functionality
            # When --map flag is provided:
            # 1. Parse the mapping string (e.g., "/mnt/media/Horror=Z:\Horror")
            # 2. Find PathMapping row by plex_path
            # 3. Update local_path in that PathMapping
            # 4. Validate that local_path exists and is readable
            # 5. Once at least one PathMapping.local_path is set and reachable, allow enabling the collection (row.enabled = true)

            # Apply updates in a transaction
            try:
                if "sync_enabled" in updates:
                    collection.sync_enabled = updates["sync_enabled"]

                if "local_path" in updates:
                    # Update or create path mapping
                    # Delete existing mappings
                    db.query(PathMapping).filter(
                        PathMapping.collection_id == collection.uuid
                    ).delete()

                    # Create new mapping
                    new_mapping = PathMapping(
                        collection_id=collection.uuid,
                        plex_path=f"/plex/{collection.name.lower().replace(' ', '_')}",  # Default plex path
                        local_path=updates["local_path"],
                    )
                    db.add(new_mapping)

                # Commit the transaction
                db.commit()

                if json_output:
                    import json

                    result = {
                        "collection_id": collection_id,
                        "collection_name": collection.name,
                        "updates": updates,
                        "status": "updated",
                    }
                    typer.echo(json.dumps(result, indent=2))
                else:
                    typer.echo(f"Successfully updated collection: {collection.name}")
                    for key, value in updates.items():
                        typer.echo(f"  {key}: {value}")

            except Exception as e:
                # Rollback on any error
                db.rollback()
                typer.echo(f"Error updating collection: {e}", err=True)
                raise typer.Exit(1)

        except Exception as e:
            typer.echo(f"Error updating collection: {e}", err=True)
            raise typer.Exit(1)


@app.command("attach-enricher")
def attach_enricher(
    collection_id: str = typer.Argument(..., help="Target collection"),
    enricher_id: str = typer.Argument(..., help="Enricher to attach"),
    priority: int = typer.Option(
        ..., "--priority", help="Priority order (lower numbers run first)"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    Attach an ingest-scope enricher to this Collection.

    Parameters:
    - collection_id: Target collection
    - enricher_id: Enricher to attach
    - --priority: Priority order (lower numbers run first)

    Examples:
        retrovue collection attach-enricher collection-movies-1 enricher-ffprobe-1 --priority 1
    """
    try:
        # TODO: Implement actual enricher attachment logic
        if json_output:
            import json

            result = {
                "collection_id": collection_id,
                "enricher_id": enricher_id,
                "priority": priority,
                "status": "attached",
            }
            typer.echo(json.dumps(result, indent=2))
        else:
            typer.echo(
                f"Successfully attached enricher {enricher_id} to collection {collection_id}"
            )
            typer.echo(f"  Priority: {priority}")
            typer.echo("TODO: implement actual attachment logic")

    except Exception as e:
        typer.echo(f"Error attaching enricher: {e}", err=True)
        raise typer.Exit(1)


@app.command("detach-enricher")
def detach_enricher(
    collection_id: str = typer.Argument(..., help="Target collection"),
    enricher_id: str = typer.Argument(..., help="Enricher to detach"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    Remove enricher from collection.

    Examples:
        retrovue collection detach-enricher collection-movies-1 enricher-ffprobe-1
    """
    try:
        # TODO: Implement actual enricher detachment logic
        if json_output:
            import json

            result = {
                "collection_id": collection_id,
                "enricher_id": enricher_id,
                "status": "detached",
            }
            typer.echo(json.dumps(result, indent=2))
        else:
            typer.echo(
                f"Successfully detached enricher {enricher_id} from collection {collection_id}"
            )
            typer.echo("TODO: implement actual detachment logic")

    except Exception as e:
        typer.echo(f"Error detaching enricher: {e}", err=True)
        raise typer.Exit(1)


@app.command("delete")
def delete_collection(
    collection_id: str = typer.Argument(..., help="Collection ID, external ID, or UUID to delete"),
    force: bool = typer.Option(False, "--force", help="Force deletion without confirmation"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    Delete a collection and all its associated data.

    This will delete the collection and all its path mappings. This action cannot be undone.

    Examples:
        retrovue collection delete "Movies"
        retrovue collection delete 18 --force
        retrovue collection delete 4b2b05e7-d7d2-414a-a587-3f5df9b53f44
    """
    with session() as db:
        from ...content_manager.source_service import SourceService
        from ...domain.entities import Collection, PathMapping

        try:
            source_service = SourceService(db)

            # Find the collection by ID (try UUID first, then external_id, then name)
            import uuid

            collection = None

            # Try to find by UUID first
            try:
                if len(collection_id) == 36 and collection_id.count("-") == 4:
                    collection_uuid = uuid.UUID(collection_id)
                    collection = (
                        db.query(Collection).filter(Collection.uuid == collection_uuid).first()
                    )
            except (ValueError, TypeError):
                pass

            # If not found by UUID, try by external_id
            if not collection:
                collection = (
                    db.query(Collection).filter(Collection.external_id == collection_id).first()
                )

            # If not found by external_id, try by name (case-insensitive)
            if not collection:
                name_matches = (
                    db.query(Collection).filter(Collection.name.ilike(collection_id)).all()
                )
                if len(name_matches) == 1:
                    collection = name_matches[0]
                elif len(name_matches) > 1:
                    typer.echo(
                        f"Error: Multiple collections found with name '{collection_id}':", err=True
                    )
                    for match in name_matches:
                        typer.echo(f"  - {match.name} (UUID: {match.id})", err=True)
                    typer.echo("Use the full UUID to specify which collection to delete.", err=True)
                    raise typer.Exit(1)

            if not collection:
                typer.echo(f"Error: Collection '{collection_id}' not found", err=True)
                raise typer.Exit(1)

            if not force:
                # Count related data to show user what will be deleted
                path_mappings_count = (
                    db.query(PathMapping)
                    .filter(PathMapping.collection_id == collection.uuid)
                    .count()
                )

                typer.echo(
                    f"Are you sure you want to delete collection '{collection.name}' (ID: {collection.uuid})?"
                )
                typer.echo("This will also delete:")
                typer.echo(f"  - {path_mappings_count} path mappings")
                typer.echo("This action cannot be undone.")
                confirm = typer.prompt("Type 'yes' to confirm", default="no")
                if confirm.lower() != "yes":
                    typer.echo("Deletion cancelled")
                    raise typer.Exit(0)

            # Delete the collection
            success = source_service.delete_collection(collection_id)
            if not success:
                typer.echo(f"Error: Failed to delete collection '{collection_id}'", err=True)
                raise typer.Exit(1)

            if json_output:
                import json

                result = {"deleted": True, "collection_id": collection_id, "name": collection.name}
                typer.echo(json.dumps(result, indent=2))
            else:
                typer.echo(f"Successfully deleted collection: {collection.name}")
                typer.echo(f"  ID: {collection.uuid}")
                typer.echo(f"  External ID: {collection.external_id}")

        except Exception as e:
            typer.echo(f"Error deleting collection: {e}", err=True)
            raise typer.Exit(1)


def execute_collection_wipe(db, collection, dry_run: bool, force: bool, json_output: bool):
    """
    Execute the collection wipe operation following Unit of Work pattern.

    Args:
        db: Database session
        collection: Collection to wipe
        dry_run: Whether to perform dry run
        force: Whether to skip confirmation
        json_output: Whether to output JSON

    Returns:
        Wipe result
    """
    from ...content_manager.library_service import LibraryService
    from ...content_manager.source_service import SourceService
    from ...domain.entities import (
        Asset,
        Episode,
        EpisodeAsset,
        PathMapping,
        ReviewQueue,
        Season,
        Title,
    )

    SourceService(db)
    LibraryService(db)

    # Get collection info for reporting
    collection_info = {
        "id": str(collection.uuid),
        "external_id": collection.external_id,
        "name": collection.name,
        "source_id": str(collection.source_id),
    }

    # Count what will be deleted
    stats = {
        "review_queue_entries": 0,
        "episode_assets": 0,
        "assets": 0,
        "episodes": 0,
        "seasons": 0,
        "titles": 0,
        "path_mappings": 0,
    }

    # Find assets from this collection
    # For new assets (with collection_id), use direct query
    # For existing assets (without collection_id), use path mapping approach
    assets_with_collection_id = db.query(Asset).filter(Asset.collection_id == collection.uuid).all()

    # For existing assets without collection_id, use path mapping
    path_mappings = db.query(PathMapping).filter(PathMapping.collection_id == collection.uuid).all()
    assets_from_paths = []
    for mapping in path_mappings:
        if mapping.local_path:
            escaped_path = mapping.local_path.replace("\\", "\\\\")
            matching_assets = (
                db.query(Asset)
                .filter(
                    Asset.uri.op("~")(f"^{escaped_path}"),
                    Asset.collection_id.is_(None),  # Only existing assets without collection_id
                )
                .all()
            )
            assets_from_paths.extend(matching_assets)

    # Combine both sets
    all_collection_assets = assets_with_collection_id + assets_from_paths
    collection_asset_ids = [asset.id for asset in all_collection_assets]

    # Count entities that will be deleted
    stats["assets"] = len(collection_asset_ids)

    # Collect IDs of episodes, seasons, and titles that will be affected
    collection_episode_ids = []
    collection_season_ids = []
    collection_title_ids = []

    if collection_asset_ids:
        # Count episode assets
        stats["episode_assets"] = (
            db.query(EpisodeAsset).filter(EpisodeAsset.asset_id.in_(collection_asset_ids)).count()
        )

        # Count review queue entries
        stats["review_queue_entries"] = (
            db.query(ReviewQueue).filter(ReviewQueue.asset_id.in_(collection_asset_ids)).count()
        )

        # Get episodes that have these assets
        episodes_with_assets = (
            db.query(Episode)
            .join(EpisodeAsset)
            .filter(EpisodeAsset.asset_id.in_(collection_asset_ids))
            .all()
        )
        collection_episode_ids = list(
            {episode.id: episode for episode in episodes_with_assets}.keys()
        )
        stats["episodes"] = len(collection_episode_ids)

        # Get seasons that have these episodes
        seasons_with_episodes = (
            db.query(Season)
            .join(Episode)
            .join(EpisodeAsset)
            .filter(EpisodeAsset.asset_id.in_(collection_asset_ids))
            .all()
        )
        collection_season_ids = list({season.id: season for season in seasons_with_episodes}.keys())
        stats["seasons"] = len(collection_season_ids)

        # Get titles that have these seasons
        titles_with_seasons = (
            db.query(Title)
            .join(Season)
            .join(Episode)
            .join(EpisodeAsset)
            .filter(EpisodeAsset.asset_id.in_(collection_asset_ids))
            .all()
        )
        collection_title_ids = list({title.id: title for title in titles_with_seasons}.keys())
        stats["titles"] = len(collection_title_ids)
    else:
        stats["episode_assets"] = 0
        stats["review_queue_entries"] = 0
        stats["episodes"] = 0
        stats["seasons"] = 0
        stats["titles"] = 0

    # Path mappings are preserved for re-ingest
    stats["path_mappings"] = 0

    if json_output:
        result = {"collection": collection_info, "dry_run": dry_run, "items_to_delete": stats}
        typer.echo(json.dumps(result, indent=2))
        return result

    # Show what will be deleted
    typer.echo(f"Collection wipe analysis for: {collection.name}")
    typer.echo(f"  Collection ID: {collection.uuid}")
    typer.echo(f"  External ID: {collection.external_id}")
    typer.echo("")
    typer.echo("Items that will be deleted:")
    typer.echo(f"  Review queue entries: {stats['review_queue_entries']}")
    typer.echo(f"  Episode-asset links: {stats['episode_assets']}")
    typer.echo(f"  Assets: {stats['assets']}")
    typer.echo(f"  Episodes: {stats['episodes']}")
    typer.echo(f"  Seasons: {stats['seasons']}")
    typer.echo(f"  TV Shows/Titles: {stats['titles']}")
    typer.echo(f"  Path mappings: {stats['path_mappings']}")
    typer.echo("")

    if dry_run:
        typer.echo("DRY RUN - No changes made")
        return {"collection": collection_info, "dry_run": dry_run, "items_to_delete": stats}

    # Confirmation
    if not force:
        typer.echo("⚠️  WARNING: This will permanently delete ALL data for this collection!")
        typer.echo("   This action cannot be undone.")
        typer.echo("")
        confirm = typer.prompt("Type 'DELETE' to confirm", default="")
        if confirm != "DELETE":
            typer.echo("Operation cancelled")
            return result

    # Perform the wipe
    typer.echo("Starting collection wipe...")

    # 1. Delete review queue entries
    if stats["review_queue_entries"] > 0:
        typer.echo(f"Deleting {stats['review_queue_entries']} review queue entries...")
        db.query(ReviewQueue).filter(ReviewQueue.asset_id.in_(collection_asset_ids)).delete(
            synchronize_session=False
        )

    # 2. Delete episode-asset links
    if stats["episode_assets"] > 0:
        typer.echo(f"Deleting {stats['episode_assets']} episode-asset links...")
        db.query(EpisodeAsset).filter(EpisodeAsset.asset_id.in_(collection_asset_ids)).delete(
            synchronize_session=False
        )

    # 3. Delete assets
    if stats["assets"] > 0:
        typer.echo(f"Deleting {stats['assets']} assets...")
        db.query(Asset).filter(Asset.id.in_(collection_asset_ids)).delete(synchronize_session=False)

    # 4. Delete orphaned episodes (episodes with no remaining assets)
    typer.echo("Checking for orphaned episodes...")
    orphaned_episodes = (
        db.query(Episode).outerjoin(EpisodeAsset).filter(EpisodeAsset.episode_id.is_(None)).all()
    )

    if orphaned_episodes:
        typer.echo(f"Deleting {len(orphaned_episodes)} orphaned episodes...")
        for episode in orphaned_episodes:
            db.delete(episode)

    # 5. Delete orphaned seasons (seasons with no remaining episodes)
    typer.echo("Checking for orphaned seasons...")
    orphaned_seasons = db.query(Season).outerjoin(Episode).filter(Episode.id.is_(None)).all()

    if orphaned_seasons:
        typer.echo(f"Deleting {len(orphaned_seasons)} orphaned seasons...")
        for season in orphaned_seasons:
            db.delete(season)

    # 6. Delete orphaned titles (titles with no remaining seasons)
    typer.echo("Checking for orphaned titles...")
    orphaned_titles = db.query(Title).outerjoin(Season).filter(Season.id.is_(None)).all()

    if orphaned_titles:
        typer.echo(f"Deleting {len(orphaned_titles)} orphaned titles...")
        for title in orphaned_titles:
            db.delete(title)

    # Commit all changes
    db.commit()

    typer.echo("Collection wipe completed successfully!")
    typer.echo("")
    typer.echo("The collection is now empty and ready for fresh ingest.")
    typer.echo(f'  retrovue collection ingest "{collection.name}"')

    return {"collection": collection_info, "dry_run": dry_run, "items_to_delete": stats}


@app.command("wipe")
def wipe_collection(
    collection_id: str = typer.Argument(
        ..., help="Collection ID, external ID, or name to completely wipe"
    ),
    force: bool = typer.Option(False, "--force", help="Force wipe without confirmation"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be deleted without actually deleting"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    Completely wipe a collection and ALL its associated data.

    This is the "nuclear option" that will delete:
    - All assets from the collection
    - All episodes from the collection
    - All seasons (if no episodes remain)
    - All TV shows/titles (if no seasons remain)
    - All review queue entries for assets from the collection
    - The collection itself and its path mappings

    This action cannot be undone. Use with extreme caution!

    Examples:
        retrovue collection wipe "TV Shows" --dry-run
        retrovue collection wipe 18 --force
        retrovue collection wipe "Movies" --dry-run --json
    """
    with session() as db:
        try:
            # Phase 1: Pre-flight validation
            collection = validate_collection_exists(db, collection_id)
            validate_no_conflicting_operations(db, collection_id)
            validate_wipe_prerequisites(db, collection)

            # Phase 2: Execute wipe
            result = execute_collection_wipe(db, collection, dry_run, force, json_output)

            # Phase 3: Post-operation validation (only if not dry run)
            if not dry_run:
                validate_no_orphaned_records(db)
                validate_collection_preserved(db, collection)
                validate_path_mappings_preserved(db, collection)
                validate_database_consistency(db)

            return result

        except ValidationError as e:
            typer.echo(f"Validation error: {e}", err=True)
            typer.echo(
                "Operation failed due to validation error. Database state may be inconsistent.",
                err=True,
            )
            raise typer.Exit(1)
        except Exception as e:
            typer.echo(f"Error wiping collection: {e}", err=True)
            typer.echo("Operation failed. Database state may be inconsistent.", err=True)
            raise typer.Exit(1)


@app.command("ingest")
def collection_ingest(
    collection_id: str = typer.Argument(..., help="Collection ID, external ID, or name to ingest"),
    title: str | None = typer.Option(
        None, "--title", help="Specific title to ingest (movie/show name)"
    ),
    season: int | None = typer.Option(None, "--season", help="Season number (for TV shows)"),
    episode: int | None = typer.Option(
        None, "--episode", help="Episode number (requires --season)"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be ingested without actually ingesting"
    ),
    test_db: bool = typer.Option(False, "--test-db", help="Use test database context"),
):
    """
    Ingest content from a collection.

    Modes:
    1. Full collection: retrovue collection ingest "TV Shows"
    2. Specific title: retrovue collection ingest "Movies" --title "Airplane (2012)"
    3. TV show: retrovue collection ingest "TV Shows" --title "The Big Bang Theory"
    4. Season: retrovue collection ingest "TV Shows" --title "The Big Bang Theory" --season 1
    5. Episode: retrovue collection ingest "TV Shows" --title "The Big Bang Theory" --season 1 --episode 1

    Examples:
        retrovue collection ingest "TV Shows"
        retrovue collection ingest "Movies" --title "Airplane (2012)"
        retrovue collection ingest "TV Shows" --title "The Big Bang Theory" --season 1
        retrovue collection ingest "TV Shows" --title "The Big Bang Theory" --season 1 --episode 1
    """
    # Validate episode requires season (B-4)
    if episode is not None and season is None:
        typer.echo("Error: --episode requires --season", err=True)
        raise typer.Exit(1)

    # Validate season requires title (B-3)
    if season is not None and title is None:
        typer.echo("Error: --season requires --title", err=True)
        raise typer.Exit(1)

    # Validate episode/season are non-negative integers (B-9)
    if season is not None and season < 0:
        typer.echo("Error: --season must be a non-negative integer", err=True)
        raise typer.Exit(1)

    if episode is not None and episode < 0:
        typer.echo("Error: --episode must be a non-negative integer", err=True)
        raise typer.Exit(1)

    with session() as db:
        from ...domain.entities import Source
        from ...infra.exceptions import IngestError

        try:
            # Initialize service
            service = CollectionIngestService(db)

            # Resolve collection (handled by service, but we need it to get source for importer)
            # We'll pass the selector string to service, which will resolve it
            # But we also need the resolved collection to get the importer

            # Quick resolution to get source info for importer creation
            try:
                collection = resolve_collection_selector(db, collection_id)
            except ValueError as e:
                # Collection not found or ambiguous - exit code 1 (B-1)
                typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(1)

            # Get importer for this collection
            source = db.query(Source).filter(Source.id == collection.source_id).first()
            if not source:
                typer.echo(f"Error: Source not found for collection '{collection.name}'", err=True)
                raise typer.Exit(1)

            # Build importer configuration from source config
            importer_config = {}
            if source.type == "plex":
                config = source.config or {}
                servers = config.get("servers", [])
                if not servers:
                    typer.echo(
                        f"Error: No Plex servers configured for source '{source.name}'", err=True
                    )
                    raise typer.Exit(1)

                server = servers[0]  # Use first server
                importer_config["base_url"] = server.get("base_url")
                importer_config["token"] = server.get("token")

                if not importer_config["base_url"] or not importer_config["token"]:
                    typer.echo(
                        f"Error: Plex server configuration incomplete for source '{source.name}'",
                        err=True,
                    )
                    raise typer.Exit(1)
            elif source.type == "filesystem":
                config = source.config or {}
                importer_config["source_name"] = source.name
                importer_config["root_paths"] = config.get("root_paths", [])

            # Create importer instance
            try:
                importer = get_importer(source.type, **importer_config)
            except Exception:
                typer.echo(
                    f"Error: Unsupported source type '{source.type}'. Available: filesystem, plex",
                    err=True,
                )
                raise typer.Exit(1)

            # Call service to perform ingest
            try:
                result = service.ingest_collection(
                    collection=collection,
                    importer=importer,
                    title=title,
                    season=season,
                    episode=episode,
                    dry_run=dry_run,
                    test_db=test_db,
                )

                # Format output per contract (B-5, B-6)
                if json_output:
                    import json

                    output_dict = result.to_dict()
                    typer.echo(json.dumps(output_dict, indent=2))
                else:
                    # Human-readable output (B-6)
                    if dry_run:
                        typer.echo("[DRY RUN] Would ingest:")

                    if result.scope == "collection":
                        typer.echo(f"Ingesting entire collection '{result.collection_name}'")
                    elif result.scope == "title":
                        typer.echo(
                            f"Ingesting title '{result.title}' from collection '{result.collection_name}'"
                        )
                    elif result.scope == "season":
                        typer.echo(
                            f"Ingesting season {result.season} of '{result.title}' from collection '{result.collection_name}'"
                        )
                    elif result.scope == "episode":
                        typer.echo(
                            f"Ingesting episode {result.episode} of season {result.season} of '{result.title}' from collection '{result.collection_name}'"
                        )

                    if dry_run:
                        typer.echo("No changes were applied.")
                    else:
                        typer.echo(f"Assets discovered: {result.stats.assets_discovered}")
                        typer.echo(f"Assets ingested: {result.stats.assets_ingested}")
                        typer.echo(f"Assets skipped: {result.stats.assets_skipped}")
                        typer.echo(f"Assets updated: {result.stats.assets_updated}")
                        if result.last_ingest_time:
                            typer.echo(f"Last ingest: {result.last_ingest_time}")

            except ValueError as e:
                # Validation failure - exit code 1 (B-11, B-12, B-13)
                typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(1)
            except IngestError as e:
                # Scope resolution failure - exit code 2 (B-8)
                # Use "unknown" scope since we couldn't complete ingest (no result available)
                if json_output:
                    import json

                    error_output = {
                        "status": "error",
                        "scope": "unknown",  # we couldn't complete ingest, so no scope
                        "collection_id": str(collection.uuid),
                        "collection_name": collection.name,
                        "error": str(e),
                    }
                    typer.echo(json.dumps(error_output, indent=2))
                else:
                    typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(2)
            except Exception as e:
                # Unexpected error - exit code 1
                typer.echo(f"Error ingesting collection '{collection.name}': {e}", err=True)
                raise typer.Exit(1)

        except typer.Exit:
            # Re-raise typer.Exit to preserve exit code (don't convert to exit 1)
            raise
        except Exception as e:
            typer.echo(f"Error ingesting collection: {e}", err=True)
            raise typer.Exit(1)
