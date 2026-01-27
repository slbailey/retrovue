"""
Program Director CLI commands.

Provides commands to start the ProgramDirector which serves as the
control plane inside RetroVue, routing viewer requests to ChannelManagers.
"""

import typer
from pathlib import Path
from retrovue.runtime.channel_manager_daemon import ChannelManagerDaemon
from retrovue.runtime.program_director import ProgramDirector

app = typer.Typer(help="Retrovue Program Director commands")


@app.command("start")
def start(
    schedule_dir: str = typer.Option(None, help="Directory containing schedule.json files (required for Phase 8)"),
    port: int = typer.Option(8000, help="Port for ProgramDirector HTTP server"),
    channel_manager_port: int = typer.Option(9000, help="Port for ChannelManager (internal)"),
    # Phase 0 options
    phase0: bool = typer.Option(False, help="Enable Phase 0 mode (grid + filler model)"),
    phase0_program_asset: str = typer.Option(None, help="Phase 0: Path to program asset (MP4 file)"),
    phase0_program_duration: float = typer.Option(None, help="Phase 0: Program duration in seconds"),
    phase0_filler_asset: str = typer.Option(None, help="Phase 0: Path to filler asset (MP4 file)"),
    phase0_filler_duration: float = typer.Option(3600.0, help="Phase 0: Filler duration in seconds (default: 3600)"),
):
    """
    Starts RetroVue with ProgramDirector as the control plane.
    
    ProgramDirector is the control plane inside RetroVue that:
    - Exposes HTTP endpoints (GET /channels, GET /channels/{id}.ts, POST /admin/emergency)
    - Routes viewer tune requests to ChannelManager
    - Owns and manages FanoutBuffers per channel
    - Stops playout engine pipelines when last viewer disconnects
    
    Phase 0 mode:
    - Uses fixed 30-minute grid with program + filler model
    - Requires --phase0-program-asset, --phase0-program-duration, and --phase0-filler-asset
    - Does not require schedule_dir (uses grid-based scheduling)
    """
    # Validate Phase 0 configuration
    if phase0:
        if not phase0_program_asset:
            typer.echo("Error: Phase 0 mode requires --phase0-program-asset", err=True)
            raise typer.Exit(1)
        if phase0_program_duration is None:
            typer.echo("Error: Phase 0 mode requires --phase0-program-duration", err=True)
            raise typer.Exit(1)
        if not phase0_filler_asset:
            typer.echo("Error: Phase 0 mode requires --phase0-filler-asset", err=True)
            raise typer.Exit(1)
        # Verify asset files exist
        if not Path(phase0_program_asset).exists():
            typer.echo(f"Error: Program asset not found: {phase0_program_asset}", err=True)
            raise typer.Exit(1)
        if not Path(phase0_filler_asset).exists():
            typer.echo(f"Error: Filler asset not found: {phase0_filler_asset}", err=True)
            raise typer.Exit(1)
    else:
        if not schedule_dir:
            typer.echo("Error: Phase 8 mode requires --schedule-dir", err=True)
            raise typer.Exit(1)
    
    # Create RetroVue Core runtime (implements ChannelManagerProvider)
    if phase0:
        channel_manager = ChannelManagerDaemon(
            schedule_dir=Path("/tmp"),  # Dummy path for Phase 0 (not used)
            port=channel_manager_port,
            phase0_mode=True,
            phase0_program_asset_path=phase0_program_asset,
            phase0_program_duration_seconds=phase0_program_duration,
            phase0_filler_asset_path=phase0_filler_asset,
            phase0_filler_duration_seconds=phase0_filler_duration,
        )
    else:
        channel_manager = ChannelManagerDaemon(
            schedule_dir=Path(schedule_dir),
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
