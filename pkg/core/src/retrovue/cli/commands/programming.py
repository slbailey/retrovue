"""
Programming DSL CLI commands.

Provides compile, validate, and expand subcommands for the Programming DSL.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

app = typer.Typer(name="programming", help="Programming DSL compile, validate, and expand operations")


@app.command("compile")
def compile_cmd(
    dsl_file: str = typer.Argument(..., help="Path to DSL YAML file"),
    output: str = typer.Option(None, "--output", "-o", help="Output JSON file (stdout if omitted)"),
    git_commit: str = typer.Option("0000000", "--git-commit", help="Git commit hash for provenance"),
    seed: int = typer.Option(42, "--seed", help="Random seed for deterministic selection"),
) -> None:
    """Compile a Programming DSL YAML file into a Program Schedule JSON (grid-aligned program blocks only)."""
    from retrovue.runtime.asset_resolver import StubAssetResolver
    from retrovue.runtime.schedule_compiler import (
        CompileError,
        ValidationError,
        compile_schedule,
        parse_dsl,
    )

    path = Path(dsl_file)
    if not path.exists():
        typer.echo(f"Error: File not found: {dsl_file}", err=True)
        raise typer.Exit(1)

    yaml_text = path.read_text()
    try:
        dsl = parse_dsl(yaml_text)
    except Exception as e:
        typer.echo(f"Error: Failed to parse YAML: {e}", err=True)
        raise typer.Exit(1)

    resolver = StubAssetResolver()

    try:
        plan = compile_schedule(
            dsl, resolver, dsl_path=str(path), git_commit=git_commit, seed=seed,
        )
    except ValidationError as e:
        typer.echo("Validation errors:", err=True)
        for err in e.errors:
            typer.echo(f"  - {err}", err=True)
        raise typer.Exit(1)
    except CompileError as e:
        typer.echo(f"Compile error: {e}", err=True)
        raise typer.Exit(1)

    json_out = json.dumps(plan, indent=2, default=str)
    if output:
        Path(output).write_text(json_out)
        typer.echo(f"Written to {output}")
    else:
        typer.echo(json_out)


@app.command("validate")
def validate_cmd(
    dsl_file: str = typer.Argument(..., help="Path to DSL YAML file"),
) -> None:
    """Validate a Programming DSL YAML file without compiling."""
    from retrovue.runtime.asset_resolver import StubAssetResolver
    from retrovue.runtime.schedule_compiler import parse_dsl, validate_dsl

    path = Path(dsl_file)
    if not path.exists():
        typer.echo(f"Error: File not found: {dsl_file}", err=True)
        raise typer.Exit(1)

    yaml_text = path.read_text()
    try:
        dsl = parse_dsl(yaml_text)
    except Exception as e:
        typer.echo(f"Error: Failed to parse YAML: {e}", err=True)
        raise typer.Exit(1)

    resolver = StubAssetResolver()
    errors = validate_dsl(dsl, resolver)

    if errors:
        typer.echo("Validation errors:", err=True)
        for err in errors:
            typer.echo(f"  - {err}", err=True)
        raise typer.Exit(1)
    else:
        typer.echo("✓ DSL is valid")


@app.command("expand")
def expand_cmd(
    asset_id: str = typer.Argument(..., help="Asset ID of the program block"),
    asset_uri: str = typer.Argument(..., help="File path to the episode/movie"),
    title: str = typer.Option("Program", "--title", help="Program title"),
    start_utc_ms: int = typer.Option(0, "--start-utc-ms", help="Block start time in UTC ms"),
    slot_duration_ms: int = typer.Option(1_800_000, "--slot-duration-ms", help="Slot duration in ms"),
    episode_duration_ms: int = typer.Option(1_320_000, "--episode-duration-ms", help="Episode duration in ms"),
    chapter_markers: str = typer.Option(None, "--chapter-markers", help="Comma-separated chapter marker times in ms"),
    num_breaks: int = typer.Option(3, "--num-breaks", help="Number of ad breaks if no chapter markers"),
    filler_uri: str = typer.Option(None, "--filler-uri", help="Path to filler.mp4 (fills ad blocks if provided)"),
    filler_duration_ms: int = typer.Option(30_000, "--filler-duration-ms", help="Filler duration in ms"),
) -> None:
    """Expand a program block into a ScheduledBlock playout log (for debugging)."""
    from retrovue.runtime.playout_log_expander import expand_program_block

    markers: tuple[int, ...] | None = None
    if chapter_markers:
        markers = tuple(int(x.strip()) for x in chapter_markers.split(","))

    block = expand_program_block(
        asset_id=asset_id,
        asset_uri=asset_uri,
        start_utc_ms=start_utc_ms,
        slot_duration_ms=slot_duration_ms,
        episode_duration_ms=episode_duration_ms,
        chapter_markers_ms=markers,
        num_breaks=num_breaks,
    )

    if filler_uri:
        from retrovue.runtime.traffic_manager import fill_ad_blocks
        block = fill_ad_blocks(block, filler_uri, filler_duration_ms)

    typer.echo(f"ScheduledBlock: {block.block_id}")
    typer.echo(f"  {block.start_utc_ms} → {block.end_utc_ms} ({block.duration_ms}ms)")
    typer.echo(f"  Segments ({len(block.segments)}):")
    for seg in block.segments:
        typer.echo(f"    [{seg.segment_type}] uri={seg.asset_uri or '(black)'} offset={seg.asset_start_offset_ms}ms dur={seg.segment_duration_ms}ms")


@app.command("rebuild")
def rebuild_cmd(
    date_str: str = typer.Argument(..., help="Broadcast date to rebuild (YYYY-MM-DD)"),
    channel_id: str = typer.Option(None, "--channel", "-c", help="Channel ID (rebuilds all channels if omitted)"),
) -> None:
    """Force-recompile a locked broadcast day by deleting the cached row and recompiling."""
    from datetime import date

    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        typer.echo(f"Error: Invalid date format '{date_str}'. Use YYYY-MM-DD.", err=True)
        raise typer.Exit(1)

    from retrovue.domain.entities import CompiledProgramLog
    from retrovue.infra.uow import session

    with session() as db:
        query = db.query(CompiledProgramLog).filter(
            CompiledProgramLog.broadcast_day == target_date,
        )
        if channel_id:
            query = query.filter(CompiledProgramLog.channel_id == channel_id)

        deleted = query.delete(synchronize_session=False)

    if deleted:
        typer.echo(f"Deleted {deleted} cached schedule(s) for {date_str}. They will recompile on next access.")
    else:
        typer.echo(f"No cached schedules found for {date_str}.")
