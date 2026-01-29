"""
Main CLI application using Typer with router-based command dispatch.

This module provides the command-line interface for Retrovue,
calling application services and outputting JSON when requested.

All command groups are registered through the centralized CliRouter,
ensuring explicit registration and documentation mapping.
"""

from __future__ import annotations

import typer

# Ensure registry is populated
import retrovue.adapters.importers  # noqa: F401

from .commands import asset as asset_cmd
from .commands import (
    channel,
    channel_manager,
    collection,
    enricher,
    producer,
    program_director,
    runtime,
    source,
    zone,
)
from .router import get_router

app = typer.Typer(help="RetroVue operator CLI")

# Initialize router and register all command groups
router = get_router(app)

# Register command groups with explicit documentation mapping
router.register(
    "source",
    source.app,
    help_text="Source and collection management operations",
    doc_path="source.md",
)

router.register(
    "channel",
    channel.app,
    help_text="Broadcast channel operations",
    doc_path="channel.md",
)

router.register(
    "collection",
    collection.app,
    help_text="Collection management operations",
    doc_path="collection.md",
)

router.register(
    "asset",
    asset_cmd.app,
    help_text="Asset inspection and review operations",
    doc_path="asset.md",
)

router.register(
    "enricher",
    enricher.app,
    help_text="Enricher management operations",
    doc_path="enricher.md",
)

router.register(
    "producer",
    producer.app,
    help_text="Producer management operations",
    doc_path="producer.md",
)

router.register(
    "runtime",
    runtime.app,
    help_text="Runtime diagnostics and validation operations",
    doc_path="runtime.md",
)

router.register(
    "channel-manager",
    channel_manager.app,
    help_text="RetroVue Core runtime operations (internal)",
    doc_path="channel-manager.md",
)

router.register(
    "program-director",
    program_director.app,
    help_text="Program Director operations (control plane)",
    doc_path="program-director.md",
)

router.register(
    "zone",
    zone.app,
    help_text="Zone (daypart) management operations",
    doc_path="zone.md",
)


@app.command("start")
def start_alias(
    config_file: str = typer.Option(None, "--config", "-c", help="Path to retrovue.json"),
    port: int = typer.Option(None, help="Override ProgramDirector HTTP port"),
):
    """Start RetroVue (alias for program-director start)."""
    from retrovue.cli.commands.program_director import start as pd_start
    pd_start(
        config_file=config_file,
        schedule_dir=None,
        port=port,
        mock_schedule_grid=False,
        program_asset=None,
        program_duration=None,
        filler_asset=None,
        filler_duration=3600.0,
        mock_schedule_ab=False,
        asset_a=None,
        asset_b=None,
        segment_seconds=10.0,
    )



@app.callback()
def main(
    ctx: typer.Context,
    json: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """Retrovue - Retro IPTV Simulation Project."""
    # Store JSON flag in context for subcommands to use
    ctx.ensure_object(dict)
    ctx.obj["json"] = json


def cli():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    cli()
