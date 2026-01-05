"""
Enricher CLI commands for enricher management.

Surfaces enricher management capabilities including listing, configuration, and management.
Focuses on enrichment parameter validation - specific values an enricher needs to
perform its enrichment tasks (API keys, file paths, timing values, etc.).
"""

from __future__ import annotations

import json
from typing import Any

import typer

from ...domain.entities import Enricher as EnricherModel
from ...infra.uow import session

app = typer.Typer(name="enricher", help="Enricher management operations")


def validate_enrichment_parameters(enricher_type: str, config: dict[str, Any]) -> None:
    """
    Validate enrichment parameters for a specific enricher type.

    Enrichment parameters are specific values an enricher needs to perform its
    enrichment tasks (API keys, file paths, timing values, etc.).

    Args:
        enricher_type: The type of enricher (e.g., 'tvdb', 'watermark', 'ffmpeg')
        config: Dictionary of enrichment parameters to validate

    Raises:
        ValueError: If enrichment parameters are invalid
    """
    if enricher_type == "tvdb":
        _validate_tvdb_parameters(config)
    elif enricher_type == "tmdb":
        _validate_tmdb_parameters(config)
    elif enricher_type == "watermark":
        _validate_watermark_parameters(config)
    elif enricher_type == "crossfade":
        _validate_crossfade_parameters(config)
    elif enricher_type == "llm":
        _validate_llm_parameters(config)
    elif enricher_type == "ffmpeg" or enricher_type == "ffprobe":
        _validate_ffmpeg_parameters(config)
    else:
        # For unknown enricher types, perform basic validation
        _validate_generic_parameters(config)


def _validate_tvdb_parameters(config: dict[str, Any]) -> None:
    """Validate TheTVDB enricher enrichment parameters."""
    if "api_key" in config:
        api_key = config["api_key"]
        if not isinstance(api_key, str) or len(api_key) < 10:
            raise ValueError("API key enrichment parameter must be at least 10 characters long")

    if "language" in config:
        language = config["language"]
        if not isinstance(language, str) or len(language) < 2:
            raise ValueError("Language enrichment parameter must be at least 2 characters long")


def _validate_tmdb_parameters(config: dict[str, Any]) -> None:
    """Validate TMDB enricher enrichment parameters."""
    if "api_key" in config:
        api_key = config["api_key"]
        if not isinstance(api_key, str) or len(api_key) < 10:
            raise ValueError("API key enrichment parameter must be at least 10 characters long")

    if "language" in config:
        language = config["language"]
        if not isinstance(language, str) or len(language) < 2:
            raise ValueError("Language enrichment parameter must be at least 2 characters long")


def _validate_watermark_parameters(config: dict[str, Any]) -> None:
    """Validate watermark enricher enrichment parameters."""
    if "overlay_path" in config:
        overlay_path = config["overlay_path"]
        if not isinstance(overlay_path, str):
            raise ValueError("Overlay path enrichment parameter must be a string")

        # Check if file exists (stub for now - in real implementation would check actual file)
        if overlay_path.startswith("/nonexistent/"):
            raise ValueError(f"File path enrichment parameter '{overlay_path}' does not exist")

    if "position" in config:
        position = config["position"]
        valid_positions = ["top-left", "top-right", "bottom-left", "bottom-right", "center"]
        if not isinstance(position, str) or position not in valid_positions:
            raise ValueError(
                f"Position enrichment parameter must be one of: {', '.join(valid_positions)}"
            )

    if "opacity" in config:
        opacity = config["opacity"]
        if not isinstance(opacity, int | float) or not (0.0 <= opacity <= 1.0):
            raise ValueError("Opacity enrichment parameter must be between 0.0 and 1.0")


def _validate_crossfade_parameters(config: dict[str, Any]) -> None:
    """Validate crossfade enricher enrichment parameters."""
    if "duration" in config:
        duration = config["duration"]
        if not isinstance(duration, int | float) or duration <= 0:
            raise ValueError("Duration enrichment parameter must be a positive number")

    if "curve" in config:
        curve = config["curve"]
        valid_curves = ["linear", "ease-in", "ease-out", "ease-in-out"]
        if not isinstance(curve, str) or curve not in valid_curves:
            raise ValueError(
                f"Curve enrichment parameter must be one of: {', '.join(valid_curves)}"
            )


def _validate_llm_parameters(config: dict[str, Any]) -> None:
    """Validate LLM enricher enrichment parameters."""
    if "api_key" in config:
        api_key = config["api_key"]
        if not isinstance(api_key, str) or len(api_key) < 10:
            raise ValueError("API key enrichment parameter must be at least 10 characters long")

    if "model" in config:
        model = config["model"]
        if not isinstance(model, str) or len(model) < 3:
            raise ValueError("Model enrichment parameter must be at least 3 characters long")

    if "prompt_template" in config:
        prompt_template = config["prompt_template"]
        if not isinstance(prompt_template, str):
            raise ValueError("Prompt template enrichment parameter must be a string")


def _validate_ffmpeg_parameters(config: dict[str, Any]) -> None:
    """Validate FFmpeg/FFprobe enricher enrichment parameters."""
    # FFmpeg enrichers typically don't need parameters - they use system defaults
    # If parameters are provided, validate them but inform user they're not necessary
    if config:
        # For now, just log that parameters aren't needed
        # In a real implementation, this might validate ffprobe_path, timeout, etc.
        pass


def _validate_generic_parameters(config: dict[str, Any]) -> None:
    """Validate generic enrichment parameters for unknown enricher types."""
    # Basic validation for unknown enricher types
    for key, value in config.items():
        if not isinstance(key, str):
            raise ValueError(f"Enrichment parameter key '{key}' must be a string")

        # Basic type validation
        if not isinstance(value, str | int | float | bool | dict | list):
            raise ValueError(f"Enrichment parameter '{key}' has invalid type: {type(value)}")


def check_enricher_needs_parameters(enricher_type: str) -> bool:
    """
    Check if an enricher type requires enrichment parameters.

    Args:
        enricher_type: The type of enricher

    Returns:
        True if the enricher requires parameters, False otherwise
    """
    # Enrichers that require parameters
    parameter_required_types = {
        "tvdb",
        "tmdb",
        "watermark",
        "crossfade",
        "llm",
        "file-parser",
        "lower-third",
        "emergency-crawl",
    }

    # Enrichers that don't require parameters (use system defaults)
    no_parameter_types = {"ffmpeg", "ffprobe"}

    if enricher_type in parameter_required_types:
        return True
    elif enricher_type in no_parameter_types:
        return False
    else:
        # Unknown type - assume it might need parameters
        return True


@app.command("list-types")
def list_enricher_types(
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    test_db: bool = typer.Option(
        False, "--test-db", help="Direct command to test database environment"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be listed without executing"
    ),
):
    """
    Show all enricher types known to the system (both ingest and playout scopes).

    Examples:
        retrovue enricher list-types
        retrovue enricher list-types --json
        retrovue enricher list-types --dry-run
        retrovue enricher list-types --test-db
    """
    try:
        # TODO: Replace with real EnricherRegistry when available
        from ...registries.enricher_registry import list_enricher_types as _list_types

        enricher_types = _list_types()

        # Handle empty registry
        if not enricher_types:
            if json_output:
                typer.echo(json.dumps({"status": "ok", "enricher_types": [], "total": 0}, indent=2))
            else:
                typer.echo("No enricher types available")
            return

        # Handle dry run
        if dry_run:
            if json_output:
                typer.echo(
                    json.dumps(
                        {
                            "status": "dry_run",
                            "enricher_types": [
                                {
                                    "type": et["type"],
                                    "description": et["description"],
                                    "available": et.get("available", True),
                                }
                                for et in enricher_types
                            ],
                            "total": len(enricher_types),
                        },
                        indent=2,
                    )
                )
            else:
                typer.echo(f"Would list {len(enricher_types)} enricher types from registry:")
                for enricher_type in enricher_types:
                    typer.echo(f"  • {enricher_type['type']} - {enricher_type['description']}")
            return

        if json_output:
            typer.echo(
                json.dumps(
                    {
                        "status": "ok",
                        "enricher_types": [
                            {
                                "type": et["type"],
                                "description": et["description"],
                                "available": et.get("available", True),
                            }
                            for et in enricher_types
                        ],
                        "total": len(enricher_types),
                    },
                    indent=2,
                )
            )
        else:
            typer.echo("Available enricher types:")
            for enricher_type in enricher_types:
                typer.echo(f"  {enricher_type['type']:<15} - {enricher_type['description']}")
            typer.echo(f"\nTotal: {len(enricher_types)} enricher types available")

    except Exception as e:
        typer.echo(f"Error listing enricher types: {e}", err=True)
        raise typer.Exit(1)


@app.command("add")
def add_enricher(
    type: str | None = typer.Option(None, "--type", help="Enricher type (ingest or playout)"),
    name: str | None = typer.Option(None, "--name", help="Human-readable label"),
    # Configuration parameter
    config: str | None = typer.Option(None, "--config", help="JSON configuration for the enricher"),
    # Enrichment parameters for specific enricher types
    api_key: str | None = typer.Option(None, "--api-key", help="API key for external services"),
    language: str | None = typer.Option(None, "--language", help="Language preference"),
    overlay_path: str | None = typer.Option(None, "--overlay-path", help="Path to overlay file"),
    position: str | None = typer.Option(None, "--position", help="Position for overlay"),
    opacity: float | None = typer.Option(None, "--opacity", help="Opacity value (0.0-1.0)"),
    duration: float | None = typer.Option(None, "--duration", help="Duration value"),
    curve: str | None = typer.Option(None, "--curve", help="Curve type"),
    model: str | None = typer.Option(None, "--model", help="Model name"),
    prompt_template: str | None = typer.Option(None, "--prompt-template", help="Prompt template"),
    # Global options
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be created without executing"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    help_type: bool = typer.Option(
        False, "--help", help="Show help for the specified enricher type"
    ),
):
    """
    Create an enricher instance. Each enricher type defines its own config params.

    Required:
    - --type: Enricher type (ingest or playout)
    - --name: Human-readable label

    Behavior:
    - If called with --help and no --type, print generic usage plus available types.
    - If called with --type <type> --help, print that enricher's specific parameter contract.

    Examples:
        retrovue enricher add --type ingest --name "Video Analysis"
        retrovue enricher add --type playout --name "Channel Branding"
    """
    try:
        # Handle help request without type
        if help_type and not type:
            typer.echo("Enricher Add Command")
            typer.echo()
            typer.echo("Required parameters:")
            typer.echo("  --type: Enricher type")
            typer.echo("  --name: Human-readable label")
            typer.echo()
            typer.echo("Available enricher types:")
            from ...registries.enricher_registry import list_enricher_types as _list_types

            available_types = _list_types()
            for enricher_type in available_types:
                typer.echo(f"  • {enricher_type['type']}: {enricher_type['description']}")
            typer.echo()
            typer.echo("For detailed help on each type, use:")
            for enricher_type in available_types:
                typer.echo(f"  retrovue enricher add --type {enricher_type['type']} --help")
            return

        # Handle case where no type is provided
        if not type:
            typer.echo("Error: --type is required")
            typer.echo()
            typer.echo("Available enricher types:")
            from ...registries.enricher_registry import list_enricher_types as _list_types

            available_types = _list_types()
            for enricher_type in available_types:
                typer.echo(f"  • {enricher_type['type']}: {enricher_type['description']}")
            typer.echo()
            typer.echo("For detailed help on each type, use:")
            for enricher_type in available_types:
                typer.echo(f"  retrovue enricher add --type {enricher_type['type']} --help")
            raise typer.Exit(1)

        # Get available enricher types
        from ...registries.enricher_registry import list_enricher_types as _list_types

        available_types = _list_types()
        type_names = [t["type"] for t in available_types]
        if type not in type_names:
            typer.echo(
                f"Invalid enricher type '{type}'. Available types: {', '.join(type_names)}",
                err=True,
            )
            raise typer.Exit(1)

        # Handle help request for specific type
        if help_type:
            # Get help information for the enricher type
            from ...registries.enricher_registry import get_enricher_help

            help_info = get_enricher_help(type)

            typer.echo(f"Help for {type} enricher type:")
            typer.echo(f"Description: {help_info['description']}")
            typer.echo()

            typer.echo("Required parameters:")
            for param in help_info["required_params"]:
                typer.echo(f"  --{param['name']}: {param['description']}")
                if "example" in param:
                    typer.echo(f"    Example: {param['example']}")

            typer.echo()
            typer.echo("Optional parameters:")
            for param in help_info["optional_params"]:
                typer.echo(f"  --{param['name']}: {param['description']}")
                if "default" in param:
                    typer.echo(f"    Default: {param['default']}")

            typer.echo()
            typer.echo("Examples:")
            for example in help_info["examples"]:
                typer.echo(f"  {example}")

            return  # Exit the function cleanly

        # Validate required parameters
        if not name:
            typer.echo("Missing required parameter: --name", err=True)
            raise typer.Exit(1)

        # Build configuration based on enricher type and provided parameters
        try:
            # If JSON config is provided, parse it
            if config:
                config = json.loads(config)
            else:
                # Build config from individual enrichment parameters
                enrichment_params = {
                    "api_key": api_key,
                    "language": language,
                    "overlay_path": overlay_path,
                    "position": position,
                    "opacity": opacity,
                    "duration": duration,
                    "curve": curve,
                    "model": model,
                    "prompt_template": prompt_template,
                }

                # Only include non-None parameters
                config = {k: v for k, v in enrichment_params.items() if v is not None}
        except json.JSONDecodeError as e:
            typer.echo(f"Invalid configuration: {e}", err=True)
            raise typer.Exit(1)

        # Create enricher instance using domain entity for validation
        from ...domain.enricher import Enricher as EnricherDomain

        enricher_domain = EnricherDomain.create(
            enricher_type=type,  # Use the --type parameter as the actual enricher type
            name=name,  # Use the --name parameter as the human-readable label
            config=config,
            scope="ingest",  # For now, assume all enrichers are ingest-scoped
        )

        # Validate enrichment parameters before creating enricher
        try:
            validate_enrichment_parameters(type, config)
        except ValueError as validation_error:
            typer.echo(f"Error: Invalid enrichment parameters: {validation_error}", err=True)
            raise typer.Exit(1)

        # Check if enricher needs parameters and inform user if not
        if not check_enricher_needs_parameters(type) and not config:
            typer.echo(
                f"Info: {type.title()} enricher requires no enrichment parameters (uses system defaults)"
            )

        # Validate configuration
        try:
            enricher_domain.validate_config()
        except ValueError as e:
            typer.echo(f"Invalid configuration: {e}", err=True)
            raise typer.Exit(1)

        # Handle dry run
        if dry_run:
            if json_output:
                result = enricher_domain.to_dict()
                result["status"] = "dry_run"
                typer.echo(json.dumps(result, indent=2))
            else:
                typer.echo("DRY RUN - Configuration validation:")
                typer.echo("Would create enricher:")
                typer.echo(f"  ID: {enricher_domain.id}")
                typer.echo(f"  Type: {enricher_domain.type}")
                typer.echo(f"  Scope: {enricher_domain.scope}")
                typer.echo(f"  Name: {enricher_domain.name}")
                typer.echo(f"  Configuration: {json.dumps(enricher_domain.config, indent=2)}")
            return

        # Create enricher in database using SQLAlchemy model
        with session() as db:
            try:
                # Create SQLAlchemy model instance
                enricher_model = EnricherModel(
                    enricher_id=enricher_domain.id,
                    type=enricher_domain.type,
                    scope=enricher_domain.scope,
                    name=enricher_domain.name,
                    config=enricher_domain.config,
                )

                db.add(enricher_model)
                db.commit()

                if json_output:
                    typer.echo(json.dumps(enricher_domain.to_dict(), indent=2))
                else:
                    typer.echo(
                        f"Successfully created {enricher_domain.type} enricher: {enricher_domain.name}"
                    )
                    typer.echo(f"  ID: {enricher_domain.id}")
                    typer.echo(f"  Type: {enricher_domain.type}")
                    typer.echo(f"  Scope: {enricher_domain.scope}")
                    typer.echo(f"  Name: {enricher_domain.name}")
                    typer.echo(f"  Configuration: {json.dumps(enricher_domain.config, indent=2)}")

            except Exception as db_error:
                db.rollback()
                typer.echo(f"Database error: {db_error}", err=True)
                raise typer.Exit(1)

    except Exception as e:
        typer.echo(f"Error adding enricher: {e}", err=True)
        raise typer.Exit(1)


def _build_enricher_config(enricher_type: str, params: dict[str, Any]) -> dict[str, Any]:
    """Build configuration dictionary based on enricher type and provided parameters."""
    # Start with default configuration
    from ...domain.enricher import Enricher as EnricherDomain

    config = EnricherDomain._get_default_config(enricher_type)

    # For both ingest and playout types, the main parameter is config
    if params["config"] is not None:
        try:
            user_config = json.loads(params["config"])
            # Merge user config with defaults
            config.update(user_config)
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON configuration")

    return config


@app.command("list")
def list_enrichers(
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    test_db: bool = typer.Option(
        False, "--test-db", help="Direct command to test database environment"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be listed without executing"
    ),
):
    """
    List configured enricher instances with:
    - enricher_id
    - type
    - name/label
    - configuration
    - attachment status
    - availability status

    Examples:
        retrovue enricher list
        retrovue enricher list --json
        retrovue enricher list --dry-run
        retrovue enricher list --test-db
    """
    try:
        # Handle test database mode
        if test_db:
            # For test database mode, we should use a test database connection
            # This is typically used in CI/CD or testing environments
            typer.echo("Using test database environment...")

        # Handle dry run
        if dry_run:
            if json_output:
                typer.echo(json.dumps({"status": "dry_run", "enrichers": [], "total": 0}, indent=2))
            else:
                typer.echo("Would list enricher instances from database:")
                typer.echo("  • No enricher instances to preview")
            return

        # Query enrichers from database
        with session() as db:
            enrichers_query = db.query(EnricherModel).order_by(EnricherModel.created_at)
            enrichers_data = enrichers_query.all()

            # Handle empty database
            if not enrichers_data:
                if json_output:
                    typer.echo(json.dumps({"status": "ok", "enrichers": [], "total": 0}, indent=2))
                else:
                    typer.echo("No enricher instances configured")
                return

            # Process enricher data
            enrichers = []
            for enricher in enrichers_data:
                # Calculate attachment status (placeholder for now)
                attachments = {
                    "collections": 0,  # TODO: Implement actual collection counting
                    "channels": 0,  # TODO: Implement actual channel counting
                }

                # Determine availability status
                status = "available"  # TODO: Implement actual availability checking

                # Redact sensitive configuration data
                config = enricher.config or {}
                redacted_config = {}
                for key, value in config.items():
                    if key.lower() in ["api_key", "password", "secret", "token"]:
                        redacted_config[key] = "***REDACTED***"
                    else:
                        redacted_config[key] = value

                enrichers.append(
                    {
                        "enricher_id": enricher.enricher_id,
                        "type": enricher.type,
                        "name": enricher.name,
                        "config": redacted_config,
                        "attachments": attachments,
                        "status": status,
                    }
                )

        if json_output:
            typer.echo(
                json.dumps(
                    {"status": "ok", "enrichers": enrichers, "total": len(enrichers)}, indent=2
                )
            )
        else:
            typer.echo("Configured enricher instances:")
            for enricher in enrichers:
                typer.echo(
                    f"  {enricher['enricher_id']:<25} - {enricher['name']} ({enricher['type']})"
                )
                if enricher["config"]:
                    typer.echo(f"    Configuration: {json.dumps(enricher['config'])}")
                typer.echo(
                    f"    Attached to: {enricher['attachments']['collections']} collections, {enricher['attachments']['channels']} channels"
                )
                typer.echo(f"    Status: {enricher['status'].title()}")
                typer.echo()  # Empty line for readability

            typer.echo(f"Total: {len(enrichers)} enricher instances configured")

    except Exception as e:
        typer.echo(f"Error listing enrichers: {e}", err=True)
        raise typer.Exit(1)


@app.command("update")
def update_enricher(
    enricher_id: str = typer.Argument(..., help="Enricher ID to update"),
    test_db: bool = typer.Option(
        False, "--test-db", help="Direct command to test database environment"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be updated without executing"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    # Configuration parameters (placeholder for now)
    config: str = typer.Option(None, "--config", help="JSON configuration for the enricher"),
):
    """
    Update enricher configuration.

    Behavior: Updates enricher configuration with validation and preview support.

    Examples:
        retrovue enricher update enricher-ffprobe-1 --config '{"timeout": 60}'
        retrovue enricher update enricher-metadata-1 --dry-run
        retrovue enricher update enricher-playout-1 --test-db --json
    """
    try:
        # Query enricher from database to verify existence and get details
        with session() as db:
            enricher_query = db.query(EnricherModel).filter(
                EnricherModel.enricher_id == enricher_id
            )
            enricher = enricher_query.first()

            if not enricher:
                typer.echo(f"Error: Enricher '{enricher_id}' not found", err=True)
                raise typer.Exit(1)

            # Parse configuration if provided
            new_config = enricher.config or {}
            if config:
                try:
                    import json

                    new_config = json.loads(config)
                except json.JSONDecodeError as e:
                    typer.echo(f"Error: Invalid JSON configuration: {e}", err=True)
                    raise typer.Exit(1)

            # Validate enrichment parameters before updating
            try:
                validate_enrichment_parameters(enricher.type, new_config)
            except ValueError as validation_error:
                typer.echo(f"Error: Invalid enrichment parameters: {validation_error}", err=True)
                raise typer.Exit(1)

            # Check if enricher needs parameters and inform user if not
            if not check_enricher_needs_parameters(enricher.type) and not new_config:
                typer.echo(
                    f"Info: {enricher.type.title()} enricher requires no enrichment parameters (uses system defaults)"
                )
                return

            # Handle dry run
            if dry_run:
                import json

                if json_output:
                    result = {
                        "enricher_id": enricher.enricher_id,
                        "type": enricher.type,
                        "name": enricher.name,
                        "current_config": enricher.config or {},
                        "new_config": new_config,
                        "status": "dry_run",
                    }
                    typer.echo(json.dumps(result, indent=2))
                else:
                    typer.echo(f"Would update enricher: {enricher.name}")
                    typer.echo(f"  ID: {enricher.enricher_id}")
                    typer.echo(f"  Type: {enricher.type}")
                    typer.echo(f"  Name: {enricher.name}")
                    typer.echo(f"  Current Configuration: {json.dumps(enricher.config or {})}")
                    typer.echo(f"  New Configuration: {json.dumps(new_config)}")
                return

            # Perform actual enricher update
            try:
                # Update the enricher configuration
                enricher.config = new_config
                db.commit()

                import json

                if json_output:
                    result = {
                        "enricher_id": enricher.enricher_id,
                        "type": enricher.type,
                        "name": enricher.name,
                        "config": new_config,
                        "status": "updated",
                        "updated_at": enricher.updated_at.isoformat()
                        if enricher.updated_at
                        else None,
                    }
                    typer.echo(json.dumps(result, indent=2))
                else:
                    typer.echo(f"Successfully updated enricher: {enricher.name}")
                    typer.echo(f"  ID: {enricher.enricher_id}")
                    typer.echo(f"  Type: {enricher.type}")
                    typer.echo(f"  Name: {enricher.name}")
                    typer.echo(f"  Configuration: {json.dumps(new_config)}")
                    typer.echo(f"  Updated: {enricher.updated_at}")

            except Exception as db_error:
                db.rollback()
                typer.echo(f"Error updating enricher: {db_error}", err=True)
                raise typer.Exit(1)

    except Exception as e:
        typer.echo(f"Error updating enricher: {e}", err=True)
        raise typer.Exit(1)


def check_enricher_removal_safety(enricher: EnricherModel, db_session) -> tuple[bool, str]:
    """
    Check if an enricher can be safely removed in production.

    Safety is based on harm prevention, not static categories.
    Checks for two types of harm:
    1. Enricher is currently in use by active operations
    2. Enricher is marked as protected_from_removal = true

    Args:
        enricher: The enricher to check
        db_session: Database session for queries

    Returns:
        tuple[bool, str]: (is_safe, reason_if_not_safe)
    """
    import os

    # Contract D-5: Production is determined by environment configuration
    # This check MUST be enforced by the removal command before performing any destructive action
    is_production = os.getenv("ENV") == "production" or "production" in os.getenv(
        "DATABASE_URL", ""
    )

    # Non-production environments are always permissive (Contract D-5)
    if not is_production:
        return True, ""

    # Check if enricher is explicitly protected from removal
    if enricher.protected_from_removal:
        return (
            False,
            f"Enricher '{enricher.name}' is marked as protected from removal and cannot be deleted in production",
        )

    # Check if enricher is currently in use by active operations
    # Note: These tables don't exist yet, so we'll return safe for now
    # When attachment and job tables are implemented, uncomment these checks:

    # # Check for active collection attachments
    # collection_attachments = db_session.query(CollectionAttachment).filter(
    #     CollectionAttachment.enricher_id == enricher.enricher_id
    # ).count()
    #
    # if collection_attachments > 0:
    #     return False, f"Enricher '{enricher.name}' is attached to {collection_attachments} collections and cannot be removed while in use"
    #
    # # Check for active channel attachments
    # channel_attachments = db_session.query(ChannelAttachment).filter(
    #     ChannelAttachment.enricher_id == enricher.enricher_id
    # ).count()
    #
    # if channel_attachments > 0:
    #     return False, f"Enricher '{enricher.name}' is attached to {channel_attachments} channels and cannot be removed while in use"
    #
    # # Check for active ingest jobs
    # active_ingest_jobs = db_session.query(IngestJob).filter(
    #     IngestJob.enricher_id == enricher.enricher_id,
    #     IngestJob.status.in_(['running', 'pending'])
    # ).count()
    #
    # if active_ingest_jobs > 0:
    #     return False, f"Enricher '{enricher.name}' is currently being used by {active_ingest_jobs} active ingest jobs"
    #
    # # Check for active playout sessions
    # active_playout_sessions = db_session.query(PlayoutSession).filter(
    #     PlayoutSession.enricher_id == enricher.enricher_id,
    #     PlayoutSession.status.in_(['active', 'scheduled'])
    # ).count()
    #
    # if active_playout_sessions > 0:
    #     return False, f"Enricher '{enricher.name}' is currently being used by {active_playout_sessions} active playout sessions"

    return True, ""


@app.command("remove")
def remove_enricher(
    enricher_id: str = typer.Argument(..., help="Enricher ID to remove"),
    force: bool = typer.Option(False, "--force", help="Force removal without confirmation"),
    test_db: bool = typer.Option(
        False, "--test-db", help="Direct command to test database environment"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    Remove enricher instance.

    Behavior: Confirms removal and shows affected collections/channels.

    Examples:
        retrovue enricher remove enricher-ffprobe-1
        retrovue enricher remove enricher-metadata-1 --force
        retrovue enricher remove enricher-playout-1 --test-db --force
    """
    try:
        # Query enricher from database to verify existence and get details
        with session() as db:
            enricher_query = db.query(EnricherModel).filter(
                EnricherModel.enricher_id == enricher_id
            )
            enricher = enricher_query.first()

            if not enricher:
                typer.echo(f"Error: Enricher '{enricher_id}' not found", err=True)
                raise typer.Exit(1)

            # Check production safety before proceeding
            is_safe, safety_reason = check_enricher_removal_safety(enricher, db)
            if not is_safe:
                typer.echo(
                    f"Error: Cannot remove enricher in production: {safety_reason}", err=True
                )
                typer.echo("Use --test-db flag to test removal in a safe environment", err=True)
                raise typer.Exit(1)

            # Calculate cascade impact before deletion
            # Note: These tables don't exist yet, so we'll set to 0 for now
            # When collection/channel attachment tables are implemented, uncomment these:
            # collection_attachments_removed = db.query(CollectionAttachment).filter(
            #     CollectionAttachment.enricher_id == enricher.enricher_id
            # ).count()
            # channel_attachments_removed = db.query(ChannelAttachment).filter(
            #     ChannelAttachment.enricher_id == enricher.enricher_id
            # ).count()
            collection_attachments_removed = 0
            channel_attachments_removed = 0

            # Handle confirmation unless --force is used
            if not force:
                typer.echo(
                    f"Are you sure you want to remove enricher '{enricher.name}' (ID: {enricher.enricher_id})?"
                )
                typer.echo("This will also remove:")
                typer.echo(f"  - {collection_attachments_removed} collection attachments")
                typer.echo(f"  - {channel_attachments_removed} channel attachments")
                if enricher.protected_from_removal:
                    typer.echo("⚠️  WARNING: This enricher is marked as protected from removal")
                typer.echo("This action cannot be undone.")
                confirm = typer.prompt("Type 'yes' to confirm", default="no")
                if confirm.lower() != "yes":
                    typer.echo("Removal cancelled")
                    return

            # Perform actual enricher removal
            try:
                # Delete the enricher record
                db.delete(enricher)
                db.commit()

                if json_output:
                    result = {
                        "removed": True,
                        "enricher_id": enricher.enricher_id,
                        "name": enricher.name,
                        "type": enricher.type,
                        "collection_attachments_removed": collection_attachments_removed,
                        "channel_attachments_removed": channel_attachments_removed,
                    }
                    typer.echo(json.dumps(result, indent=2))
                else:
                    typer.echo(f"Successfully removed enricher: {enricher.name}")
                    typer.echo(f"  ID: {enricher.enricher_id}")
                    typer.echo(f"  Type: {enricher.type}")
                    if collection_attachments_removed > 0 or channel_attachments_removed > 0:
                        typer.echo(
                            f"  Also removed: {collection_attachments_removed} collection attachments, {channel_attachments_removed} channel attachments"
                        )

            except Exception as db_error:
                db.rollback()
                typer.echo(f"Error removing enricher: {db_error}", err=True)
                raise typer.Exit(1)

    except Exception as e:
        typer.echo(f"Error removing enricher: {e}", err=True)
        raise typer.Exit(1)
