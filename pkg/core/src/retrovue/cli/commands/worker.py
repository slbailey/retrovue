"""CLI commands for the processor job worker."""

from __future__ import annotations

import typer

from ...runtime.processor_worker import run_once, run_loop

app = typer.Typer(name="worker", help="Processor job queue worker")


@app.command("run")
def run(
    once: bool = typer.Option(False, "--once", help="Process a single job then exit"),
    iterations: int | None = typer.Option(None, "--iterations", "-n", help="Max number of jobs to process (default: until queue empty)"),
):
    """Run the processor worker: claim jobs from the queue and execute them."""
    if once:
        processed = run_once()
        if not processed:
            typer.echo("No job available.")
    else:
        count = run_loop(iterations=iterations)
        typer.echo(f"Processed {count} job(s).")
