"""
Producer CLI commands for producer management.

Surfaces producer management capabilities including listing, configuration, and management.
"""

from __future__ import annotations

import typer

app = typer.Typer(name="producer", help="Producer management operations")


@app.command("list-types")
def list_producer_types(
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    Show available producer types (linear, prevue, yule-log, etc.).

    Examples:
        retrovue producer list-types
        retrovue producer list-types --json
    """
    try:
        from ...registries.producer_registry import list_producer_types as _list_types

        producer_types = _list_types()

        if json_output:
            import json

            typer.echo(json.dumps(producer_types, indent=2))
        else:
            typer.echo("Available producer types:")
            for producer_type in producer_types:
                typer.echo(f"  - {producer_type['type']}: {producer_type['description']}")

    except Exception as e:
        typer.echo(f"Error listing producer types: {e}", err=True)
        raise typer.Exit(1)


@app.command("add")
def add_producer(
    type: str | None = typer.Option(None, "--type", help="Producer type"),
    name: str | None = typer.Option(None, "--name", help="Human-readable label"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    help_type: bool = typer.Option(
        False, "--help", help="Show help for the specified producer type"
    ),
):
    """
    Create a producer instance.

    Required:
    - --type: Producer type
    - --name: Human-readable label

    Behavior:
    - If called with --help and no --type, print generic usage plus available types.
    - If called with --type <type> --help, print that producer's specific parameter contract.

    Examples:
        retrovue producer add --type linear --name "Linear TV Producer"
        retrovue producer add --type prevue --name "Prevue Producer"
    """
    try:
        # Handle case where no type is provided
        if not type:
            typer.echo("Error: --type is required")
            typer.echo()
            typer.echo("Available producer types:")
            from ...registries.producer_registry import list_producer_types as _list_types

            available_types = _list_types()
            for producer_type in available_types:
                typer.echo(f"  • {producer_type['type']}: {producer_type['description']}")
            typer.echo()
            typer.echo("For detailed help on each type, use:")
            for producer_type in available_types:
                typer.echo(f"  retrovue producer add --type {producer_type['type']} --help")
            raise typer.Exit(1)

        # Get available producer types
        from ...registries.producer_registry import get_producer_help, list_producer_types as _list_types

        available_types = _list_types()
        type_names = [t["type"] for t in available_types]
        if type not in type_names:
            typer.echo(
                f"Error: Unknown producer type '{type}'. Available types: {', '.join(type_names)}",
                err=True,
            )
            raise typer.Exit(1)

        # Handle help request for specific type
        if help_type:
            # Get help information for the producer type
            help_info = get_producer_help(type)

            typer.echo(f"Help for {type} producer type:")
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
            typer.echo("Error: --name is required", err=True)
            raise typer.Exit(1)

        # TODO: Implement actual producer creation logic
        # For now, just echo success
        if json_output:
            import json

            result = {
                "producer_id": f"producer-{type}-{name.lower().replace(' ', '-')}",
                "type": type,
                "name": name,
                "status": "created",
            }
            typer.echo(json.dumps(result, indent=2))
        else:
            typer.echo(f"Successfully created {type} producer: {name}")
            typer.echo(f"  Type: {type}")
            typer.echo(f"  Name: {name}")
            typer.echo("  Status: created (TODO: implement actual creation)")

    except Exception as e:
        typer.echo(f"Error adding producer: {e}", err=True)
        raise typer.Exit(1)


@app.command("list")
def list_producers(
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    List configured producer instances.

    Output: Table showing producer_id, type, name, status.

    Examples:
        retrovue producer list
        retrovue producer list --json
    """
    try:
        # TODO: Replace with real producer listing logic
        producers = [
            {
                "producer_id": "producer-linear-1",
                "type": "linear",
                "name": "Linear TV Producer",
                "status": "active",
            },
            {
                "producer_id": "producer-preview-1",
                "type": "preview",
                "name": "Preview Producer",
                "status": "inactive",
            },
        ]

        if json_output:
            import json

            typer.echo(json.dumps(producers, indent=2))
        else:
            typer.echo("Configured producer instances:")
            for producer in producers:
                typer.echo(
                    f"  - {producer['producer_id']}: {producer['name']} ({producer['type']}, {producer['status']})"
                )

    except Exception as e:
        typer.echo(f"Error listing producers: {e}", err=True)
        raise typer.Exit(1)


@app.command("update")
def update_producer(
    producer_id: str = typer.Argument(..., help="Producer ID to update"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    Update producer configuration.

    Parameters: Same as add command for the producer type.

    Examples:
        retrovue producer update producer-linear-1
    """
    try:
        # TODO: Implement actual producer update logic
        typer.echo(f"TODO: Update producer {producer_id}")
        typer.echo("This command will update the producer configuration.")
        typer.echo("Parameters: Same as add command for the producer type.")

    except Exception as e:
        typer.echo(f"Error updating producer: {e}", err=True)
        raise typer.Exit(1)


@app.command("remove")
def remove_producer(
    producer_id: str = typer.Argument(..., help="Producer ID to remove"),
    force: bool = typer.Option(False, "--force", help="Force removal without confirmation"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    Remove producer instance.

    Behavior: Confirms removal and shows affected channels.

    Examples:
        retrovue producer remove producer-linear-1
        retrovue producer remove producer-preview-1 --force
    """
    try:
        if not force:
            typer.echo(f"Are you sure you want to remove producer '{producer_id}'?")
            typer.echo("This action cannot be undone.")
            confirm = typer.prompt("Type 'yes' to confirm", default="no")
            if confirm.lower() != "yes":
                typer.echo("Removal cancelled")
                raise typer.Exit(0)

        # TODO: Implement actual producer removal logic
        if json_output:
            import json

            result = {"removed": True, "producer_id": producer_id}
            typer.echo(json.dumps(result, indent=2))
        else:
            typer.echo(f"Successfully removed producer: {producer_id}")
            typer.echo("TODO: Show affected channels")

    except Exception as e:
        typer.echo(f"Error removing producer: {e}", err=True)
        raise typer.Exit(1)
