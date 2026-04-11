"""
Config CLI commands.

Provides commands to manage RetroVue configuration at runtime.
"""

import typer
import urllib.request
import urllib.error
import json

app = typer.Typer(help="Configuration management commands")


@app.command("reload")
def reload(
    port: int = typer.Option(8000, help="ProgramDirector HTTP port"),
    host: str = typer.Option("127.0.0.1", help="ProgramDirector host"),
):
    """Reload channel YAML configs on the running server.

    Invalidates all config caches so the next schedule compilation,
    horizon expansion, or traffic fill picks up updated YAML files.
    Active channels are not interrupted.
    """
    url = f"http://{host}:{port}/admin/reload-config"
    try:
        req = urllib.request.Request(url, method="POST", data=b"")
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read())
            typer.echo(f"OK: {body.get('message', 'reloaded')}")
            for item in body.get("reloaded", []):
                typer.echo(f"  - {item}")
    except urllib.error.URLError as e:
        typer.echo(f"Error: Could not connect to server at {url}: {e}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
