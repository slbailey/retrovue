"""
Program Director CLI commands.

Provides commands to start the ProgramDirector which serves as the
control plane inside RetroVue, routing viewer requests to ChannelManagers.
"""

import logging
import typer
from pathlib import Path
from retrovue.runtime.channel_manager_daemon import ChannelManagerDaemon
from retrovue.runtime.program_director import ProgramDirector

app = typer.Typer(help="Retrovue Program Director commands")


@app.command("start")
def start(
    schedule_dir: str = typer.Option(None, help="Directory containing schedule.json files (Phase 8); if omitted, use mock schedule (channel 'mock', assets/samplecontent.mp4)"),
    port: int = typer.Option(8000, help="Port for ProgramDirector HTTP server"),
    channel_manager_port: int = typer.Option(9000, help="Port for ChannelManager (internal)"),
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
    
    ProgramDirector is the control plane inside RetroVue that:
    - Exposes HTTP endpoints (GET /channels, GET /channels/{id}.ts, POST /admin/emergency)
    - Routes viewer tune requests to ChannelManager
    - Owns and manages FanoutBuffers per channel
    - Stops playout engine pipelines when last viewer disconnects
    
    Mock grid (--mock-schedule-grid):
    - Uses fixed 30-minute grid with program + filler model
    - Requires --program-asset, --program-duration, and --filler-asset
    - Does not require schedule_dir (uses grid-based scheduling)

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
    # Create RetroVue Core runtime (implements ChannelManagerProvider)
    if mock_schedule_ab:
        channel_manager = ChannelManagerDaemon(
            schedule_dir=Path("/tmp"),  # Dummy path for mock A/B (not used)
            port=channel_manager_port,
            mock_schedule_ab_mode=True,
            asset_a_path=asset_a,
            asset_b_path=asset_b,
            segment_seconds=segment_seconds,
        )
    elif mock_schedule_grid:
        channel_manager = ChannelManagerDaemon(
            schedule_dir=Path("/tmp"),  # Dummy path for mock grid (not used)
            port=channel_manager_port,
            mock_schedule_grid_mode=True,
            program_asset_path=program_asset,
            program_duration_seconds=program_duration,
            filler_asset_path=filler_asset,
            filler_duration_seconds=filler_duration,
        )
    else:
        channel_manager = ChannelManagerDaemon(
            schedule_dir=Path(schedule_dir) if schedule_dir else None,  # None = built-in mock schedule
            port=channel_manager_port,  # Internal port for ChannelManager
        )
    
    # Create ProgramDirector with RetroVue Core runtime as provider
    program_director = ProgramDirector(
        channel_manager_provider=channel_manager,
        host="0.0.0.0",
        port=port,
    )
    
    # Start both components
    # ChannelManagerDaemon.start() blocks (runs uvicorn server), so start it in a thread
    import threading
    
    def start_channel_manager():
        channel_manager.start()
    
    cm_thread = threading.Thread(target=start_channel_manager, name="channel-manager", daemon=True)
    cm_thread.start()
    
    # Start ProgramDirector (this will start its HTTP server in a background thread)
    program_director.start()
    
    # Keep main thread alive and handle shutdown
    try:
        import time
        print(f"ProgramDirector started on port {port}")
        print(f"ChannelManager running on port {channel_manager_port} (internal)")
        print("Press Ctrl+C to stop...")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        program_director.stop()
        channel_manager.stop()
