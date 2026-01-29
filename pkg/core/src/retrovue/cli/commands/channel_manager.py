import typer
from pathlib import Path
from retrovue.runtime.channel_manager_daemon import ChannelManagerDaemon
from retrovue.runtime.providers import FileChannelConfigProvider

app = typer.Typer(help="Retrovue Channel Manager commands")

@app.command("start")
def start(
    schedule_dir: str = typer.Option(..., help="Directory containing schedule.json files"),
    port: int = typer.Option(9000, help="Port to serve the HTTP API and TS streams"),
    channel_config: str = typer.Option(
        None,
        help="Path to channels.json config file (default: /opt/retrovue/config/channels.json)"
    ),
):
    """
    Starts the RetroVue Core runtime.

    This is an internal command. Most users should use 'retrovue program-director start' instead.
    """
    # Load channel config provider if specified or use default location
    config_provider = None
    if channel_config:
        config_path = Path(channel_config)
    else:
        # Default location
        config_path = Path("/opt/retrovue/config/channels.json")

    if config_path.exists():
        config_provider = FileChannelConfigProvider(config_path)
        typer.echo(f"Loading channel config from: {config_path}")

    daemon = ChannelManagerDaemon(
        schedule_dir=Path(schedule_dir),
        port=port,
        channel_config_provider=config_provider,
    )
    daemon.start()
