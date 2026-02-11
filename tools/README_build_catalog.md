# build_catalog.py

Probes media files with `ffprobe` and builds a JSON asset catalog + per-program episode list for the planning pipeline.

## Prerequisites

- `ffprobe` on PATH (ships with ffmpeg)

## Usage

```bash
# Add one program's episodes
python tools/build_catalog.py \
  --media-dir "/mnt/data/media/tv/Cheers (1982) {imdb-tt0083399}/Season 01" \
  --program-id cheers \
  --program-name "Cheers" \
  --filler /opt/retrovue/assets/filler.mp4

# Add another program (catalog is merged additively)
python tools/build_catalog.py \
  --media-dir "/mnt/data/media/tv/Seinfeld (1989)/Season 03" \
  --program-id seinfeld \
  --program-name "Seinfeld"
```

## Parameters

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--media-dir` | yes | | Directory containing `.mp4` / `.mkv` episode files |
| `--program-id` | yes | | Identifier (e.g. `cheers`) |
| `--program-name` | yes | | Display name (e.g. `Cheers`) |
| `--filler` | no | | Filler file path (repeatable: `--filler a.mp4 --filler b.mp4`) |
| `--catalog` | no | `config/asset_catalog.json` | Shared catalog output path |
| `--programs-dir` | no | `config/programs` | Directory for per-program JSON |

## Outputs

**`config/asset_catalog.json`** — Shared catalog keyed by absolute file path. Each entry has `duration_ms`, `asset_type`, and `markers`. Re-running merges new assets into the existing file.

**`config/programs/{program_id}.json`** — Per-program episode list matching the `JsonFileProgramCatalog` schema. Overwritten each run for that program.

## Filename parsing

Expects Sonarr-style names:

```
Show (Year) - S01E02 - Episode Title [quality-tags].mp4
```

Files that don't match this pattern get a fallback episode ID derived from the filename stem.

## Runtime usage

The catalog is consumed by `StaticAssetLibrary`:

```python
from retrovue.catalog.static_asset_library import StaticAssetLibrary

lib = StaticAssetLibrary("config/asset_catalog.json")
lib.get_duration_ms("/path/to/episode.mp4")   # -> 1501653
lib.get_markers("/path/to/episode.mp4")        # -> [MarkerInfo(...), ...]
lib.get_filler_assets(max_duration_ms=60000)   # -> [FillerAsset(...)]
```
