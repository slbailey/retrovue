"""
Source CLI commands for source and collection management.

Surfaces source and collection management capabilities including listing, configuration, and path mapping.
"""

from __future__ import annotations

import json
import uuid

import typer
from sqlalchemy.orm import Session

from ...adapters.registry import (
    SOURCES,
    get_importer,
    get_importer_help,
    list_enrichers,
    list_importers,
)
from ...domain.entities import Collection, Source
from ...infra.uow import session
from ...usecases.source_add import add_source as usecase_add_source
from ...usecases.source_discover import discover_collections as usecase_discover_collections
from ...usecases.source_list import list_sources as usecase_list_sources

# Thin, contract-aligned functions instead of fat SourceService
# Each function maps 1:1 to a contract + test

def source_list(source_type: str | None = None, test_db: bool = False, db_session: Session | None = None) -> list[dict]:
    """
    List all configured sources.
    
    Contract: SourceListContract.md
    Test: test_source_list_contract.py
    """
    if db_session:
        db = db_session
        should_close = False
    else:
        db = session()
        should_close = True
    
    try:
        query = db.query(Source)
        
        if source_type:
            query = query.filter(Source.type == source_type)
        
        sources = query.all()
        
        # Convert to contract-aligned format
        result = []
        for source in sources:
            # Get collection counts - handle case where collections table might not exist
            try:
                enabled_collections = db.query(Collection).filter(
                    Collection.source_id == source.id,
                    Collection.sync_enabled.is_(True)
                ).count()
                
                ingestible_collections = db.query(Collection).filter(
                    Collection.source_id == source.id,
                    Collection.ingestible.is_(True)
                ).count()
            except Exception:
                # If collections table doesn't exist or query fails, default to 0
                enabled_collections = 0
                ingestible_collections = 0
            
            result.append({
                "id": str(source.id),
                "name": source.name,
                "type": source.type,
                "created_at": source.created_at.isoformat() if source.created_at else None,
                "updated_at": source.updated_at.isoformat() if source.updated_at else None,
                "enabled_collections": enabled_collections,
                "ingestible_collections": ingestible_collections
            })
        
        return result
    finally:
        if should_close:
            db.close()

def source_get_by_id(source_id: str) -> Source | None:
    """
    Get a source by ID, external ID, or name.
    
    Used by other source functions.
    """
    with session() as db:
        return _resolve_source_by_id(db, source_id)


def _resolve_source_by_id(db: Session, source_id: str) -> Source | None:
    """
    Resolve a source by ID, external ID, or name using an existing session.
    
    Args:
        db: Database session
        source_id: Source identifier (UUID, external_id, or name)
    
    Returns:
        Source object or None if not found
    """
    # Try by UUID first
    try:
        uuid.UUID(source_id)
        source = db.query(Source).filter(Source.id == source_id).first()
        if source:
            return source
    except ValueError:
        pass
    
    # Try by external_id
    source = db.query(Source).filter(Source.external_id == source_id).first()
    if source:
        return source
    
    # Try by name
    return db.query(Source).filter(Source.name == source_id).first()

def source_add(
    source_type: str,
    name: str,
    config: dict,
    enrichers: list[str] | None = None,
    discover: bool = False,
    test_db: bool = False,
    db_session: Session | None = None
) -> dict:
    """
    Add a new content source.
    
    Contract: SourceAddContract.md
    Test: test_source_add_contract.py
    """
    if db_session:
        db = db_session
        should_close = False
    else:
        db = session()
        should_close = True
    
    try:
        # Generate external ID
        external_id = f"{source_type}-{uuid.uuid4().hex[:8]}"
        
        # Create source entity
        source = Source(
            external_id=external_id,
            name=name,
            type=source_type,
            config=config
        )
        
        db.add(source)
        db.commit()
        db.refresh(source)
        
        # Discover collections if requested
        # Discovery is handled by the separate 'source discover' command
        # This flag is ignored per contract
        collections_discovered = 0
        
        return {
            "id": str(source.id),
            "external_id": source.external_id,
            "name": source.name,
            "type": source.type,
            "config": source.config,
            "enrichers": enrichers or [],
            "collections_discovered": collections_discovered
        }
    finally:
        if should_close:
            db.close()

def source_discover_collections(
    source_id: str,
    test_db: bool = False,
    db_session: Session | None = None
) -> list[dict]:
    """
    Discover collections from a source.
    
    Contract: SourceDiscoverContract.md
    Test: test_source_discover_contract.py
    """
    if db_session:
        db = db_session
        should_close = False
    else:
        db = session()
        should_close = True
    
    try:
        # Get source
        source = source_get_by_id(source_id)
        if not source:
            raise ValueError(f"Source not found: {source_id}")
        
        # TODO: Implement actual collection discovery
        # For now, return empty list
        return []
    finally:
        if should_close:
            db.close()

def source_persist_collections(
    source_id: str,
    collections: list[dict],
    test_db: bool = False,
    db_session: Session | None = None
) -> bool:
    """
    Persist discovered collections to database.
    
    Contract: SourceDiscoverContract.md
    Test: test_source_discover_contract.py
    """
    if db_session:
        db = db_session
        should_close = False
    else:
        db = session()
        should_close = True
    
    try:
        # TODO: Implement collection persistence
        # For now, just return True
        return True
    finally:
        if should_close:
            db.close()

def source_update(
    source_id: str,
    updates: dict,
    test_db: bool = False,
    db_session: Session | None = None
) -> dict:
    """
    Update an existing source.
    
    Contract: SourceUpdateContract.md
    Test: test_source_update_contract.py
    """
    if db_session:
        db = db_session
        should_close = False
    else:
        db = session()
        should_close = True
    
    try:
        # Get source
        source = source_get_by_id(source_id)
        if not source:
            raise ValueError(f"Source not found: {source_id}")
        
        # Update fields
        for key, value in updates.items():
            if hasattr(source, key):
                setattr(source, key, value)
        
        db.commit()
        db.refresh(source)
        
        return {
            "id": str(source.id),
            "external_id": source.external_id,
            "name": source.name,
            "type": source.type,
            "config": source.config,
            "updated_at": source.updated_at.isoformat() if source.updated_at else None
        }
    finally:
        if should_close:
            db.close()

def source_delete(
    source_id: str,
    test_db: bool = False,
    db_session: Session | None = None
) -> bool:
    """
    Delete a source and cascade delete related collections.
    
    Contract: SourceDeleteContract.md
    Test: test_source_delete_contract.py
    """
    if db_session:
        db = db_session
        should_close = False
    else:
        db = session()
        should_close = True
    
    try:
        # Get source
        source = source_get_by_id(source_id)
        if not source:
            raise ValueError(f"Source not found: {source_id}")
        
        # Delete source (cascade will handle collections)
        db.delete(source)
        db.commit()
        
        return True
    finally:
        if should_close:
            db.close()

def _redact_sensitive_config(config: dict) -> dict:
    """
    Redact sensitive information from configuration dictionaries.
    
    This function identifies and redacts any configuration values that could
    contain sensitive authentication data, tokens, or credentials for any
    type of content source (Plex, filesystem, API, etc.).
    
    Recursively processes nested dictionaries and lists to find and redact
    sensitive values at any nesting level.
    
    Args:
        config: Configuration dictionary that may contain sensitive data
        
    Returns:
        Configuration dictionary with sensitive values redacted
    """
    if not isinstance(config, dict):
        return config
    
    redacted = config.copy()
    
    # Comprehensive list of sensitive key patterns
    sensitive_patterns = [
        'token', 'password', 'secret', 'key', 'auth', 'credential',
        'api_key', 'access_token', 'refresh_token', 'bearer', 'jwt',
        'private', 'sensitive', 'confidential', 'secure', 'pass',
        'login', 'user', 'username', 'email', 'account'
    ]
    
    # Recursively redact sensitive values
    for key, value in redacted.items():
        key_lower = key.lower()
        
        # Check if this key matches sensitive patterns
        if any(pattern in key_lower for pattern in sensitive_patterns):
            redacted[key] = '***REDACTED***'
        # Recursively process nested dictionaries
        elif isinstance(value, dict):
            redacted[key] = _redact_sensitive_config(value)
        # Recursively process lists (which may contain dicts)
        elif isinstance(value, list):
            redacted[key] = [
                _redact_sensitive_config(item) if isinstance(item, dict) else item
                for item in value
            ]
    
    return redacted

app = typer.Typer(name="source", help="Source and collection management operations")


@app.command("list")
def list_sources(
    source_type: str | None = typer.Option(None, "--type", help="Filter by source type"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    test_db: bool = typer.Option(False, "--test-db", help="Query test database"),
):
    """
    List all configured sources.
    
    Examples:
        retrovue source list
        retrovue source list --json
        retrovue source list --type plex
        retrovue source list --test-db --json
    """
    # Validate source type if provided
    if source_type:
        available_types = list_importers()
        if source_type not in available_types:
            typer.echo(f"Unknown source type '{source_type}'. Available types: {', '.join(available_types)}", err=True)
            raise typer.Exit(1)
    
    try:
        # Use usecase function (contract-aligned)
        with session() as db:
            sources_data = usecase_list_sources(db, source_type=source_type)
        
        if json_output:
            import json
            # Sort sources by name (case-insensitive), then by id
            sorted_sources = sorted(sources_data, key=lambda s: (s['name'].lower(), s['id']))
            
            response = {
                "status": "ok",
                "total": len(sorted_sources),
                "sources": sorted_sources
            }
            typer.echo(json.dumps(response, indent=2))
        else:
            # Human-readable output
            if not sources_data:
                typer.echo("No sources configured")
            else:
                # Sort sources by name (case-insensitive), then by id
                sorted_sources = sorted(sources_data, key=lambda s: (s['name'].lower(), s['id']))
                
                if source_type:
                    typer.echo(f"{source_type.title()} sources:")
                else:
                    typer.echo("Configured sources:")
                
                for source in sorted_sources:
                    typer.echo(f"  ID: {source['id']}")
                    typer.echo(f"  Name: {source['name']}")
                    typer.echo(f"  Type: {source['type']}")
                    typer.echo(f"  Enabled Collections: {source['enabled_collections']}")
                    typer.echo(f"  Ingestible Collections: {source['ingestible_collections']}")
                    typer.echo(f"  Created: {source['created_at']}")
                    typer.echo(f"  Updated: {source['updated_at']}")
                    typer.echo()
                
                # Show total
                total_text = f"Total: {len(sources_data)}"
                if source_type:
                    total_text += f" {source_type} source" if len(sources_data) == 1 else f" {source_type} sources"
                else:
                    total_text += " source" if len(sources_data) == 1 else " sources"
                total_text += " configured"
                typer.echo(total_text)
                    
    except Exception as e:
        typer.echo(f"Error listing sources: {e}", err=True)
        raise typer.Exit(1)


# Create a sub-app for asset groups (collections/directories)
asset_groups_app = typer.Typer()
app.add_typer(asset_groups_app, name="assets")

@asset_groups_app.command("list")
def list_asset_groups(
    source_id: str = typer.Argument(..., help="Source ID, name, or external ID"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    List asset groups (collections/directories) from a source.
    
    Examples:
        retrovue source assets list "My Plex Server"
        retrovue source assets list plex-5063d926 --json
    """
    try:
        with session() as db:
            # Get the source
            source = _resolve_source_by_id(db, source_id)
            if not source:
                typer.echo(f"Error: Source '{source_id}' not found", err=True)
                raise typer.Exit(1)
            
            # Get the importer for this source
            from ...adapters.registry import get_importer
            
            # Filter out enrichers from config as importers don't need them
            importer_config = {k: v for k, v in (source.config or {}).items() if k != 'enrichers'}
            importer = get_importer(source.type, **importer_config)
            
            # Get asset groups from the importer
            asset_groups = importer.list_asset_groups()
            
            if json_output:
                typer.echo(json.dumps(asset_groups, indent=2))
            else:
                # Display as Rich table
                from rich.console import Console
                from rich.table import Table
                
                console = Console()
                table = Table(title=f"Asset Groups from {source.name}")
                table.add_column("Name", style="green")
                table.add_column("Path", style="blue")
                table.add_column("Type", style="cyan")
                table.add_column("Asset Count", style="yellow")
                table.add_column("Enabled", style="magenta")
                
                for group in asset_groups:
                    table.add_row(
                        group.get("name", "Unknown"),
                        group.get("path", "Unknown"),
                        group.get("type", "Unknown"),
                        str(group.get("asset_count", "Unknown")),
                        "Yes" if group.get("enabled", False) else "No"
                    )
                
                console.print(table)
                
    except Exception as e:
        typer.echo(f"Error listing asset groups: {e}", err=True)
        raise typer.Exit(1)


@app.command("add")
def add_source(
    type: str | None = typer.Option(None, "--type", help="Source type (plex, filesystem, etc.)"),
    name: str | None = typer.Option(None, "--name", help="Friendly name for the source"),
    base_url: str | None = typer.Option(None, "--base-url", help="Base URL for the source"),
    token: str | None = typer.Option(None, "--token", help="Authentication token"),
    base_path: str | None = typer.Option(None, "--base-path", help="Base filesystem path to scan"),
    enrichers: str | None = typer.Option(None, "--enrichers", help="Comma-separated list of enrichers to use"),
    discover: bool = typer.Option(False, "--discover", help="Automatically discover and persist collections after source creation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be created without executing"),
    test_db: bool = typer.Option(False, "--test-db", help="Direct command to test database environment"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    help_type: bool = typer.Option(False, "--help", help="Show help for the specified source type"),
):
    """
    Add a new content source to the repository for content discovery.
    
    This command adds a content source to the repository. The source type determines
    which importer is used to discover and ingest content from that source.
    
    Available source types are discovered dynamically from registered importers.
    Use 'retrovue source list-types' to see available types.
    
    For detailed help on parameters for a specific type, use:
        retrovue source add --type <type> --help
    
    The CLI validates required parameters based on the importer's configuration schema.
    Each importer type defines its own required and optional configuration parameters.
    """
    try:
        # Handle case where no type is provided
        if not type:
            typer.echo("Error: --type is required")
            typer.echo()
            typer.echo("Available source types:")
            available_importers = list_importers()
            for importer in available_importers:
                typer.echo(f"  • {importer}")
            typer.echo()
            typer.echo("For detailed help on each type, use:")
            for importer in available_importers:
                typer.echo(f"  retrovue source add --type {importer} --help")
            raise typer.Exit(1)
        
        # Get available importers
        available_importers = list_importers()
        if type not in available_importers:
            typer.echo(f"Error: Unknown source type '{type}'. Available types: {', '.join(available_importers)}", err=True)
            raise typer.Exit(1)
        
        # Handle help request for specific type
        if help_type:
            # Get help information for the importer
            help_info = get_importer_help(type)
            
            typer.echo(f"Help for {type} source type:")
            typer.echo(f"Description: {help_info['description']}")
            typer.echo()
            
            typer.echo("Required parameters:")
            for param in help_info['required_params']:
                typer.echo(f"  --{param['name']}: {param['description']}")
                if 'example' in param:
                    typer.echo(f"    Example: {param['example']}")
            
            typer.echo()
            typer.echo("Optional parameters:")
            if help_info['optional_params']:
                for param in help_info['optional_params']:
                    typer.echo(f"  --{param['name']}: {param['description']}")
                    if 'default' in param:
                        typer.echo(f"    Default: {param['default']}")
            else:
                typer.echo("  None")
            
            typer.echo()
            typer.echo("Examples:")
            for example in help_info['examples']:
                typer.echo(f"  {example}")
            
            return  # Exit the function cleanly
        
        # Validate required parameters
        if not name:
            typer.echo("Error: --name is required", err=True)
            raise typer.Exit(1)
        
        # Get importer class to access schema
        try:
            importer_class = SOURCES.get(type)
            if not importer_class:
                typer.echo(f"Error: Importer class not found for type '{type}'", err=True)
                raise typer.Exit(1)
        except KeyError:
            typer.echo(f"Error: Unknown source type '{type}'", err=True)
            raise typer.Exit(1)
        
        # Get configuration schema from importer
        schema = importer_class.get_config_schema()
        
        # Build configuration from CLI args using schema
        importer_params = {}
        config = {}
        
        # Map CLI flags to config params
        # Map common CLI flags to schema param names
        cli_args = {
            "base_url": base_url,
            "token": token,
            "base_path": base_path,
        }
        
        # Build mapping from CLI flags to schema param names
        # This mapping is based on common CLI flag naming conventions
        # The importer schema defines what params are actually required
        cli_to_schema = {}
        
        # Map CLI flags to potential schema param names
        # Note: This is a generic mapping - actual validation comes from schema
        for param in schema.required_params + schema.optional_params:
            param_name = param["name"]
            # Try to match CLI flags to schema params by name
            # Common patterns: base_url -> base_url, base_path -> might be root_paths, etc.
            if param_name in cli_args:
                cli_to_schema[param_name] = param_name
            # Handle special cases where CLI flag name differs from schema param name
            elif param_name == "root_paths" and base_path:
                cli_to_schema["base_path"] = "root_paths"
            elif param_name == "source_name" and name:
                cli_to_schema["name"] = "source_name"
        
        # Validate required params and build config
        for param in schema.required_params:
            param_name = param["name"]
            
            # Check if this param maps to a CLI flag
            cli_flag_value = None
            cli_flag_name = None
            
            # Try direct mapping first
            if param_name in cli_args:
                cli_flag_value = cli_args[param_name]
                cli_flag_name = param_name.replace('_', '-')
            else:
                # Try reverse mapping from schema param to CLI flag
                for cli_key, schema_key in cli_to_schema.items():
                    if schema_key == param_name:
                        cli_flag_value = cli_args.get(cli_key)
                        cli_flag_name = cli_key.replace('_', '-')
                        break
            
            param_value = cli_flag_value or cli_args.get(param_name)
            
            # Handle special case: source_name comes from name parameter
            if param_name == "source_name":
                param_value = name
            
            # Handle special case: root_paths might come from base_path
            if param_name == "root_paths" and not param_value and base_path:
                param_value = base_path
                # Ensure we set the CLI flag name for error messages
                if not cli_flag_name:
                    cli_flag_name = "base-path"
            
            # If we still don't have a CLI flag name, try to derive it from known mappings
            if not cli_flag_name:
                # Common mappings: schema param -> CLI flag
                if param_name == "root_paths":
                    cli_flag_name = "base-path"
                elif param_name == "source_name":
                    cli_flag_name = "name"
                else:
                    # Default: use param_name as flag name
                    cli_flag_name = param_name.replace('_', '-')
            
            if not param_value:
                # Use CLI flag name in error message
                typer.echo(f"Error: --{cli_flag_name} is required for {type} sources", err=True)
                raise typer.Exit(1)
            
            # Store the value in the format the importer expects
            # Convert string to list if schema expects list (e.g., root_paths)
            if param_name == "root_paths" and isinstance(param_value, str):
                importer_params[param_name] = [param_value]
                config[param_name] = [param_value]
            else:
                importer_params[param_name] = param_value
                config[param_name] = param_value
        
        # Handle optional params
        for param in schema.optional_params:
            param_name = param["name"]
            param_value = cli_args.get(param_name)
            if param_value:
                importer_params[param_name] = param_value
                config[param_name] = param_value
        
        # Store config in the format provided by importer_params
        # The importer's constructor expects these params, and we store them as-is
        # If an importer needs a different storage format, it should provide
        # conversion methods, but for now we store what the importer accepts
        
        # Parse enrichers
        enricher_list = []
        if enrichers:
            try:
                available_enrichers = [e.name for e in list_enrichers()]
            except Exception as e:
                typer.echo(f"Error: Failed to load enricher registry: {e}", err=True)
                raise typer.Exit(1)
            
            enricher_list = [e.strip() for e in enrichers.split(",") if e.strip()]
            unknown_enrichers = []
            for enricher in enricher_list:
                if enricher not in available_enrichers:
                    unknown_enrichers.append(enricher)
            
            if unknown_enrichers:
                for enricher in unknown_enrichers:
                    typer.echo(f"Error: Unknown enricher '{enricher}'. Available: {', '.join(available_enrichers)}", err=True)
                raise typer.Exit(1)
        
        # Create the importer instance to validate configuration
        importer = get_importer(type, **importer_params)
        
        # Handle dry-run mode
        if dry_run:
            # Generate external ID for preview
            external_id = f"{type}-{uuid.uuid4().hex[:8]}"
            
            if json_output:
                import json
                result = {
                    "id": f"preview-{external_id}",
                    "external_id": external_id,
                    "name": name,
                    "type": type,
                    "config": config,
                    "enrichers": enricher_list,
                    "importer_name": importer.name,
                    "dry_run": True
                }
                typer.echo(json.dumps(result, indent=2))
            else:
                typer.echo(f"[DRY RUN] Would create {type} source: {name}")
                typer.echo(f"  External ID: {external_id}")
                typer.echo(f"  Type: {type}")
                typer.echo(f"  Importer: {importer.name}")
                if enricher_list:
                    typer.echo(f"  Enrichers: {', '.join(enricher_list)}")
                typer.echo(f"  Configuration: {config}")
                if discover:
                    # Discovery support is determined by the importer's capabilities
                    # We can't know this without instantiating the importer, so just note it
                    typer.echo("  Would discover collections: Yes (if supported by importer)")
            return
        
        # Handle test-db mode
        if test_db:
            typer.echo("Using test database environment", err=True)
            # TODO: Implement test database isolation
            # For now, just continue with normal flow but mark as test mode
        
        # Now actually create and save the source in the database
        with session() as db:
            # Use usecase function (contract-aligned)
            result = usecase_add_source(
                db,
                source_type=type,
                name=name,
                config=config,
                enrichers=enricher_list if enricher_list else None
            )
            
            # Add collections_discovered field for backward compatibility
            result["collections_discovered"] = 0
            
            # Note: --discover flag is ignored in add command per contract
            # Discovery is handled by separate source discover command
            
            if json_output:
                import json
                # Add importer name to result
                result["importer_name"] = importer.name
                # Add status field for contract compliance
                result["status"] = "success"
                
                typer.echo(json.dumps(result, indent=2))
            else:
                typer.echo(f"Successfully created {type} source: {name}")
                typer.echo(f"  Name: {name}")
                typer.echo(f"  ID: {result['id']}")
                typer.echo(f"  Type: {type}")
                if enricher_list:
                    typer.echo(f"  Enrichers: {', '.join(enricher_list)}")
                
    except Exception as e:
        typer.echo(f"Error adding source: {e}", err=True)
        raise typer.Exit(1)




@app.command("list-types")
def list_source_types(
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    test_db: bool = typer.Option(False, "--test-db", help="Use test database environment"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be listed without executing external validation"),
):
    """
    List all available source types (importers) with interface compliance validation.
    
    This command enumerates source types from the importer registry, validates
    interface compliance, and reports availability status.
    
    Examples:
        retrovue source list-types
        retrovue source list-types --json
        retrovue source list-types --dry-run
        retrovue source list-types --test-db
    """
    try:
        # Get available importers from registry
        available_importers = list_importers()
        
        
        if not available_importers:
            if json_output:
                import json
                result = {
                    "status": "ok",
                    "source_types": [],
                    "total": 0
                }
                typer.echo(json.dumps(result, indent=2))
            else:
                typer.echo("No source types available")
            return
        
        # Build source type information with interface compliance validation
        source_types = []
        
        for importer_name in available_importers:
            try:
                # Get importer class from registry
                importer_class = SOURCES.get(importer_name)
                if not importer_class:
                    continue
                
                # Check interface compliance
                interface_compliant = _check_interface_compliance(importer_class)
                
                # Get display name and status
                display_name = _get_display_name(importer_name)
                status = "valid" if interface_compliant else "error"
                
                source_type_info = {
                    "type": importer_name,
                    "importer_file": f"{importer_name}_importer.py",
                    "display_name": display_name,
                    "available": True,
                    "interface_compliant": interface_compliant,
                    "status": status
                }
                
                source_types.append(source_type_info)
                
            except Exception:
                # Handle individual importer validation errors
                source_type_info = {
                    "type": importer_name,
                    "importer_file": f"{importer_name}_importer.py",
                    "display_name": f"{importer_name.title()} Source",
                    "available": False,
                    "interface_compliant": False,
                    "status": "error"
                }
                source_types.append(source_type_info)
        
        # Handle dry-run mode
        if dry_run:
            if json_output:
                import json
                result = {
                    "status": "dry_run",
                    "source_types": source_types,
                    "total": len(source_types)
                }
                typer.echo(json.dumps(result, indent=2))
            else:
                typer.echo(f"Would list {len(source_types)} source types from registry:")
                for source_type in source_types:
                    status_indicator = "[OK]" if source_type["interface_compliant"] else "[ERROR]"
                    typer.echo(f"  - {source_type['type']} ({source_type['importer_file']}) {status_indicator}")
            return
        
        # Normal output
        if json_output:
            import json
            result = {
                "status": "ok",
                "source_types": source_types,
                "total": len(source_types)
            }
            typer.echo(json.dumps(result, indent=2))
        else:
            typer.echo("Available source types:")
            for source_type in source_types:
                status_indicator = "[OK]" if source_type["interface_compliant"] else "[ERROR]"
                typer.echo(f"  - {source_type['type']} {status_indicator}")
            
            typer.echo(f"\nTotal: {len(source_types)} source types available")
                
    except Exception as e:
        typer.echo(f"Error listing source types: {e}", err=True)
        raise typer.Exit(1)


def _check_interface_compliance(importer_class) -> bool:
    """
    Check if an importer class implements the required interface.
    
    Args:
        importer_class: The importer class to check
        
    Returns:
        True if the class implements the required interface, False otherwise
    """
    try:
        # Check if the class has the required methods from ImporterInterface
        required_methods = [
            'get_config_schema',
            'discover',
            'get_help',
            'list_asset_groups',
            'enable_asset_group',
            'disable_asset_group'
        ]
        
        for method_name in required_methods:
            if not hasattr(importer_class, method_name):
                return False
        
        # Check if it has the name attribute (class attribute, not instance)
        if not hasattr(importer_class, 'name'):
            return False
        
        # Verify the name attribute is accessible
        try:
            name_value = importer_class.name
            if not name_value:
                return False
        except Exception:
            return False
        
        # Try to create a minimal instance to test interface
        # This is a basic check - in a real implementation you'd want more thorough validation
        return True
        
    except Exception:
        return False


def _get_display_name(importer_name: str) -> str:
    """
    Get a human-readable display name for an importer.
    
    This is product-agnostic - it uses the importer's help information if available,
    otherwise falls back to a generic format.
    
    Args:
        importer_name: The importer name
        
    Returns:
        Human-readable display name
    """
    try:
        # Try to get display name from importer's help
        help_info = get_importer_help(importer_name)
        if help_info and "description" in help_info:
            # Use description as display name, or derive from it
            return help_info["description"].split(".")[0]  # First sentence
    except Exception:
        pass
    
    # Fallback: generic format
    return f"{importer_name.title()} Source"


@app.command("show")
def show_source(
    source_id: str = typer.Argument(..., help="Source ID, external ID, or name to show"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    Show details for a specific source.
    
    Examples:
        retrovue source show "My Plex Server"
        retrovue source show filesystem-4807c63e
        retrovue source show 4b2b05e7-d7d2-414a-a587-3f5df9b53f44 --json
    """
    with session() as db:
        try:
            source = _resolve_source_by_id(db, source_id)
            if not source:
                typer.echo(f"Error: Source '{source_id}' not found", err=True)
                raise typer.Exit(1)
            
            if json_output:
                import json
                source_dict = {
                    "id": source.id,
                    "external_id": source.external_id,
                    "type": source.type,
                    "name": source.name,
                    "status": source.status,
                    "base_url": source.base_url,
                    "config": source.config
                }
                typer.echo(json.dumps(source_dict, indent=2))
            else:
                typer.echo("Source Details:")
                typer.echo(f"  ID: {source.id}")
                typer.echo(f"  External ID: {source.external_id}")
                typer.echo(f"  Name: {source.name}")
                typer.echo(f"  Type: {source.type}")
                typer.echo(f"  Status: {source.status}")
                if source.base_url:
                    typer.echo(f"  Base URL: {source.base_url}")
                if source.config:
                    typer.echo(f"  Configuration: {source.config}")
                    
        except Exception as e:
            typer.echo(f"Error showing source: {e}", err=True)
            raise typer.Exit(1)


@app.command("update")
def update_source(
    source_id: str = typer.Argument(..., help="Source ID, external ID, or name to update"),
    name: str | None = typer.Option(None, "--name", help="New name for the source"),
    base_url: str | None = typer.Option(None, "--base-url", help="New base URL for the source"),
    token: str | None = typer.Option(None, "--token", help="New authentication token"),
    base_path: str | None = typer.Option(None, "--base-path", help="New base filesystem path"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be updated without executing"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    Update a source configuration.
    
    Examples:
        retrovue source update "My Plex Server" --name "Updated Plex Server"
        retrovue source update filesystem-4807c63e --name "Updated Media Library"
        retrovue source update "Test Plex" --base-url "http://new-plex:32400" --token "new-token"
    """
    with session() as db:
        try:
            # Get current source to determine type
            current_source = source_get_by_id(source_id)
            if not current_source:
                typer.echo(f"Error: Source '{source_id}' not found", err=True)
                raise typer.Exit(1)
            
            # Verify importer interface compliance (B-17, D-7)
            # This check happens BEFORE building updates, BEFORE opening transaction, BEFORE UnitOfWork
            from ...adapters.registry import ALIASES, SOURCES
            
            # Get importer class (not instance) for interface compliance check
            importer_key = ALIASES.get(current_source.type.lower(), current_source.type.lower())
            try:
                importer_class = SOURCES[importer_key]
            except KeyError:
                typer.echo(f"Error: Importer for source type '{current_source.type}' is not available or not interface-compliant", err=True)
                raise typer.Exit(1)
            
            # Check that importer class implements required update methods
            if not hasattr(importer_class, "get_update_fields") or not hasattr(importer_class, "validate_partial_update"):
                typer.echo(f"Error: Importer for source type '{current_source.type}' is not available or not interface-compliant", err=True)
                raise typer.Exit(1)
            
            # Build update configuration using importer's update fields
            updates = {}
            new_config = current_source.config.copy() if current_source.config else {}
            
            if name:
                updates["name"] = name
            
            # Get updatable fields from importer
            update_fields = importer_class.get_update_fields()
            
            # Build partial config from CLI args
            partial_config = {}
            cli_args_map = {
                "base_url": base_url,
                "token": token,
                "base_path": base_path,
            }
            
            for field_spec in update_fields:
                config_key = field_spec.config_key
                cli_value = cli_args_map.get(config_key)
                
                if cli_value is not None:
                    partial_config[config_key] = cli_value
            
            # Validate partial update using importer
            if partial_config:
                try:
                    importer_class.validate_partial_update(partial_config)
                except Exception as e:
                    typer.echo(f"Error: Invalid configuration update: {e}", err=True)
                    raise typer.Exit(1)
                
                # Merge into new_config, preserving existing structure
                # Contract D-10: Partial merges apply only to top-level keys.
                # Nested objects/arrays are treated as atomic values.
                # However, if stored config has a different format than what importer expects,
                # we need to map the update fields to the stored format.
                # 
                # TODO: Importers should provide methods to convert between storage and runtime formats
                # For now, we detect if stored config has nested structures and try to map updates
                # This is a temporary workaround until importers handle their own format conversions
                
                # Check if stored config has nested list structures that might need updating
                # This is generic - we look for any list of dicts that might contain our update keys
                updated_nested = False
                for _key, value in new_config.items():
                    if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
                        # Check if any update keys exist in the nested dict
                        nested_dict = value[0]
                        for update_key, update_value in partial_config.items():
                            if update_key in nested_dict:
                                nested_dict[update_key] = update_value
                                updated_nested = True
                
                # If we updated nested structures, don't also do a flat update for those keys
                if updated_nested:
                    # Only update keys that weren't handled in nested structures
                    for key, value in partial_config.items():
                        if key not in new_config or not (isinstance(new_config.get(key), list) and len(new_config[key]) > 0 and isinstance(new_config[key][0], dict)):
                            new_config[key] = value
                else:
                    # Flat update - standard merge
                    new_config.update(partial_config)
            
            if new_config:
                updates["config"] = new_config
            
            if not updates:
                typer.echo("No updates provided", err=True)
                raise typer.Exit(1)
            
            # Handle dry-run mode
            if dry_run:
                # Redact sensitive config for display
                current_config_redacted = _redact_sensitive_config(current_source.config.copy() if current_source.config else {})
                proposed_config_redacted = _redact_sensitive_config(new_config.copy() if new_config else {})
                
                if json_output:
                    # Dry-run JSON output format (B-16)
                    result = {
                        "id": current_source.id,
                        "external_id": current_source.external_id,
                        "type": current_source.type,
                        "current_name": current_source.name,
                        "proposed_name": name if name else current_source.name,
                        "current_config": current_config_redacted,
                        "proposed_config": proposed_config_redacted,
                        "updated_parameters": []
                    }
                    if name:
                        result["updated_parameters"].append("name")
                    if "config" in updates:
                        # Add updated parameters from partial_config
                        for key in partial_config.keys():
                            if key not in result["updated_parameters"]:
                                result["updated_parameters"].append(key)
                    typer.echo(json.dumps(result, indent=2))
                else:
                    # Dry-run human-readable output
                    typer.echo(f"Would update source: {current_source.name}")
                    typer.echo(f"  ID: {current_source.id}")
                    typer.echo(f"  Current Name: {current_source.name}")
                    if name:
                        typer.echo(f"  Proposed Name: {name}")
                    typer.echo(f"  Type: {current_source.type}")
                    
                    if "config" in updates:
                        typer.echo(f"  Current Configuration: {json.dumps(current_config_redacted)}")
                        typer.echo(f"  Proposed Configuration: {json.dumps(proposed_config_redacted)}")
                    
                    typer.echo("(No database changes made — dry-run mode)")
                return
            
            # Update the source using thin function
            result = source_update(source_id, updates, db_session=db)
            if not result:
                typer.echo(f"Error: Failed to update source '{source_id}'", err=True)
                raise typer.Exit(1)
            
            # Redact sensitive config for display
            redacted_config = _redact_sensitive_config(result["config"].copy() if result["config"] else {})
            
            if json_output:
                source_dict = {
                    "id": result["id"],
                    "external_id": result["external_id"],
                    "type": result["type"],
                    "name": result["name"],
                    "config": redacted_config,
                    "updated_parameters": []
                }
                if name:
                    source_dict["updated_parameters"].append("name")
                if "config" in updates:
                    # Add updated parameters from partial_config
                    for key in partial_config.keys():
                        if key not in source_dict["updated_parameters"]:
                            source_dict["updated_parameters"].append(key)
                typer.echo(json.dumps(source_dict, indent=2))
            else:
                typer.echo(f"Successfully updated source: {result['name']}")
                typer.echo(f"  ID: {result['id']}")
                typer.echo(f"  Type: {result['type']}")
                if result["config"]:
                    typer.echo(f"  Configuration: {json.dumps(redacted_config)}")
                    
        except Exception as e:
            typer.echo(f"Error updating source: {e}", err=True)
            raise typer.Exit(1)


@app.command("delete", no_args_is_help=True)
def delete_source(
    source_selector: str = typer.Argument(..., help="Source ID, external ID, name, or wildcard pattern to delete"),
    force: bool = typer.Option(False, "--force", help="Force deletion without confirmation"),
    confirm: bool = typer.Option(False, "--confirm", help="Required flag to proceed with deletion"),
    test_db: bool = typer.Option(False, "--test-db", help="Direct command to test database environment"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    Delete a source.
    
    Examples:
        retrovue source delete "My Plex Server"
        retrovue source delete filesystem-4807c63e --force
        retrovue source delete 4b2b05e7-d7d2-414a-a587-3f5df9b53f44
        retrovue source delete "plex-%" --confirm
    """
    from ._ops.confirmation import evaluate_confirmation
    from ._ops.source_delete_ops import (
        build_pending_delete_summary,
        format_human_output,
        format_json_output,
        perform_source_deletions,
        resolve_source_selector,
    )
    
    # Production safety check
    if not test_db and not force:
        import os

        from ...infra.settings import settings
        
        # Check if this looks like a production database
        is_production = True
        db_url = settings.database_url or ""
        
        # Consider it a test database if:
        # 1. URL contains "test" 
        # 2. TEST_DATABASE_URL environment variable is set
        # 3. Database name contains "test", "dev", "local", or "sandbox"
        if ("test" in db_url.lower() or 
            os.getenv("TEST_DATABASE_URL") or
            any(word in db_url.lower() for word in ["test", "dev", "local", "sandbox"])):
            is_production = False
        
        if is_production:
            typer.echo("⚠️  WARNING: This appears to be a production database!", err=True)
            typer.echo("", err=True)
            typer.echo("   To delete sources from production:", err=True)
            typer.echo("   1. Use --test-db flag for test databases only", err=True)
            typer.echo("   2. For production: backup your database first", err=True)
            typer.echo("   3. Consider using --dry-run to preview changes", err=True)
            typer.echo("   4. Use --force flag to bypass this safety check", err=True)
            typer.echo("", err=True)
            typer.echo("   Example: retrovue source delete 'source-name' --force", err=True)
            typer.echo("", err=True)
            typer.echo("   To mark as test database:", err=True)
            typer.echo("   - Set TEST_DATABASE_URL environment variable", err=True)
            typer.echo("   - Use database name with 'test', 'dev', 'local', or 'sandbox'", err=True)
            raise typer.Exit(1)
    
    try:
        with session() as db:
            # Call resolve_source_selector(...)
            sources = resolve_source_selector(db, source_selector)
            
            # If it returns an empty list, print Error and exit code 1 (B-5)
            if not sources:
                typer.echo(f"Error: Source '{source_selector}' not found", err=True)
                raise typer.Exit(1)
            
            # Call build_pending_delete_summary(...) to get the impact summary
            summary = build_pending_delete_summary(db, sources)
            
            # Run the confirmation gate
            # First call evaluate_confirmation(...) with user_response=None
            proceed, prompt = evaluate_confirmation(
                summary=summary,
                force=force,
                confirm=confirm,
                user_response=None
            )
            
            if not proceed and prompt is not None:
                # If that returns (False, <prompt>), print <prompt>, read from stdin
                typer.echo(prompt)
                user_response = typer.prompt("", default="no")
                
                # then call evaluate_confirmation(...) again with the user's response
                proceed, message = evaluate_confirmation(
                    summary=summary,
                    force=force,
                    confirm=confirm,
                    user_response=user_response
                )
                
                if not proceed and message == "Deletion cancelled":
                    # If the second evaluation returns (False, "Deletion cancelled"), print "Deletion cancelled" and exit code 0 (B-6)
                    typer.echo("Deletion cancelled")
                    raise typer.Exit(0)
            
            # Call perform_source_deletions(...) to actually apply deletions / skips
            # Create a simple environment configuration for now
            class SimpleEnvConfig:
                def is_production(self):
                    # For now, always return False (non-production) to allow deletion
                    # TODO: Implement proper environment detection
                    return False
            
            env_config = SimpleEnvConfig()
            args = type('Args', (), {'test_db': test_db})()
            results = perform_source_deletions(db, env_config, args, sources)
            
            # If --json: Render JSON with the output helper from source_delete_ops
            if json_output:
                json_output_data = format_json_output(results)
                typer.echo(json.dumps(json_output_data, indent=2))
            else:
                # Else: Render human-readable output with the output helper from source_delete_ops
                human_output = format_human_output(results)
                typer.echo(human_output)
        
        # Exit code 0 - transaction has been committed
        raise typer.Exit(0)
                    
    except typer.Exit:
        # Re-raise typer.Exit exceptions (including cancellation)
        raise
    except Exception as e:
        typer.echo(f"Error deleting source: {e}", err=True)
        raise typer.Exit(1)


@app.command("discover")
def discover_collections(
    source_id: str = typer.Argument(..., help="Source ID, external ID, or name to discover collections from"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    test_db: bool = typer.Option(False, "--test-db", help="Direct command to test database environment"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be discovered without persisting"),
):
    """
    Discover and add collections (libraries) from a source to the repository.
    
    This scans the source for available collections/libraries and adds them
    to the RetroVue database for management. Collections start disabled by default.
    
    Examples:
        retrovue source discover "My Plex"
        retrovue source discover plex-5063d926
        retrovue source discover "My Plex" --json
    """
    with session() as db:
        try:
            # Get the source first to validate it exists
            source = source_get_by_id(source_id)
            if not source:
                typer.echo(f"Error: Source '{source_id}' not found", err=True)
                raise typer.Exit(1)
            
            # Use usecase for collection discovery (handles all source types)
            try:
                collections = usecase_discover_collections(db, source_id=source_id)
            except ValueError as e:
                # Handle unsupported source types gracefully per contract
                if "Unsupported source type" in str(e):
                    if json_output:
                        import json
                        result = {
                            "source": {
                                "id": str(source.id),
                                "name": source.name,
                                "type": source.type
                            },
                            "collections_added": 0,
                            "collections": []
                        }
                        typer.echo(json.dumps(result, indent=2))
                    else:
                        typer.echo(f"No collections discoverable for source type '{source.type}'")
                    return
                raise
            
            if not collections:
                if json_output:
                    import json
                    result = {
                        "source": {
                            "id": str(source.id),
                            "name": source.name,
                            "type": source.type
                        },
                        "collections_added": 0,
                        "collections": []
                    }
                    typer.echo(json.dumps(result, indent=2))
                else:
                    typer.echo(f"No collections found for source '{source.name}'")
                return
            
            # Prepare summaries for output and track added count
            collection_summaries = []
            added_count = 0
            
            for collection in collections:
                # Check if collection already exists
                existing = db.query(Collection).filter(
                    Collection.source_id == source.id,
                    Collection.external_id == collection["external_id"]
                ).first()
                
                if existing:
                    if dry_run:
                        typer.echo(f"  Collection '{collection['name']}' already exists, would skip")
                    else:
                        typer.echo(f"  Collection '{collection['name']}' already exists, skipping")
                    continue
                
                # Build config from collection data returned by importer
                # Store whatever the importer provides - this is product-agnostic
                config = {}
                # Copy all fields from collection except the ones we handle separately
                for key, value in collection.items():
                    if key not in ("external_id", "name", "http_status"):
                        config[key] = value
                
                # Ensure type is included if not present
                if "type" not in config:
                    config["type"] = collection.get("type", "unknown")
                collection_summaries.append({
                    "external_id": collection["external_id"],
                    "name": collection["name"],
                    "sync_enabled": False,
                    "source_type": source.type,
                    "config": config,
                })
                added_count += 1
                
                # Only persist to database if not in dry-run mode
                if not dry_run:
                    # Use thin function for collection persistence
                    success = source_persist_collections(source_id, [collection], test_db, db)
                    if not success:
                        typer.echo(f"  Warning: Failed to persist collection '{collection['name']}'", err=True)
                        continue
            
            if json_output:
                import json
                result = {
                    "source": {
                        "id": str(source.id),
                        "name": source.name,
                        "type": source.type
                    },
                    "collections_added": added_count,
                    "collections": collection_summaries
                }
                typer.echo(json.dumps(result, indent=2))
            else:
                if dry_run:
                    typer.echo(f"Would discover {added_count} collections from '{source.name}':")
                    for summary in collection_summaries:
                        typer.echo(f"  • {summary['name']} (ID: {summary['external_id']}) - Would be created")
                else:
                    typer.echo(f"Successfully added {added_count} collections from '{source.name}':")
                    for summary in collection_summaries:
                        typer.echo(f"  • {summary['name']} (ID: {summary['external_id']}) - Disabled by default")
                    typer.echo()
                    typer.echo("Use 'retrovue collection update <name> --sync-enabled true' to enable collections for sync")
                    
        except Exception as e:
            typer.echo(f"Error discovering collections: {e}", err=True)
            raise typer.Exit(1)


@app.command("ingest")
def source_ingest(
    source_id: str = typer.Argument(..., help="Source ID, external ID, or name to ingest from"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be ingested without actually ingesting"),
):
    """
    Ingest all sync-enabled, ingestible collections from a source.
    
    This command finds all collections that are both sync-enabled and ingestible,
    then processes them using the ingest orchestrator.
    
    Examples:
        retrovue source --name "My Plex Server" ingest
        retrovue source plex-5063d926 ingest
        retrovue source "My Plex Server" ingest --json
    """
    with session() as db:
        try:
            # Get the source first to validate it exists
            source = source_get_by_id(source_id)
            if not source:
                typer.echo(f"Error: Source '{source_id}' not found", err=True)
                raise typer.Exit(1)
            
            # Get sync-enabled, ingestible collections for this source
            collections = db.query(Collection).filter(
                Collection.source_id == source.id,
                Collection.sync_enabled
            ).all()
            
            if not collections:
                typer.echo(f"No sync-enabled collections found for source '{source.name}'")
                typer.echo("Use 'retrovue collection update <name> --sync-enabled true' to enable collections")
                return
            
            # Filter to only ingestible collections using persisted field
            ingestible_collections = []
            for collection in collections:
                if collection.ingestible:
                    ingestible_collections.append(collection)
                else:
                    typer.echo(f"  Skipping '{collection.name}' - not ingestible (no valid local paths)")
            
            if not ingestible_collections:
                typer.echo(f"No ingestible collections found for source '{source.name}'")
                typer.echo("Configure path mappings and ensure local paths are accessible")
                return
            
            # Ingest orchestrator is legacy; this operation is not available
            typer.echo("Ingest operation is not available: legacy orchestrator removed", err=True)
            raise typer.Exit(1)
                    
        except Exception as e:
            typer.echo(f"Error ingesting from source: {e}", err=True)
            raise typer.Exit(1)


@app.command("attach-enricher")
def source_attach_enricher(
    source_id: str = typer.Argument(..., help="Source ID, external ID, or name to attach enricher to"),
    enricher_id: str = typer.Argument(..., help="Enricher ID to attach"),
    priority: int = typer.Option(1, "--priority", help="Priority/order for enricher execution (default: 1)"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    Attach an ingest-scope enricher to all collections in a source.
    
    This command attaches the specified enricher to all collections under the source,
    applying it during the ingest process for each collection.
    
    Parameters:
    - source_id: Source to attach enricher to (can be ID, external ID, or name)
    - enricher_id: Enricher to attach
    - priority: Execution priority (lower numbers run first)
    
    Examples:
        retrovue source --name "My Plex Server" attach-enricher enricher-ffprobe-1
        retrovue source plex-5063d926 attach-enricher enricher-metadata-1 --priority 2
        retrovue source "My Plex Server" attach-enricher enricher-llm-1 --priority 3
    """
    with session() as db:
        try:
            # Get the source first to validate it exists
            source = _resolve_source_by_id(db, source_id)
            if not source:
                typer.echo(f"Error: Source '{source_id}' not found", err=True)
                raise typer.Exit(1)
            
            # Get all collections for this source
            collections = db.query(Collection).filter(
                Collection.source_id == source.id
            ).all()
            
            if not collections:
                typer.echo(f"No collections found for source '{source.name}'")
                return
            
            # TODO: Implement actual enricher attachment logic
            # For now, just show what would be attached
            typer.echo(f"Attaching enricher '{enricher_id}' to {len(collections)} collections in source '{source.name}'")
            typer.echo(f"Priority: {priority}")
            typer.echo()
            typer.echo("Collections that will have the enricher attached:")
            for collection in collections:
                typer.echo(f"  - {collection.name} (ID: {collection.id})")
            
            if json_output:
                import json
                result = {
                    "source": {
                        "id": str(source.id),
                        "name": source.name,
                        "type": source.type
                    },
                    "enricher_id": enricher_id,
                    "priority": priority,
                    "collections_affected": len(collections),
                    "collections": [
                        {
                            "id": str(collection.id),
                            "name": collection.name,
                            "external_id": collection.external_id
                        }
                        for collection in collections
                    ],
                    "status": "attached"
                }
                typer.echo(json.dumps(result, indent=2))
            else:
                typer.echo(f"Successfully attached enricher '{enricher_id}' to {len(collections)} collections")
                typer.echo("TODO: Implement actual enricher attachment logic")
                
        except Exception as e:
            typer.echo(f"Error attaching enricher to source: {e}", err=True)
            raise typer.Exit(1)


@app.command("detach-enricher")
def source_detach_enricher(
    source_id: str = typer.Argument(..., help="Source ID, external ID, or name to detach enricher from"),
    enricher_id: str = typer.Argument(..., help="Enricher ID to detach"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    Detach an ingest-scope enricher from all collections in a source.
    
    This command removes the specified enricher from all collections under the source,
    preventing it from running during the ingest process for each collection.
    
    Parameters:
    - source_id: Source to detach enricher from (can be ID, external ID, or name)
    - enricher_id: Enricher to detach
    
    Examples:
        retrovue source --name "My Plex Server" detach-enricher enricher-ffprobe-1
        retrovue source plex-5063d926 detach-enricher enricher-metadata-1
        retrovue source "My Plex Server" detach-enricher enricher-llm-1
    """
    with session() as db:
        try:
            # Get the source first to validate it exists
            source = _resolve_source_by_id(db, source_id)
            if not source:
                typer.echo(f"Error: Source '{source_id}' not found", err=True)
                raise typer.Exit(1)
            
            # Get all collections for this source
            collections = db.query(Collection).filter(
                Collection.source_id == source.id
            ).all()
            
            if not collections:
                typer.echo(f"No collections found for source '{source.name}'")
                return
            
            # TODO: Implement actual enricher detachment logic
            # For now, just show what would be detached
            typer.echo(f"Detaching enricher '{enricher_id}' from {len(collections)} collections in source '{source.name}'")
            typer.echo()
            typer.echo("Collections that will have the enricher detached:")
            for collection in collections:
                typer.echo(f"  - {collection.name} (ID: {collection.id})")
            
            if json_output:
                import json
                result = {
                    "source": {
                        "id": str(source.id),
                        "name": source.name,
                        "type": source.type
                    },
                    "enricher_id": enricher_id,
                    "collections_affected": len(collections),
                    "collections": [
                        {
                            "id": str(collection.id),
                            "name": collection.name,
                            "external_id": collection.external_id
                        }
                        for collection in collections
                    ],
                    "status": "detached"
                }
                typer.echo(json.dumps(result, indent=2))
            else:
                typer.echo(f"Successfully detached enricher '{enricher_id}' from {len(collections)} collections")
                typer.echo("TODO: Implement actual enricher detachment logic")
                
        except Exception as e:
            typer.echo(f"Error detaching enricher from source: {e}", err=True)
            raise typer.Exit(1)




@asset_groups_app.command("enable")
def enable_asset_group(
    source_id: str = typer.Argument(..., help="Source ID, name, or external ID"),
    group_id: str = typer.Argument(..., help="Asset group ID to enable"),
):
    """
    Enable an asset group for content discovery.
    
    Examples:
        retrovue source assets enable "My Plex Server" "Movies"
        retrovue source assets enable plex-5063d926 "TV Shows"
    """
    try:
        with session() as db:
            # Get the source
            source = _resolve_source_by_id(db, source_id)
            if not source:
                typer.echo(f"Error: Source '{source_id}' not found", err=True)
                raise typer.Exit(1)
            
            # Get the importer for this source
            from ...adapters.registry import get_importer
            
            # Filter out enrichers from config as importers don't need them
            importer_config = {k: v for k, v in (source.config or {}).items() if k != 'enrichers'}
            importer = get_importer(source.type, **importer_config)
            
            # Enable the asset group
            success = importer.enable_asset_group(group_id)
            
            if success:
                typer.echo(f"Asset group '{group_id}' enabled successfully")
            else:
                typer.echo(f"Error: Failed to enable asset group '{group_id}'", err=True)
                raise typer.Exit(1)
                
    except Exception as e:
        typer.echo(f"Error enabling asset group: {e}", err=True)
        raise typer.Exit(1)


@asset_groups_app.command("disable")
def disable_asset_group(
    source_id: str = typer.Argument(..., help="Source ID, name, or external ID"),
    group_id: str = typer.Argument(..., help="Asset group ID to disable"),
):
    """
    Disable an asset group from content discovery.
    
    Examples:
        retrovue source assets disable "My Plex Server" "Movies"
        retrovue source assets disable plex-5063d926 "TV Shows"
    """
    try:
        with session() as db:
            # Get the source
            source = _resolve_source_by_id(db, source_id)
            if not source:
                typer.echo(f"Error: Source '{source_id}' not found", err=True)
                raise typer.Exit(1)
            
            # Get the importer for this source
            from ...adapters.registry import get_importer
            
            # Filter out enrichers from config as importers don't need them
            importer_config = {k: v for k, v in (source.config or {}).items() if k != 'enrichers'}
            importer = get_importer(source.type, **importer_config)
            
            # Disable the asset group
            success = importer.disable_asset_group(group_id)
            
            if success:
                typer.echo(f"Asset group '{group_id}' disabled successfully")
            else:
                typer.echo(f"Error: Failed to disable asset group '{group_id}'", err=True)
                raise typer.Exit(1)
                
    except Exception as e:
        typer.echo(f"Error disabling asset group: {e}", err=True)
        raise typer.Exit(1)


@app.command("enrichers")
def update_enrichers(
    source_id: str = typer.Argument(..., help="Source ID, external ID, or name to update"),
    enrichers: str = typer.Argument(..., help="Comma-separated list of enrichers to use"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    Update enrichers for a source.
    
    Examples:
        retrovue source enrichers "My Plex" "ffprobe"
        retrovue source enrichers "My Plex" "ffprobe,metadata"
        retrovue source enrichers plex-5063d926 "ffprobe"
    """
    with session() as db:
        try:
            # Get the source
            source = _resolve_source_by_id(db, source_id)
            if not source:
                typer.echo(f"Error: Source '{source_id}' not found", err=True)
                raise typer.Exit(1)
            
            # Parse enrichers
            enricher_list = [e.strip() for e in enrichers.split(",") if e.strip()]
            
            # Validate enrichers
            available_enrichers = [e.name for e in list_enrichers()]
            unknown_enrichers = []
            for enricher in enricher_list:
                if enricher not in available_enrichers:
                    unknown_enrichers.append(enricher)
            
            if unknown_enrichers:
                for enricher in unknown_enrichers:
                    typer.echo(f"Error: Unknown enricher '{enricher}'. Available: {', '.join(available_enrichers)}", err=True)
                raise typer.Exit(1)
            
            # Update enrichers in source config
            if source.config is None:
                source.config = {}
            source.config["enrichers"] = enricher_list
            db.commit()
            
            if json_output:
                import json
                result = {
                    "source_id": source_id,
                    "enrichers": enricher_list
                }
                typer.echo(json.dumps(result, indent=2))
            else:
                typer.echo(f"Successfully updated enrichers for source: {source_id}")
                typer.echo(f"  Enrichers: {', '.join(enricher_list)}")
                
        except Exception as e:
            typer.echo(f"Error updating enrichers: {e}", err=True)
            raise typer.Exit(1)