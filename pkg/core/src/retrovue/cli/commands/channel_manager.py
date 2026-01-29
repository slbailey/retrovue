"""
Channel Manager CLI commands.

Alias for program-director: starts ProgramDirector with embedded ChannelManager
registry. Same runtime as 'retrovue program-director start'; different default
port (9000) for backward compatibility.
"""

import logging
import time
import typer
from pathlib import Path
from retrovue.runtime.program_director import ProgramDirector
from retrovue.runtime.providers import FileChannelConfigProvider

app = typer.Typer(help="Retrovue Channel Manager commands (alias for program-director)")


@app.command("start")
def start(
    schedule_dir: str = typer.Option(..., help="Directory containing schedule.json files"),
    port: int = typer.Option(9000, help="Port to serve the HTTP API and TS streams"),
    channel_config: str = typer.Option(
        None,
        help="Path to channels.json config file (default: /opt/retrovue/config/channels.json)",
    ),
):
    """
    Starts the RetroVue Core runtime (ProgramDirector with embedded ChannelManager registry).

    Alias for 'retrovue program-director start' with schedule_dir and port.
    Default port is 9000 for backward compatibility; use program-director start for default 8000.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:     %(message)s",
        force=True,
    )
    config_provider = None
    if channel_config:
        config_path = Path(channel_config)
    else:
        config_path = Path("/opt/retrovue/config/channels.json")
    if config_path.exists():
        config_provider = FileChannelConfigProvider(config_path)
        typer.echo(f"Loading channel config from: {config_path}")

    program_director = ProgramDirector(
        host="0.0.0.0",
        port=port,
        schedule_dir=Path(schedule_dir),
        channel_config_provider=config_provider,
    )
    program_director.start()
    try:
        typer.echo(f"ProgramDirector started on port {port}")
        typer.echo("Press Ctrl+C to stop...")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        typer.echo("\nShutting down...")
        program_director.stop()


@app.command("start-channel")
def start_channel_cmd(
    channel_id: str = typer.Argument(..., help="Channel ID to start (e.g. retro1)"),
    schedule_dir: str = typer.Option(..., help="Directory containing schedule.json files"),
    port: int = typer.Option(9000, help="Port to serve the HTTP API and TS streams"),
    channel_config: str = typer.Option(
        None,
        help="Path to channels.json config file (default: /opt/retrovue/config/channels.json)",
    ),
    grace_period: int = typer.Option(
        30,
        "--grace-period",
        help="Seconds to wait for a viewer to connect before tearing down (default: 30); ignored with --dry-run",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Only call start_channel and exit (test that channel starts with these params); do not start server",
    ),
):
    """
    Start a single channel using the same function ProgramDirector uses when a viewer tunes in.

    CLI-started channels have no viewer yet. A grace period (--grace-period, default 30s) gives
    time for a viewer to connect; if none connect, the channel is torn down. When ProgramDirector
    starts a channel because a viewer tuned in, it tears down as soon as viewer count = 0 (no grace).
    Builds ProgramDirector, calls start_channel(channel_id, pre_warmed_grace_seconds=grace_period),
    then (unless --dry-run) starts the server.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:     %(message)s",
        force=True,
    )
    config_provider = None
    if channel_config:
        config_path = Path(channel_config)
    else:
        config_path = Path("/opt/retrovue/config/channels.json")
    if config_path.exists():
        config_provider = FileChannelConfigProvider(config_path)
        typer.echo(f"Loading channel config from: {config_path}")

    program_director = ProgramDirector(
        host="0.0.0.0",
        port=port,
        schedule_dir=Path(schedule_dir),
        channel_config_provider=config_provider,
    )
    # CLI-started channel: pass grace period so channel tears down if no viewer connects in time
    pre_warmed_grace = None if dry_run else grace_period
    program_director.start_channel(channel_id, pre_warmed_grace_seconds=pre_warmed_grace)
    typer.echo(f"Started channel {channel_id} (same code path as ProgramDirector)")
    if dry_run:
        typer.echo("Dry run: not starting server.")
        return
    program_director.start()
    try:
        typer.echo(f"ProgramDirector started on port {port}; channel {channel_id} pre-warmed (grace period {grace_period}s)")
        typer.echo("Press Ctrl+C to stop...")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        typer.echo("\nShutting down...")
        program_director.stop()
