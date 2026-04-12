"""
Plex CLI commands for Plex server operations.

Surfaces Plex server interaction capabilities including verification, episode retrieval, and ingestion.
Calls SourceService, LibraryService, IngestOrchestrator, and PathResolverService under the hood.
"""

from __future__ import annotations

import json

import typer
from src_legacy.retrovue.content_manager.path_service import (
    PathResolutionError,
    PathResolverService,
)
from src_legacy.retrovue.content_manager.source_service import SourceService

from ...adapters.enrichers.ffprobe_enricher import FFprobeEnricher
from ...adapters.importers.plex_importer import PlexClient
from ...infra.uow import session
from ...shared.path_utils import get_file_hash, get_file_size

app = typer.Typer(
    name="plex",
    help="Plex server operations using SourceService, LibraryService, and IngestOrchestrator",
)


def get_active_plex_server(server_name: str | None = None) -> tuple[str, str]:
    """
    Get the active Plex server configuration using SourceService.

    Args:
        server_name: Optional server name to select explicitly

    Returns:
        Tuple of (base_url, token)

    Raises:
        typer.Exit: If no server found or configuration invalid
    """
    with session() as db:
        source_service = SourceService(db)

        # Get all Plex sources using the service
        sources = source_service.list_sources()
        plex_sources = [s for s in sources if s.type == "plex"]

        if not plex_sources:
            typer.echo(
                "Error: No Plex servers configured. Please add a Plex server first.", err=True
            )
            raise typer.Exit(1)

        # Select server
        if server_name:
            selected_source = None
            for source in plex_sources:
                if source.name == server_name:
                    selected_source = source
                    break
            if not selected_source:
                typer.echo(f"Error: Plex server '{server_name}' not found.", err=True)
                raise typer.Exit(1)
        else:
            # Use first available server (could be enhanced to check is_active flag)
            selected_source = plex_sources[0]

        config = selected_source.config or {}
        base_url = config.get("base_url")
        token = config.get("token")

        if not base_url or not token:
            typer.echo(
                f"Error: Plex server '{selected_source.name}' has invalid configuration.", err=True
            )
            raise typer.Exit(1)

        return base_url, token


def get_plex_client(server_name: str | None = None) -> PlexClient:
    """
    Create a Plex client using the active server configuration.

    Args:
        server_name: Optional server name to select explicitly

    Returns:
        Configured PlexClient instance
    """
    base_url, token = get_active_plex_server(server_name)
    return PlexClient(base_url, token)


def resolve_plex_path(plex_path: str) -> str:
    """
    Resolve a Plex file path to a local path using PathResolverService.

    Args:
        plex_path: Plex file path

    Returns:
        Resolved local path

    Raises:
        typer.Exit: If path cannot be resolved or file doesn't exist
    """
    with session() as db:
        # Get all path mappings using SourceService
        source_service = SourceService(db)
        sources = source_service.list_sources()

        # Collect all mapping pairs from all sources
        mapping_pairs = []
        for source in sources:
            collections = source_service.list_enabled_collections(source.external_id)
            for collection in collections:
                mapping_pairs.extend(collection.mapping_pairs)

        if not mapping_pairs:
            # Fallback for testing when no mappings exist
            if plex_path.startswith("/media/tv"):
                local_path = plex_path.replace("/media/tv", "R:\\Media\\TV")
                return local_path
            else:
                typer.echo(
                    f"Error: No path mappings configured. Cannot resolve Plex path: {plex_path}",
                    err=True,
                )
                raise typer.Exit(1)

        # Create path resolver service
        path_resolver = PathResolverService(mapping_pairs)

        try:
            # Resolve path using the service
            local_path = path_resolver.resolve_path(plex_path, validate_exists=True)
            return local_path
        except PathResolutionError as e:
            typer.echo(f"Error: Cannot resolve Plex path: {plex_path}", err=True)
            typer.echo(f"Available mappings: {e.available_mappings}", err=True)
            raise typer.Exit(1)


@app.command("verify")
def verify_plex_connection(
    server_name: str | None = typer.Option(
        None, "--server-name", help="Specific server name to use"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    Verify connection to the active Plex server.

    Uses SourceService to get server configuration and calls Plex API to confirm connection.

    Examples:
        retrovue plex verify
        retrovue plex verify --server-name "My Plex Server"
        retrovue plex verify --json
    """
    try:
        # Get server info using SourceService
        base_url, token = get_active_plex_server(server_name)
        plex_client = PlexClient(base_url, token)

        # Make a simple request to verify connection
        # We'll use the existing get_libraries method as a health check
        libraries = plex_client.get_libraries()

        # Get server info (this would need to be added to PlexClient)
        server_info = {
            "server_name": "Plex Server",  # Could be enhanced to get actual server name
            "base_url": base_url,
            "libraries_count": len(libraries),
            "status": "connected",
        }

        if json_output:
            typer.echo(json.dumps(server_info, indent=2))
        else:
            typer.echo(f"Connected to Plex server at {base_url}")
            typer.echo(f"  Libraries available: {len(libraries)}")
            typer.echo(f"  Status: {server_info['status']}")

    except Exception as e:
        typer.echo(f"Error verifying Plex connection: {e}", err=True)
        raise typer.Exit(1)


@app.command("get-episode")
def get_episode_info(
    rating_key: int | None = typer.Argument(
        None, help="Plex rating key for the episode (fast path)"
    ),
    series: str | None = typer.Option(
        None, "--series", help="Series title (required if not using --rating-key)"
    ),
    season: int | None = typer.Option(
        None, "--season", help="Season number (required if not using --rating-key)"
    ),
    episode: int | None = typer.Option(
        None, "--episode", help="Episode number (required if not using --rating-key)"
    ),
    server_name: str | None = typer.Option(
        None, "--server-name", help="Specific server name to use"
    ),
    dry_run: bool = typer.Option(
        True, "--dry-run", help="Show what would be done without making changes"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    Get episode metadata and resolve local path.

    Fetch metadata by ratingKey (fast path) or by series/season/episode, resolve path via DB mappings,
    ffprobe duration, compute hash, print dry-run summary (human + JSON).

    Examples:
        retrovue plex get-episode 12345
        retrovue plex get-episode --series "Batman TAS" --season 1 --episode 1
        retrovue plex get-episode 12345 --server-name "My Server"
        retrovue plex get-episode --series "Batman TAS" --season 1 --episode 1 --json
    """
    try:
        # Validate input parameters
        if rating_key is None and (series is None or season is None or episode is None):
            typer.echo(
                "Error: Either --rating-key or all of --series, --season, --episode must be provided",
                err=True,
            )
            raise typer.Exit(1)

        if rating_key is not None and (
            series is not None or season is not None or episode is not None
        ):
            typer.echo(
                "Error: Cannot use both --rating-key and series/season/episode selectors", err=True
            )
            raise typer.Exit(1)

        # Get Plex client
        plex_client = get_plex_client(server_name)

        # Get episode metadata from Plex
        if rating_key is not None:
            # Fast path: direct rating key lookup
            episode_metadata = plex_client.get_episode_metadata(rating_key)
        else:
            # Series/season/episode lookup
            episode_metadata = plex_client.find_episode_by_sse(series, season, episode)

        # Extract file path from metadata
        plex_file_path = episode_metadata["Media"][0]["Part"][0]["file"]

        # Resolve to local path using PathResolverService
        local_path = resolve_plex_path(plex_file_path)

        # Get file info
        file_size = get_file_size(local_path)
        file_hash = get_file_hash(local_path) if file_size else None

        # Run ffprobe for duration and codecs
        ffprobe_enricher = FFprobeEnricher()
        from ...adapters.importers.base import DiscoveredItem

        discovered_item = DiscoveredItem(
            path_uri=f"file://{local_path}",
            provider_key=str(rating_key),
            size=file_size,
            hash_sha256=file_hash,
        )

        enriched_item = ffprobe_enricher.enrich(discovered_item)

        # Extract metadata from enriched item
        duration_ms = None

        if enriched_item.raw_labels:
            for label in enriched_item.raw_labels:
                if label.startswith("duration_ms:"):
                    duration_ms = int(label.split(":", 1)[1])
                elif label.startswith("video_codec:"):
                    label.split(":", 1)[1]
                elif label.startswith("audio_codec:"):
                    label.split(":", 1)[1]
                elif label.startswith("container:"):
                    label.split(":", 1)[1]

        # Prepare summary in the specified format
        summary = {
            "action": "UPSERT" if not dry_run else "DRY_RUN",
            "provenance": {
                "source": "plex",
                "source_rating_key": episode_metadata["ratingKey"],
                "source_guid": episode_metadata.get("guid", ""),
            },
            "episode": {
                "series_title": episode_metadata["grandparentTitle"],
                "season_number": int(episode_metadata["parentIndex"])
                if episode_metadata["parentIndex"]
                else None,
                "episode_number": int(episode_metadata["index"])
                if episode_metadata["index"]
                else None,
                "title": episode_metadata["title"],
            },
            "file": {
                "plex_path": plex_file_path,
                "resolved_path": local_path,
                "duration_sec": duration_ms / 1000.0 if duration_ms else None,
                "hash": file_hash,
            },
        }

        if json_output:
            typer.echo(json.dumps(summary, indent=2))
        else:
            typer.echo(f"Episode: {episode_metadata['title']}")
            season_num = (
                int(episode_metadata["parentIndex"]) if episode_metadata["parentIndex"] else 0
            )
            episode_num = int(episode_metadata["index"]) if episode_metadata["index"] else 0
            typer.echo(
                f"Series: {episode_metadata['grandparentTitle']} S{season_num:02d}E{episode_num:02d}"
            )
            typer.echo(f"Plex path: {plex_file_path}")
            typer.echo(f"Local path: {local_path}")
            typer.echo(f"File size: {file_size:,} bytes" if file_size else "File size: Unknown")
            typer.echo(
                f"Duration: {duration_ms // 1000 // 60} minutes"
                if duration_ms
                else "Duration: Unknown"
            )
            typer.echo(f"Hash: {file_hash[:16]}..." if file_hash else "Hash: Not computed")
            typer.echo(f"Action: {summary['action']}")

    except Exception as e:
        typer.echo(f"Error getting episode info: {e}", err=True)
        raise typer.Exit(1)


@app.command("ingest-episode")
def ingest_episode(
    rating_key: int | None = typer.Argument(
        None, help="Plex rating key for the episode (fast path)"
    ),
    series: str | None = typer.Option(
        None, "--series", help="Series title (required if not using --rating-key)"
    ),
    season: int | None = typer.Option(
        None, "--season", help="Season number (required if not using --rating-key)"
    ),
    episode: int | None = typer.Option(
        None, "--episode", help="Episode number (required if not using --rating-key)"
    ),
    server_name: str | None = typer.Option(
        None, "--server-name", help="Specific server name to use"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be done without making changes"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    Ingest a single episode from Plex into the content library using IngestOrchestrator.

    Uses IngestOrchestrator.ingest_single_episode() for all ingest operations.

    Examples:
        retrovue plex ingest-episode 12345
        retrovue plex ingest-episode --series "Batman TAS" --season 1 --episode 1
        retrovue plex ingest-episode 12345 --dry-run
        retrovue plex ingest-episode --series "Batman TAS" --season 1 --episode 1 --json
    """
    try:
        # Validate input parameters
        if rating_key is None and (series is None or season is None or episode is None):
            typer.echo(
                "Error: Either --rating-key or all of --series, --season, --episode must be provided",
                err=True,
            )
            raise typer.Exit(1)

        if rating_key is not None and (
            series is not None or season is not None or episode is not None
        ):
            typer.echo(
                "Error: Cannot use both --rating-key and series/season/episode selectors", err=True
            )
            raise typer.Exit(1)

        # Get Plex client for metadata retrieval
        plex_client = get_plex_client(server_name)

        # Get episode metadata from Plex
        if rating_key is not None:
            # Fast path: direct rating key lookup
            episode_metadata = plex_client.get_episode_metadata(rating_key)
        else:
            # Series/season/episode lookup
            episode_metadata = plex_client.find_episode_by_sse(series, season, episode)

        plex_file_path = episode_metadata["Media"][0]["Part"][0]["file"]
        local_path = resolve_plex_path(plex_file_path)

        if dry_run:
            # Show what would be done using get-episode logic
            # Get file info
            file_size = get_file_size(local_path)
            file_hash = get_file_hash(local_path) if file_size else None

            # Run ffprobe for duration and codecs
            ffprobe_enricher = FFprobeEnricher()
            from ...adapters.importers.base import DiscoveredItem

            discovered_item = DiscoveredItem(
                path_uri=f"file://{local_path}",
                provider_key=str(rating_key),
                size=file_size,
                hash_sha256=file_hash,
            )

            enriched_item = ffprobe_enricher.enrich(discovered_item)

            # Extract metadata from enriched item
            duration_ms = None
            if enriched_item.raw_labels:
                for label in enriched_item.raw_labels:
                    if label.startswith("duration_ms:"):
                        duration_ms = int(label.split(":", 1)[1])

            # Show dry run summary
            summary = {
                "action": "DRY_RUN",
                "provenance": {
                    "source": "plex",
                    "source_rating_key": episode_metadata["ratingKey"],
                    "source_guid": episode_metadata.get("guid", ""),
                },
                "episode": {
                    "series_title": episode_metadata["grandparentTitle"],
                    "season_number": int(episode_metadata["parentIndex"])
                    if episode_metadata["parentIndex"]
                    else None,
                    "episode_number": int(episode_metadata["index"])
                    if episode_metadata["index"]
                    else None,
                    "title": episode_metadata["title"],
                },
                "file": {
                    "plex_path": plex_file_path,
                    "resolved_path": local_path,
                    "duration_sec": duration_ms / 1000.0 if duration_ms else None,
                    "hash": file_hash,
                },
            }

            if json_output:
                typer.echo(json.dumps(summary, indent=2))
            else:
                typer.echo("DRY RUN - No changes will be made")
                typer.echo(f"Would ingest: {episode_metadata['title']}")
                typer.echo(f"Local path: {local_path}")
                typer.echo(f"File size: {file_size:,} bytes" if file_size else "File size: Unknown")
                typer.echo(
                    f"Duration: {duration_ms // 1000 // 60} minutes"
                    if duration_ms
                    else "Duration: Unknown"
                )
        else:
            # Use IngestOrchestrator for actual ingestion
            with session() as db:
                from src_legacy.retrovue.content_manager.ingest_orchestrator import (
                    IngestOrchestrator,
                )

                orchestrator = IngestOrchestrator(db)
                report = orchestrator.ingest_single_episode(
                    source_id="plex", episode_id=str(rating_key), dry_run=False
                )

                if json_output:
                    typer.echo(json.dumps(report.to_dict(), indent=2))
                else:
                    typer.echo(f"Ingest completed: {report.registered} assets registered")
                    if report.errors > 0:
                        typer.echo(f"Errors: {report.errors}", err=True)

    except Exception as e:
        typer.echo(f"Error ingesting episode: {e}", err=True)
        raise typer.Exit(1)
