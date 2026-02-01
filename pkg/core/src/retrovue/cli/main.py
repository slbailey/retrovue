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
    channel_id: str = typer.Argument(None, help="Channel ID to start directly (e.g., cheers-24-7). If omitted, starts ProgramDirector."),
    config_file: str = typer.Option(None, "--config", "-c", help="Path to retrovue.json"),
    port: int = typer.Option(None, help="Override ProgramDirector HTTP port"),
    socket_path: str = typer.Option(None, "--socket", "-s", help="Override UDS socket path for direct channel start"),
):
    """Start RetroVue. With channel_id, starts that channel directly. Without, starts ProgramDirector."""
    if channel_id:
        # Direct channel start - bypass ProgramDirector, launch AIR directly
        _start_channel_direct(channel_id, config_file, socket_path)
    else:
        # Full ProgramDirector start
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


def _start_channel_direct(channel_id: str, config_file: str | None, socket_path: str | None):
    """Start a channel directly without ProgramDirector - for testing socket connectivity."""
    import signal
    import sys
    import json
    from pathlib import Path
    from retrovue.usecases.channel_manager_launch import launch_air, terminate_air
    from retrovue.runtime.config import ChannelConfig

    # Load channel config
    config_path = Path(config_file) if config_file else Path("/opt/retrovue/config/channels.json")
    if not config_path.exists():
        typer.echo(f"Error: Channel config not found: {config_path}", err=True)
        raise typer.Exit(1)

    with open(config_path) as f:
        channels_data = json.load(f)

    # Find the channel
    channel_data = None
    for ch in channels_data.get("channels", []):
        if ch.get("channel_id") == channel_id:
            channel_data = ch
            break

    if not channel_data:
        typer.echo(f"Error: Channel '{channel_id}' not found in {config_path}", err=True)
        typer.echo(f"Available channels: {[c.get('channel_id') for c in channels_data.get('channels', [])]}", err=True)
        raise typer.Exit(1)

    # Build channel config using from_dict for proper deserialization
    config_data = {
        "channel_id": channel_data["channel_id"],
        "channel_id_int": channel_data.get("channel_id_int", 1),
        "name": channel_data.get("name", channel_id),
        "program_format": channel_data.get("program_format", {
            "video": {"width": 1920, "height": 1080, "frame_rate": "30/1"},
            "audio": {"sample_rate": 48000, "channels": 2}
        }),
        "schedule_source": channel_data.get("schedule_source", "file"),
        "schedule_config": channel_data.get("schedule_config", {}),
    }
    channel_config = ChannelConfig.from_dict(config_data)

    # Get first asset from schedule (or use a default test asset)
    schedule_path = Path(f"/opt/retrovue/config/schedules/{channel_id}.json")
    asset_path = "/opt/retrovue/assets/SampleA.mp4"  # default fallback

    if schedule_path.exists():
        with open(schedule_path) as f:
            schedule_data = json.load(f)
        # Try to get first slot's asset
        slots = schedule_data.get("slots", [])
        if slots:
            program_ref = slots[0].get("program_ref", {})
            program_id = program_ref.get("id")
            if program_id:
                program_path = Path(f"/opt/retrovue/config/programs/{program_id}.json")
                if program_path.exists():
                    with open(program_path) as f:
                        program_data = json.load(f)
                    episodes = program_data.get("episodes", [])
                    if episodes:
                        asset_path = episodes[0].get("asset_path", asset_path)

    # Use socket path for easy socat testing
    # NOTE: Must use a subdirectory (not /tmp directly) because ensure_socket_dir_exists
    # will chmod the parent directory, which fails on /tmp.
    if socket_path:
        ts_socket = socket_path
    else:
        ts_socket = f"/tmp/retrovue/{channel_id}.sock"

    # Ensure directory exists and remove existing socket if present
    sock_path = Path(ts_socket)
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    if sock_path.exists():
        sock_path.unlink()

    typer.echo(f"Starting channel: {channel_id}")
    typer.echo(f"Socket path: {ts_socket}")
    typer.echo(f"Asset: {asset_path}")
    typer.echo(f"Program format: {channel_config.program_format.to_json()}")
    typer.echo("")
    typer.echo("To test with socat (in another terminal):")
    typer.echo(f"  socat -v UNIX-LISTEN:{ts_socket},fork -")
    typer.echo("")
    typer.echo("Press Ctrl+C to stop...")
    typer.echo("")

    playout_request = {
        "channel_id": channel_id,
        "asset_path": asset_path,
        "start_pts": 0,
    }

    proc = None
    try:
        proc, actual_socket, reader_queue, grpc_addr = launch_air(
            playout_request=playout_request,
            channel_config=channel_config,
            ts_socket_path=ts_socket,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        typer.echo(f"AIR started, gRPC at {grpc_addr}")
        typer.echo(f"Actual socket: {actual_socket}")

        # Wait for Ctrl+C
        def signal_handler(sig, frame):
            typer.echo("\nShutting down...")
            if proc:
                terminate_air(proc)
            raise typer.Exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Keep running
        proc.wait()

    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        if proc:
            terminate_air(proc)
        raise typer.Exit(1)



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
