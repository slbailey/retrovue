#!/usr/bin/env python3
"""
Build or update an asset catalog by probing media files with ffprobe.

Parameterized per-program: each invocation adds/updates one program's
episodes in the shared catalog.  Run multiple times for different shows.

Usage:
    python tools/build_catalog.py \
      --media-dir "/mnt/data/media/tv/Cheers (1982) {imdb-tt0083399}/Season 01" \
      --program-id cheers \
      --program-name "Cheers" \
      --filler /opt/retrovue/assets/filler.mp4

    python tools/build_catalog.py \
      --media-dir "/mnt/data/media/tv/Seinfeld (1989)/Season 03" \
      --program-id seinfeld \
      --program-name "Seinfeld"
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

MEDIA_EXTENSIONS = {".mp4", ".mkv"}

# Sonarr-style: "Show (Year) - S01E02 - Title [quality]..."
EPISODE_RE = re.compile(
    r"^(?P<show>.+?)\s*"           # show name (greedy-minimal)
    r"(?:\(\d{4}\)\s*)?-?\s*"      # optional (year) and separator
    r"S(?P<season>\d{2})"          # S01
    r"E(?P<episode>\d{2})"         # E02
    r"(?:\s*-\s*(?P<title>[^[\]]+?))?"  # optional " - Title"
    r"\s*(?:\[.*)?$",              # optional [quality...] tail
    re.IGNORECASE,
)


def probe_file(path: str) -> dict:
    """Run ffprobe on a file, return parsed JSON."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_chapters",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def extract_duration_ms(probe: dict) -> int:
    """Extract duration in milliseconds from ffprobe output."""
    dur_str = probe.get("format", {}).get("duration", "0")
    return int(float(dur_str) * 1000)


def extract_markers(probe: dict) -> list[dict]:
    """Extract chapter markers from ffprobe output."""
    markers = []
    for ch in probe.get("chapters", []):
        offset_ms = int(float(ch.get("start_time", "0")) * 1000)
        label = ch.get("tags", {}).get("title", "")
        markers.append({
            "kind": "chapter",
            "offset_ms": offset_ms,
            "label": label,
        })
    return markers


def parse_episode_filename(filename: str) -> dict | None:
    """Parse Sonarr-style filename into episode metadata."""
    stem = Path(filename).stem
    m = EPISODE_RE.match(stem)
    if not m:
        return None
    title = (m.group("title") or "").strip()
    return {
        "season": int(m.group("season")),
        "episode": int(m.group("episode")),
        "title": title,
    }


def discover_media(media_dir: str) -> list[Path]:
    """Find all media files in directory, sorted by name."""
    d = Path(media_dir)
    if not d.is_dir():
        print(f"Error: {media_dir} is not a directory", file=sys.stderr)
        sys.exit(1)
    files = sorted(
        f for f in d.iterdir()
        if f.is_file() and f.suffix.lower() in MEDIA_EXTENSIONS
    )
    return files


def load_catalog(catalog_path: Path) -> dict:
    """Load existing catalog or return empty skeleton."""
    if catalog_path.exists():
        with open(catalog_path) as f:
            return json.load(f)
    return {"catalog_version": 1, "generated_at": "", "assets": {}}


def save_catalog(catalog: dict, catalog_path: Path) -> None:
    """Write catalog JSON."""
    catalog["generated_at"] = datetime.now(timezone.utc).isoformat()
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    with open(catalog_path, "w") as f:
        json.dump(catalog, f, indent=2)
        f.write("\n")


def save_program(program: dict, programs_dir: Path) -> None:
    """Write per-program JSON."""
    programs_dir.mkdir(parents=True, exist_ok=True)
    out = programs_dir / f"{program['program_id']}.json"
    with open(out, "w") as f:
        json.dump(program, f, indent=2)
        f.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Probe media files and build/update an asset catalog."
    )
    parser.add_argument(
        "--media-dir", required=True,
        help="Directory containing episode media files (.mp4, .mkv)",
    )
    parser.add_argument(
        "--program-id", required=True,
        help="Identifier for this program (e.g. 'cheers')",
    )
    parser.add_argument(
        "--program-name", required=True,
        help="Display name (e.g. 'Cheers')",
    )
    parser.add_argument(
        "--filler", action="append", default=[],
        help="Filler file path to include (repeatable)",
    )
    parser.add_argument(
        "--catalog", default="config/asset_catalog.json",
        help="Output catalog path (default: config/asset_catalog.json)",
    )
    parser.add_argument(
        "--programs-dir", default="config/programs",
        help="Directory for per-program JSON (default: config/programs)",
    )
    args = parser.parse_args()

    catalog_path = Path(args.catalog)
    programs_dir = Path(args.programs_dir)

    # Load existing catalog (additive merge)
    catalog = load_catalog(catalog_path)
    assets = catalog["assets"]

    # Discover and probe episodes
    media_files = discover_media(args.media_dir)
    if not media_files:
        print(f"No media files found in {args.media_dir}", file=sys.stderr)
        sys.exit(1)

    episodes = []
    for mf in media_files:
        file_path = str(mf.resolve())
        print(f"  probing {mf.name} ... ", end="", flush=True)

        probe = probe_file(file_path)
        duration_ms = extract_duration_ms(probe)
        markers = extract_markers(probe)

        # Add to catalog
        assets[file_path] = {
            "duration_ms": duration_ms,
            "asset_type": "episode",
            "markers": markers,
        }

        # Parse episode metadata from filename
        parsed = parse_episode_filename(mf.name)
        if parsed:
            ep_id = f"{args.program_id}-s{parsed['season']:02d}e{parsed['episode']:02d}"
            title = parsed["title"]
        else:
            # Fallback: use filename stem
            ep_id = f"{args.program_id}-{mf.stem}"
            title = mf.stem

        episodes.append({
            "episode_id": ep_id,
            "title": title,
            "file_path": file_path,
            "duration_seconds": duration_ms / 1000.0,
        })

        ch_count = len(markers)
        print(f"{duration_ms}ms, {ch_count} chapters")

    # Probe filler files
    for filler_path in args.filler:
        filler_path = os.path.abspath(filler_path)
        if not os.path.isfile(filler_path):
            print(f"  Warning: filler not found: {filler_path}", file=sys.stderr)
            continue
        print(f"  probing filler {os.path.basename(filler_path)} ... ", end="", flush=True)
        probe = probe_file(filler_path)
        duration_ms = extract_duration_ms(probe)
        assets[filler_path] = {
            "duration_ms": duration_ms,
            "asset_type": "filler",
            "markers": [],
        }
        print(f"{duration_ms}ms")

    # Write catalog
    save_catalog(catalog, catalog_path)
    print(f"\nCatalog: {catalog_path} ({len(assets)} total assets)")

    # Write program JSON
    program = {
        "program_id": args.program_id,
        "name": args.program_name,
        "play_mode": "sequential",
        "episodes": episodes,
    }
    save_program(program, programs_dir)
    print(f"Program: {programs_dir / args.program_id}.json ({len(episodes)} episodes)")


if __name__ == "__main__":
    main()
