# Enricher Development Guide

_Related: [Architecture](../architecture/ArchitectureOverview.md) • [Plugin Authoring](PluginAuthoring.md) • [Registry API](RegistryAPI.md) • [Testing Plugins](TestingPlugins.md)_

## Audience

**I am extending RetroVue with a new enricher plugin.**

This guide explains how to implement and register a new **Enricher** in RetroVue. An Enricher is responsible for adding metadata and value to objects during ingest or playout operations, transforming them into richer versions without persisting data directly.

Enrichers are loaded dynamically at runtime and can be attached to Collections (ingest scope) or Channels (playout scope) through the `retrovue enricher` and `retrovue source` CLI commands.

---

## Concepts

### Enricher Type (code)

An _enricher type_ is a Python implementation that knows how to add value to specific object types.

**Examples:**

- `ffprobe` - Video/audio analysis using FFprobe
- `metadata` - Metadata extraction from external APIs
- `playout-enricher` - Channel processing and overlays

An enricher type lives in code under `adapters/enrichers/` and is discovered at runtime. Enricher types are **not** stored in the database.

Each enricher type:

- declares what configuration it needs (e.g. `ffprobe_path`, `timeout`, `api_key`, etc.),
- exposes enrichment methods for specific scopes,
- and registers itself with the Enricher Registry at startup.

### Enricher Instance (persistent configuration)

An _Enricher Instance_ is an operator-configured instance of an enricher type.

**Example:**  
`"Video Analysis"` might be an Enricher Instance of type `ffprobe` with:

- a custom FFprobe path,
- a timeout setting,
- and priority configuration.

This configuration is stored in the database and is assigned a stable `enricher_id`. Operators refer to Enricher Instances by that ID in CLI commands:

```bash
retrovue enricher add --type ffprobe --name "Video Analysis" \
  --ffprobe-path /usr/bin/ffprobe \
  --timeout 30

retrovue source attach-enricher plex-5063d926 enricher-ffprobe-a1b2c3d4 --priority 1
retrovue collection attach-enricher "TV Shows" enricher-ffprobe-a1b2c3d4 --priority 1
```

**So:**

- **Enricher Type** = code you ship.
- **Enricher Instance** = persisted configuration of that code with real settings.

---

## Responsibilities of an Enricher

An Enricher is responsible for:

### Scope Declaration

- Declare whether it operates in `ingest` or `playout` scope
- Validate that it's only attached to appropriate targets
- Handle scope-specific object types correctly

### Value Addition

- Transform input objects by adding metadata, overlays, or processing
- Return enriched versions without modifying originals
- Handle enrichment failures gracefully

### Enrichment Parameter Management

- Define enrichment parameter schema for the enricher type
- Validate enrichment parameters (API keys, file paths, timing values, etc.)
- Support both required and optional enrichment parameters
- Handle parameter updates through the `enricher update` command

### Error Handling

- Raise typed, enricher-specific errors for failures
- Support graceful fallback when enrichment fails
- Never block ingestion or playout operations

---

## What Enrichers Are NOT Allowed To Do

Enrichers are **not allowed** to:

- **Persist data directly** to authoritative database tables (that's the Ingest Service's job)
- **Own orchestration** or decide when to run
- **Modify external systems** or upstream content
- **Block operations** - failures must be graceful

### Metadata domains (authoring rules)

- Write to the correct domain:
  - Technical media data → `probed`
  - Editorial data (titles, seasons, synopsis) → `editorial`
  - Station-level/packaging data → `station_ops`
- Do not overwrite whole domains: perform a deep merge (object/object recursive, last-writer-wins on scalars) when a domain already exists on the item.
- Leave `sidecar` intact unless you are explicitly extending it; sidecar is the canonical merge surface across importer and enrichers.

---

## Enricher Interface

Each enricher type must implement a well-defined interface so orchestration code can drive it.

Below is the core protocol that all enrichers must implement:

```python
from typing import Protocol
from ..importers.base import DiscoveredItem

class Enricher(Protocol):
    """Protocol that all enrichers must implement."""

    name: str
    """Unique name identifier for this enricher"""

    def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
        """
        Enrich a discovered item with additional metadata.

        Args:
            discovered_item: The item to enrich

        Returns:
            The enriched item (may be the same object or a new one)

        Raises:
            EnricherError: If enrichment fails
        """
        ...
```

### Scope-Specific Interfaces

For different scopes, enrichers may work with different object types:

**Ingest Scope Enrichers:**

- Input: `DiscoveredItem` from importers
- Output: Enriched `DiscoveredItem` with additional metadata
- Examples: FFprobe analysis, metadata extraction, file parsing

**Playout Scope Enrichers:**

- Input: Playout plan objects
- Output: Modified playout plan with overlays, transitions, etc.
- Examples: Channel branding, crossfades, emergency crawls

### Enrichment Parameter Schema

Each enricher type declares its enrichment parameter requirements. These are the specific values the enricher needs to perform its enrichment tasks:

```python
@classmethod
def param_spec(cls) -> dict:
    return {
        "required": {
            "--name": "Human-readable label for this enricher"
        },
        "optional": {
            "--ffprobe-path": "Path to FFprobe executable (default: ffprobe)",
            "--timeout": "Timeout in seconds for FFprobe operations (default: 30)"
        }
    }
```

**Enrichment Parameter Types:**

- **API Credentials**: `--api-key` for external service authentication
- **File Paths**: `--overlay-path`, `--template-path` for file-based resources
- **Timing Values**: `--duration`, `--timeout` for temporal parameters
- **Configuration Values**: `--model`, `--language`, `--pattern` for behavior settings
- **No Parameters**: Some enrichers (e.g., FFmpeg) require no parameters and use system defaults

**Parameter Update Behavior:**

- The `enricher update` command allows modification of these enrichment parameters
- Some enrichers may not require updates (inform user that updates are not necessary)
- Others may need frequent updates (e.g., API keys for external services)

---

## Discovery / Registry

At startup, RetroVue discovers available enrichers under `adapters/enrichers/`, registering them by their type identifier. Instances refer to these types.

## Registration

Enricher types must be registered so RetroVue can find them at runtime.

At startup, RetroVue scans `adapters/enrichers/` for modules that identify themselves as enrichers and registers them with the Enricher Registry.

That registry:

- maps `name` → enricher class
- exposes all enricher types to the CLI via `retrovue enricher list-types`
- validates parameters for `retrovue enricher add --type <type>`

A typical registration pattern looks like:

```python
from retrovue.registries.enricher_registry import ENRICHER_REGISTRY

class FFprobeEnricher:
    name = "ffprobe"
    scope = "ingest"

    @classmethod
    def param_spec(cls) -> dict:
        return {
            "required": {"--name": "Human-readable label"},
            "optional": {
                "--ffprobe-path": "Path to FFprobe executable (default: ffprobe)",
                "--timeout": "Timeout in seconds (default: 30)"
            }
        }

    def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
        # Implementation here
        ...

ENRICHER_REGISTRY.register(FFprobeEnricher)
```

**Enrichment Parameter Examples by Enricher Type:**

```python
# TheTVDB Enricher - requires API key
class TheTVDBEnricher:
    name = "tvdb"
    scope = "ingest"

    @classmethod
    def param_spec(cls) -> dict:
        return {
            "required": {
                "--name": "Human-readable label",
                "--api-key": "TheTVDB API key for authentication"
            },
            "optional": {
                "--language": "Language preference (default: en-US)"
            }
        }

# Watermark Enricher - requires file path
class WatermarkEnricher:
    name = "watermark"
    scope = "playout"

    @classmethod
    def param_spec(cls) -> dict:
        return {
            "required": {
                "--name": "Human-readable label",
                "--overlay-path": "Path to watermark image file"
            },
            "optional": {
                "--position": "Watermark position (default: top-right)",
                "--opacity": "Watermark opacity 0.0-1.0 (default: 0.8)"
            }
        }

# FFmpeg Enricher - no parameters needed
class FFmpegEnricher:
    name = "ffmpeg"
    scope = "ingest"

    @classmethod
    def param_spec(cls) -> dict:
        return {
            "required": {"--name": "Human-readable label"},
            "optional": {}  # No enrichment parameters needed
        }
```

**Key rules:**

- `name` must be unique across all enricher types.
- If two enricher types claim the same `name`, registration MUST fail fast and loudly.
- If an enricher type is removed from the codebase, any Enricher Instances in the DB that reference that `name` are still kept, but will be marked unavailable at runtime.

---

## Enricher Lifecycle (Operator View)

Once your enricher type is registered, operators interact with it entirely through `retrovue enricher ....` and attachment commands.

### Create an Enricher Instance

```bash
retrovue enricher add \
  --type ffprobe \
  --name "Video Analysis" \
  --ffprobe-path /usr/bin/ffprobe \
  --timeout 30
```

- CLI calls your enricher's `param_spec()` to know what enrichment parameters are required.
- CLI validates that all required enrichment parameters are present.
- RetroVue persists a new Enricher Instance row in the DB with:
  - `enricher_id` (e.g. `enricher-ffprobe-a1b2c3d4`)
  - `type` = "ffprobe"
  - `config` (FFprobe path, timeout, etc.)

### Update Enrichment Parameters

```bash
# Update API key for TheTVDB enricher
retrovue enricher update enricher-tvdb-b2c3d4e5 \
  --api-key "new-tvdb-api-key"

# Update watermark path for playout enricher
retrovue enricher update enricher-watermark-c3d4e5f6 \
  --overlay-path "/new/path/to/watermark.png"

# FFmpeg enricher requires no updates
retrovue enricher update enricher-ffmpeg-a1b2c3d4
# Output: "FFmpeg enricher requires no parameter updates"
```

- CLI validates enrichment parameters against the enricher's `param_spec()`.
- Some enrichers may not require updates (inform user that updates are not necessary).
- RetroVue updates the persisted configuration with new enrichment parameter values.

### Attach to Collections (Ingest Scope)

```bash
retrovue collection attach-enricher "TV Shows" enricher-ffprobe-a1b2c3d4 --priority 1
```

- System loads your enricher by `type`.
- Passes the persisted config.
- Enricher runs during ingest operations on that collection.

### Attach to Channels (Playout Scope)

```bash
retrovue channel attach-enricher "Main Channel" enricher-playout-a1b2c3d4 --priority 2
```

- System loads your enricher by `type`.
- Passes the persisted config.
- Enricher runs during playout plan generation for that channel.

### Enrichment Execution

During ingest or playout:

- System loops over attached enrichers in priority order.
- For each enricher, it calls `enrich()` with the current object.
- Enriched objects flow through the pipeline.

---

## Error Handling & Safety

Your enricher must behave like infrastructure, not like a script.

**Rules you must follow:**

### You MUST raise typed, enricher-specific errors for:

- bad enrichment parameters (invalid API key format, file not found, etc.),
- unreachable external services,
- malformed responses,
- "file not found," etc.

**Do not** `sys.exit`, **do not** print and continue. **Raise.** The orchestration layer / CLI is responsible for converting that into:

- exit code 1,
- clean human output,
- stable JSON if `--json` was passed.

### You MUST support graceful failure.

When an enricher fails on a single item during ingest, that error is logged and ingest continues with the partially enriched item.

When a playout enricher fails when assembling the playout plan, RetroVue falls back to the most recent successful version without that enricher's modifications.

### You MUST be deterministic for the same config and same input.

Enrichment needs to be repeatable so we can diff runs, isolate partial failures, and reconcile.

### You MUST NOT persist outside the controlled transaction.

Enrichers feed enrichment. They don't write directly to RetroVue's final authoritative tables. Persistence happens inside the Ingest Service / Unit of Work layer, not inside your enricher class.

---

## Implementation Examples

### FFprobe Enricher (Ingest Scope)

```python
import json
import subprocess
from pathlib import Path
from typing import Any

from ..importers.base import DiscoveredItem
from .base import Enricher, EnricherError

class FFprobeEnricher:
    """Enricher for video/audio analysis using FFprobe."""

    name = "ffprobe"
    scope = "ingest"

    def __init__(self, ffprobe_path: str = "ffprobe", timeout: int = 30):
        """
        Initialize FFprobe enricher with enrichment parameters.

        Args:
            ffprobe_path: Path to FFprobe executable (enrichment parameter)
            timeout: Timeout in seconds for FFprobe operations (enrichment parameter)
        """
        self.ffprobe_path = ffprobe_path
        self.timeout = timeout

    def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
        """Enrich a discovered item with FFprobe metadata."""
        try:
            # Only process file:// URIs
            if not discovered_item.path_uri.startswith("file://"):
                return discovered_item

            # Extract file path from URI
            file_path = Path(discovered_item.path_uri[7:])  # Remove "file://" prefix

            if not file_path.exists():
                raise EnricherError(f"File does not exist: {file_path}")

            # Run FFprobe to get metadata
            metadata = self._run_ffprobe(file_path)

            # Extract relevant information
            enriched_labels = discovered_item.raw_labels or []

            # Add duration if available
            if "duration" in metadata:
                duration_ms = int(float(metadata["duration"]) * 1000)
                enriched_labels.append(f"duration_ms:{duration_ms}")

            # Add video codec if available
            if "video_codec" in metadata:
                enriched_labels.append(f"video_codec:{metadata['video_codec']}")

            # Add audio codec if available
            if "audio_codec" in metadata:
                enriched_labels.append(f"audio_codec:{metadata['audio_codec']}")

            # Add container format if available
            if "container" in metadata:
                enriched_labels.append(f"container:{metadata['container']}")

            # Add resolution if available
            if "resolution" in metadata:
                enriched_labels.append(f"resolution:{metadata['resolution']}")

            # Add chapter markers if available
            if "chapters" in metadata:
                chapter_count = len(metadata["chapters"])
                enriched_labels.append(f"chapters:{chapter_count}")

            # Create enriched item
            enriched_item = DiscoveredItem(
                path_uri=discovered_item.path_uri,
                provider_key=discovered_item.provider_key,
                raw_labels=enriched_labels,
                last_modified=discovered_item.last_modified,
                size=discovered_item.size,
                hash_sha256=discovered_item.hash_sha256
            )

            return enriched_item

        except Exception as e:
            raise EnricherError(f"Failed to enrich item: {str(e)}") from e

    def _run_ffprobe(self, file_path: Path) -> dict[str, Any]:
        """Run FFprobe on a file and return parsed metadata."""
        try:
            # Build FFprobe command
            cmd = [
                self.ffprobe_path,
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                "-show_chapters",
                str(file_path)
            ]

            # Run FFprobe
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )

            if result.returncode != 0:
                raise EnricherError(f"FFprobe failed: {result.stderr}")

            # Parse JSON output
            data = json.loads(result.stdout)

            # Extract relevant metadata
            metadata = {}

            # Duration from format
            if "format" in data and "duration" in data["format"]:
                metadata["duration"] = data["format"]["duration"]

            # Container format
            if "format" in data and "format_name" in data["format"]:
                metadata["container"] = data["format"]["format_name"]

            # Stream information
            if "streams" in data:
                video_streams = [s for s in data["streams"] if s.get("codec_type") == "video"]
                audio_streams = [s for s in data["streams"] if s.get("codec_type") == "audio"]

                # Video codec
                if video_streams:
                    video_stream = video_streams[0]
                    if "codec_name" in video_stream:
                        metadata["video_codec"] = video_stream["codec_name"]

                    # Resolution
                    if "width" in video_stream and "height" in video_stream:
                        width = video_stream["width"]
                        height = video_stream["height"]
                        metadata["resolution"] = f"{width}x{height}"

                # Audio codec
                if audio_streams:
                    audio_stream = audio_streams[0]
                    if "codec_name" in audio_stream:
                        metadata["audio_codec"] = audio_stream["codec_name"]

            # Chapter information
            if "chapters" in data:
                metadata["chapters"] = data["chapters"]

            return metadata

        except subprocess.TimeoutExpired:
            raise EnricherError("FFprobe timed out")
        except json.JSONDecodeError as e:
            raise EnricherError(f"Failed to parse FFprobe output: {e}")
        except Exception as e:
            raise EnricherError(f"FFprobe execution failed: {e}")
```

Requirements & Failure Behavior:

- FFprobe must be installed and on PATH (or configured via `ffprobe_path`).
- If FFprobe cannot be located or executed, the enricher raises a clear error:
  "FFprobe executable not found. Install ffprobe and ensure it is on PATH, or configure ffprobe_path."
- Collection ingest records enricher errors under `stats.errors` and continues processing other items.

### Metadata Enricher (Ingest Scope)

```python
import requests
from typing import Any, Dict

from ..importers.base import DiscoveredItem
from .base import Enricher, EnricherError

class MetadataEnricher:
    """Enricher for metadata extraction from external APIs."""

    name = "metadata"
    scope = "ingest"

    def __init__(self, sources: str = "imdb,tmdb", api_key: str = None):
        """
        Initialize metadata enricher with enrichment parameters.

        Args:
            sources: Comma-separated list of metadata sources (enrichment parameter)
            api_key: API key for external services (enrichment parameter)
        """
        self.sources = sources.split(",")
        self.api_key = api_key

    def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
        """Enrich a discovered item with external metadata."""
        try:
            # Extract title from path or labels
            title = self._extract_title(discovered_item)
            if not title:
                return discovered_item

            # Look up metadata from configured sources
            metadata = self._lookup_metadata(title)

            if not metadata:
                return discovered_item

            # Add metadata as labels
            enriched_labels = discovered_item.raw_labels or []

            for key, value in metadata.items():
                if value is not None:
                    enriched_labels.append(f"{key}:{value}")

            # Create enriched item
            enriched_item = DiscoveredItem(
                path_uri=discovered_item.path_uri,
                provider_key=discovered_item.provider_key,
                raw_labels=enriched_labels,
                last_modified=discovered_item.last_modified,
                size=discovered_item.size,
                hash_sha256=discovered_item.hash_sha256
            )

            return enriched_item

        except Exception as e:
            raise EnricherError(f"Failed to enrich item: {str(e)}") from e

    def _extract_title(self, item: DiscoveredItem) -> str:
        """Extract title from item path or labels."""
        # Implementation to extract title from path or existing labels
        # This is a simplified example
        if item.raw_labels:
            for label in item.raw_labels:
                if label.startswith("title:"):
                    return label.split(":", 1)[1]
        return None

    def _lookup_metadata(self, title: str) -> Dict[str, Any]:
        """Look up metadata from external sources."""
        metadata = {}

        for source in self.sources:
            try:
                if source == "imdb":
                    metadata.update(self._lookup_imdb(title))
                elif source == "tmdb":
                    metadata.update(self._lookup_tmdb(title))
            except Exception as e:
                # Log error but continue with other sources
                print(f"Warning: {source} lookup failed: {e}")
                continue

        return metadata

    def _lookup_imdb(self, title: str) -> Dict[str, Any]:
        """Look up metadata from IMDb."""
        # Implementation for IMDb API lookup
        return {}

    def _lookup_tmdb(self, title: str) -> Dict[str, Any]:
        """Look up metadata from TMDb."""
        # Implementation for TMDb API lookup
        return {}
```

### Playout Enricher (Playout Scope)

```python
from typing import Any, Dict

from .base import Enricher, EnricherError

class PlayoutEnricher:
    """Enricher for playout plan modifications."""

    name = "playout-enricher"
    scope = "playout"

    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize playout enricher with enrichment parameters.

        Args:
            config: Dictionary of enrichment parameters (overlay_path, crossfade_duration, etc.)
        """
        self.config = config or {}

    def enrich(self, playout_plan: Any) -> Any:
        """Enrich a playout plan with modifications."""
        try:
            # Apply modifications based on configuration
            if "overlay_path" in self.config:
                playout_plan = self._add_overlay(playout_plan, self.config["overlay_path"])

            if "crossfade_duration" in self.config:
                playout_plan = self._add_crossfades(playout_plan, self.config["crossfade_duration"])

            return playout_plan

        except Exception as e:
            raise EnricherError(f"Failed to enrich playout plan: {str(e)}") from e

    def _add_overlay(self, playout_plan: Any, overlay_path: str) -> Any:
        """Add overlay to playout plan."""
        # Implementation to add overlay
        return playout_plan

    def _add_crossfades(self, playout_plan: Any, duration: float) -> Any:
        """Add crossfades to playout plan."""
        # Implementation to add crossfades
        return playout_plan
```

---

## Versioning / Availability

Enrichers can come and go at runtime.

If your enricher file is removed from the codebase, RetroVue will no longer register that `name`.

Any existing Enricher Instances in the DB that referenced your enricher will:

- still exist,
- still be listed in `retrovue enricher list`,
- but will appear as unavailable.

Commands like `retrovue collection attach-enricher` MUST refuse to run for an unavailable enricher and MUST produce an explanatory error telling the operator the implementation is missing.

You are not responsible for that UX inside the enricher. That's enforced in the Enricher command contract. But: you are responsible for giving the registry enough metadata (`name`, friendly description) that the CLI can report something meaningful.

---

## Checklist for Contributing a New Enricher

Before you send a PR for a new enricher:

### Implements required interface

- [ ] `name` attribute
- [ ] `scope` attribute (ingest or playout)
- [ ] `enrich()` method with proper signature
- [ ] `param_spec()` class method for enrichment parameters
- [ ] proper error handling for enrichment parameter validation

### Registers with the Enricher Registry

- [ ] unique `name`
- [ ] no collisions
- [ ] proper registration call

### Supports graceful failure

- [ ] Raises typed errors, does not exit()
- [ ] Handles external service failures gracefully
- [ ] Never blocks ingestion or playout operations

### Has tests

- [ ] Enrichment behavior
- [ ] Enrichment parameter validation
- [ ] Error handling paths for invalid parameters
- [ ] Graceful failure scenarios
- [ ] Deterministic output for same input
- [ ] Parameter update behavior (for enrichers that support updates)

See [TestingPlugins.md](TestingPlugins.md) for expectations on enricher tests, and integration smoke tests across Source → Collection → Enricher → Producer.

---

## Summary

- **Enricher Type** = runtime plugin that knows how to add value to objects.
- **Enricher Instance** = persisted configuration of that enricher type with real enrichment parameters and operator intent.
- **Enrichment Parameters** = specific values an enricher needs to perform its enrichment tasks (API keys, file paths, timing values, etc.).
- **Runtime registry** wires enricher types into the CLI (`enricher list-types`, `enricher add`, `enricher update`, etc.).
- **Your enricher** feeds enrichment, but does not own persistence, policy, or orchestration.

If your enricher follows this contract, RetroVue can safely treat your enrichment logic like first-class internal processing.
