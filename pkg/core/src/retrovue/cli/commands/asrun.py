"""As-run log inspection and validation commands."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

app = typer.Typer(name="asrun", help="As-run log inspection and validation")

ASRUN_DIR = Path("/opt/retrovue/data/logs/asrun")

# Fallback types produced by AIR's SegmentTypeName() enum mapper.
# These are UPPERCASE strings derived from the 3-value SegmentType enum.
# If ALL segment types are in this set, the editorial enrichment
# pipeline is not working (Core is not setting segment_type_name,
# or AIR is not reading it).
# Lowercase types ("content", "commercial", "presentation", etc.)
# are editorial pass-through values — their presence means enrichment works.
_FALLBACK_TYPES = {"CONTENT", "FILLER", "PAD"}


def _load_jsonl(channel: str, date: str) -> list[dict]:
    """Load and parse a .asrun.jsonl file. Exits on error."""
    path = ASRUN_DIR / channel / f"{date}.asrun.jsonl"
    if not path.exists():
        typer.echo(f"Error: file not found: {path}", err=True)
        raise typer.Exit(1)

    records = []
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                typer.echo(
                    f"Warning: skipping malformed line {lineno}: {e}",
                    err=True,
                )
    return records


@app.command("doctor")
def doctor(
    channel: str = typer.Option(..., "--channel", "-c", help="Channel slug"),
    date: str = typer.Option(..., "--date", "-d", help="Date (YYYY-MM-DD)"),
) -> None:
    """Run health checks on an as-run log file."""
    records = _load_jsonl(channel, date)

    seg_starts = [r for r in records if r.get("status") == "SEG_START"]
    block_starts = [r for r in records if r.get("status") == "START"]

    typer.echo("=== ASRUN DOCTOR ===")
    typer.echo(f"Channel: {channel}")
    typer.echo(f"Date:    {date}")
    typer.echo(f"Records: {len(records)} total, {len(seg_starts)} segment starts, {len(block_starts)} block starts")
    typer.echo()

    ok = True

    # ── Check 1: Type enrichment ──────────────────────────────────────
    if seg_starts:
        seg_types = {r.get("segment_type", "") for r in seg_starts}
        all_fallback = seg_types and seg_types <= _FALLBACK_TYPES

        if all_fallback:
            typer.echo(
                f"  \u2717 Type enrichment NOT working (fallback only)\n"
                f"    All {len(seg_starts)} segments have types: {sorted(seg_types)}\n"
                f"    Expected editorial types: commercial, presentation, bumper, etc.\n"
                f"    Likely cause: AIR binary not rebuilt after proto change"
            )
            ok = False
        else:
            editorial_types = seg_types - _FALLBACK_TYPES
            typer.echo(
                f"  \u2713 Type enrichment OK\n"
                f"    Editorial types present: {sorted(editorial_types)}"
            )

        # Type distribution summary
        from collections import Counter
        type_counts = Counter(r.get("segment_type", "?") for r in seg_starts)
        typer.echo()
        typer.echo("    Type distribution:")
        for t, c in type_counts.most_common():
            typer.echo(f"      {t:<20s} {c:>4d} segments")
    else:
        typer.echo("  ? No SEG_START records found — nothing to check")

    typer.echo()

    # ── Check 2: Segment index uniqueness ─────────────────────────────
    seen_pairs: set[tuple[str, int]] = set()
    duplicates: list[tuple[str, int]] = []
    for r in seg_starts:
        block_id = r.get("block_id", "")
        seg_idx = r.get("segment_index", -1)
        pair = (block_id, seg_idx)
        if pair in seen_pairs:
            duplicates.append(pair)
        else:
            seen_pairs.add(pair)

    if duplicates:
        typer.echo(
            f"  \u2717 Duplicate segment_index detected ({len(duplicates)} duplicates)"
        )
        for block_id, seg_idx in duplicates[:5]:
            typer.echo(f"    block={block_id} segment_index={seg_idx}")
        if len(duplicates) > 5:
            typer.echo(f"    ... and {len(duplicates) - 5} more")
        ok = False
    else:
        typer.echo(
            f"  \u2713 Segment indexes OK ({len(seen_pairs)} unique across {len(set(r.get('block_id') for r in seg_starts))} blocks)"
        )

    typer.echo()

    # ── Summary ───────────────────────────────────────────────────────
    if ok:
        typer.echo("Result: HEALTHY")
    else:
        typer.echo("Result: ISSUES DETECTED")
        raise typer.Exit(1)
