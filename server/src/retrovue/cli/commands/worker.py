"""CLI commands for the processor job worker."""

from __future__ import annotations

import typer

from ...infra.settings import settings
from ...runtime.processor_worker import run_once, run_loop

app = typer.Typer(name="worker", help="Processor job queue worker")


@app.command("run")
def run(
    once: bool = typer.Option(False, "--once", help="Process a single job then exit"),
    iterations: int | None = typer.Option(None, "--iterations", "-n", help="Max number of jobs to process (default: until queue empty)"),
    poll: bool = typer.Option(False, "--poll", help="Keep running: sleep and re-check when the queue is empty"),
    interval: int = typer.Option(30, "--interval", help="Seconds to sleep between poll cycles (default: 30)"),
):
    """Run the processor worker: claim jobs from the queue and execute them."""
    if once:
        processed = run_once()
        if not processed:
            typer.echo("No job available.")
    else:
        count = run_loop(iterations=iterations, poll=poll, interval=interval)
        typer.echo(f"Processed {count} job(s).")


@app.command("purge")
def purge(
    retention_days: int | None = typer.Option(
        None,
        "--retention-days",
        "-d",
        help="Delete completed/failed jobs older than this many days (default: from PROCESSOR_JOB_RETENTION_DAYS)",
    ),
):
    """Purge old completed/failed processor jobs (and their runs) to keep the table size bounded."""
    from ...catalog.processor_jobs import purge_old_processor_jobs
    from ...infra.uow import session

    days = retention_days if retention_days is not None else settings.processor_job_retention_days
    if days <= 0:
        typer.echo("Retention days must be > 0 (or set PROCESSOR_JOB_RETENTION_DAYS). Skipping purge.")
        raise typer.Exit(0)
    with session() as db:
        deleted = purge_old_processor_jobs(db, days)
    typer.echo(f"Purged {deleted} completed/failed processor job(s) older than {days} days.")
