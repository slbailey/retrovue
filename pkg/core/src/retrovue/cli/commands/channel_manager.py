import typer
from pathlib import Path
from retrovue.runtime.channel_manager_daemon import ChannelManagerDaemon

app = typer.Typer(help="Retrovue Channel Manager commands")

@app.command("start")
def start(
    schedule_dir: str = typer.Option(..., help="Directory containing schedule.json files"),
    port: int = typer.Option(9000, help="Port to serve the HTTP API and TS streams")
):
    """
    Starts the RetroVue Core runtime.
    
    This is an internal command. Most users should use 'retrovue program-director start' instead.
    """
    daemon = ChannelManagerDaemon(
        schedule_dir=Path(schedule_dir),
        port=port,
    )
    daemon.start()
