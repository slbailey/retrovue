"""
Program Director CLI commands.

Provides commands to start the ProgramDirector which serves as the
control plane inside RetroVue. ProgramDirector owns the ChannelManager
registry (creation, health ticking, fanout attachment, teardown); there
is no separate daemon. Single HTTP server, single port.
"""

import logging
import typer
from pathlib import Path
from retrovue.runtime.program_director import ProgramDirector
from retrovue.runtime.config import RuntimeConfig
from retrovue.runtime.providers import FileChannelConfigProvider, YamlChannelConfigProvider

app = typer.Typer(help="Retrovue Program Director commands")


@app.command("start")
def start(
    config_file: str = typer.Option(None, "--config", "-c", help="Path to retrovue.json (default: auto-detect)"),
    port: int = typer.Option(None, help="Port for HTTP server (default: from config or 8000)"),
    # Mock schedule: grid + filler (no real schedule)
    mock_schedule_grid: bool = typer.Option(False, help="Use mock grid schedule (program + filler on 30-minute grid)"),
    program_asset: str = typer.Option(None, help="Mock grid: Path to program asset (MP4 file)"),
    program_duration: float = typer.Option(None, help="Mock grid: Program duration in seconds"),
    filler_asset: str = typer.Option(None, help="Mock grid: Path to filler asset (MP4 file)"),
    filler_duration: float = typer.Option(3600.0, help="Mock grid: Filler duration in seconds (default: 3600)"),
    # Mock schedule: A/B alternating (Air harness; channel test-1)
    mock_schedule_ab: bool = typer.Option(False, help="Use mock A/B schedule: alternating asset A and B every N seconds, 24/7 (channel test-1)"),
    asset_a: str = typer.Option(None, help="Mock A/B: Path to asset A (e.g. SampleA.mp4)"),
    asset_b: str = typer.Option(None, help="Mock A/B: Path to asset B (e.g. SampleB.mp4)"),
    segment_seconds: float = typer.Option(10.0, help="Mock A/B: Segment length in seconds (default: 10)"),
):
    """
    Starts RetroVue with ProgramDirector as the control plane.

    Configuration is loaded from (in order):
    1. --config FILE (if specified)
    2. config/retrovue.json (relative to cwd)
    3. /opt/retrovue/config/retrovue.json
    4. Built-in defaults

    With no arguments, starts with config file settings or defaults.
    CLI options override config file values when specified.

    ProgramDirector is the control plane inside RetroVue that:
    - Exposes HTTP endpoints (GET /channels, GET /channel/{id}.ts, POST /admin/emergency)
    - Routes viewer tune requests to ChannelManager
    - Owns and manages FanoutBuffers per channel
    - Stops playout engine pipelines when last viewer disconnects

    Mock grid (--mock-schedule-grid):
    - Uses fixed 30-minute grid with program + filler model
    - Requires --program-asset, --program-duration, and --filler-asset

    Mock A/B (--mock-schedule-ab): Air harness for channel test-1
    - Alternating asset A and B every N seconds, 24/7
    - Requires --asset-a and --asset-b; optional --segment-seconds (default 10)
    - Mutually exclusive with --mock-schedule-grid.
    """
    if mock_schedule_ab and mock_schedule_grid:
        typer.echo("Error: Use either --mock-schedule-ab or --mock-schedule-grid, not both", err=True)
        raise typer.Exit(1)

    # Ensure INFO logs (channel create/destroy, subscriber count) are visible in the console
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:     %(message)s",
        force=True,
    )

    # Load runtime configuration from file (or defaults)
    runtime_config = RuntimeConfig.load(config_file)

    # CLI options override config file values (single port; no separate daemon)
    http_port = port if port is not None else runtime_config.program_director_port

    # Load channel config provider — prefer YAML channels dir, fall back to channels.json
    channel_config_provider = None
    yaml_channels_dir = Path("/opt/retrovue/config/channels")
    if yaml_channels_dir.is_dir():
        channel_config_provider = YamlChannelConfigProvider(yaml_channels_dir)
    else:
        channels_config_path = runtime_config.get_channels_config_path()
        if channels_config_path.exists():
            channel_config_provider = FileChannelConfigProvider(channels_config_path)

    if not mock_schedule_ab and not mock_schedule_grid and channel_config_provider is None:
        typer.echo(
            "Error: Channel config is required. Create a channels config file (e.g. config/channels.json) "
            "or use --mock-schedule-ab / --mock-schedule-grid for testing.",
            err=True,
        )
        raise typer.Exit(1)

    # Validate mock A/B configuration
    if mock_schedule_ab:
        if not asset_a:
            typer.echo("Error: Mock A/B requires --asset-a", err=True)
            raise typer.Exit(1)
        if not asset_b:
            typer.echo("Error: Mock A/B requires --asset-b", err=True)
            raise typer.Exit(1)
        if not Path(asset_a).exists():
            typer.echo(f"Error: Asset A not found: {asset_a}", err=True)
            raise typer.Exit(1)
        if not Path(asset_b).exists():
            typer.echo(f"Error: Asset B not found: {asset_b}", err=True)
            raise typer.Exit(1)
    # Validate mock grid configuration
    if mock_schedule_grid:
        if not program_asset:
            typer.echo("Error: Mock grid requires --program-asset", err=True)
            raise typer.Exit(1)
        if program_duration is None:
            typer.echo("Error: Mock grid requires --program-duration", err=True)
            raise typer.Exit(1)
        if not filler_asset:
            typer.echo("Error: Mock grid requires --filler-asset", err=True)
            raise typer.Exit(1)
        # Verify asset files exist
        if not Path(program_asset).exists():
            typer.echo(f"Error: Program asset not found: {program_asset}", err=True)
            raise typer.Exit(1)
        if not Path(filler_asset).exists():
            typer.echo(f"Error: Filler asset not found: {filler_asset}", err=True)
            raise typer.Exit(1)
    # Create ProgramDirector with embedded ChannelManager registry (single component, single port)
    if mock_schedule_ab:
        program_director = ProgramDirector(
            host="0.0.0.0",
            port=http_port,
            channel_config_provider=channel_config_provider,
            mock_schedule_ab_mode=True,
            asset_a_path=asset_a,
            asset_b_path=asset_b,
            segment_seconds=segment_seconds,
        )
    elif mock_schedule_grid:
        program_director = ProgramDirector(
            host="0.0.0.0",
            port=http_port,
            channel_config_provider=channel_config_provider,
            mock_schedule_grid_mode=True,
            program_asset_path=program_asset,
            program_duration_seconds=program_duration,
            filler_asset_path=filler_asset,
            filler_duration_seconds=filler_duration,
        )
    else:
        program_director = ProgramDirector(
            host="0.0.0.0",
            port=http_port,
            channel_config_provider=channel_config_provider,
        )

    program_director.start()

    try:
        import time
        print(f"ProgramDirector started on port {http_port}")
        print("Press Ctrl+C to stop...")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        program_director.stop()
