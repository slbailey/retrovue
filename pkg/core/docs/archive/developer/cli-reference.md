> **⚠️ Historical document.** Superseded by: [contracts/cli](../../contracts/cli/README.md), [contracts/resources](../../contracts/resources/README.md).

# RetroVue CLI

\_See the [CLI contract](../contracts/resources/README.md) for the complete reference.

The RetroVue CLI provides a command-line interface for managing your media library, content ingestion, and review workflows.

## Installation

After installing RetroVue, the CLI is available as the `retrovue` command:

```bash
# Install in development mode
pip install -e .

# The CLI is now available
retrovue --help
```

## Command Structure

The CLI is organized into command groups reflecting the domain separation. There are two fundamental types of command groups:

### Domain Entity Commands

These commands manage **persisted domain entities** that operators create, configure, and maintain. Each entity has CRUD operations (create, read, update, delete) and is stored in the database.

- `retrovue channel` - Channel configuration and management (add, list, update, delete, show, validate)
- `retrovue source` - Source management (add, list, discover, ingest)
- `retrovue collection` - Collection management (list, show, update, ingest, wipe)
- `retrovue asset` - Asset inspection and review operations
- `retrovue enricher` - Enricher management (add, list, remove)
- `retrovue producer` - Producer management (add, list, remove)

**Pattern**: Domain entities have persistent state, support CRUD operations, and are managed by operators through the CLI.

### Runtime Infrastructure Commands

These commands provide **diagnostics and validation** for runtime system components that operate during broadcast execution. These components are not user-managed entities—they are infrastructure services that operators diagnose and validate.

- `retrovue runtime` - Runtime diagnostics and validation operations
  - `retrovue runtime masterclock` - Validate MasterClock time source behavior
  - `retrovue runtime masterclock-monotonic` - Test time monotonicity
  - `retrovue runtime masterclock-logging` - Validate logging timestamps
  - `retrovue runtime masterclock-scheduler-alignment` - Validate scheduler time usage
  - `retrovue runtime masterclock-stability` - Stress-test performance
  - `retrovue runtime masterclock-consistency` - Test component time consistency
  - `retrovue runtime masterclock-serialization` - Validate timestamp serialization
  - `retrovue runtime masterclock-performance` - Performance benchmarking

**Pattern**: Runtime infrastructure components (MasterClock, ScheduleService, ChannelManager, etc.) are system services that run during broadcast execution. They are not persisted entities—they are validated and diagnosed, not configured through CRUD operations.

**Why this distinction matters**:

- **Domain entities** represent business concepts that operators manage (channels, sources, assets)
- **Runtime infrastructure** represents system components that execute the broadcast (time services, schedulers, playout managers)
- Operators configure domain entities; they diagnose runtime infrastructure

## Global Options

All commands support these global options:

- `--json` - Output results in JSON format
- `--help` - Show help for the command

## Commands

### Runtime Diagnostics Commands

#### `retrovue runtime masterclock`

Validate MasterClock functionality and core behaviors.

```bash
# Basic MasterClock validation
retrovue runtime masterclock

# Validate with specific precision
retrovue runtime masterclock --precision millisecond

# JSON output
retrovue runtime masterclock --json
```

**Options:**

- `--precision, -p` - Time precision: second, millisecond, microsecond (default: millisecond)
- `--json` - Output results in JSON format

**Purpose:**
Validates that MasterClock (the authoritative time source) correctly provides tz-aware timestamps, maintains monotonicity, rejects naive datetimes, and serves as the single source of "now" for all runtime components.

See [MasterClock Contract](../contracts/resources/MasterClockContract.md) for complete validation rules and behavior specifications.

### Assets Commands (Library Domain)

#### `retrovue assets run`

Run content ingestion from a source.

```bash
# Ingest from filesystem
retrovue assets run filesystem:/path/to/media

# Ingest with specific library and enrichers
retrovue assets run plex --library-id 1 --enrichers ffprobe

# Output in JSON format
retrovue assets run filesystem:/media --json
```

**Arguments:**

- `source` - Source identifier (e.g., 'plex', 'filesystem:/path')

**Options:**

- `--library-id TEXT` - Library ID to process
- `--enrichers TEXT` - Comma-separated list of enrichers (e.g., 'ffprobe')
- `--json` - Output in JSON format

#### `retrovue assets promote`

Promotes a reviewed Library asset into the Broadcast Catalog.

```bash
# Promote an asset to the broadcast catalog
retrovue assets promote --uuid "b4739f5c-7f91-4937-a7b2-4a5ba8ef4249" \
  --title "Cheers S01E01" \
  --tags "sitcom,comedy" \
  --canonical true

# Promote without canonical approval (not yet airable)
retrovue assets promote --uuid "b4739f5c-7f91-4937-a7b2-4a5ba8ef4249" \
  --title "New Episode" \
  --tags "drama" \
  --canonical false
```

**Options:**

- `--uuid` - Library asset identifier (required)
- `--title` - Guide-facing title (required)
- `--tags` - Comma-separated tags (required)
- `--canonical` - Mark as approved-for-air (required)
- `--json` - Output as JSON

**Purpose:**
Promotion is the ONLY approved path to make content legally schedulable. This creates a new `catalog_asset` row in the Broadcast Domain.

### Catalog Commands (Broadcast Domain)

#### `retrovue catalog add`

Add a new catalog entry (airable, canonical-approved asset).

```bash
# Add a canonical asset to the broadcast catalog
retrovue catalog add --title "Cheers S01E01" --duration 1440 --tags "sitcom" --path "/media/cheers01.mkv" --canonical true

# Add without canonical approval (not yet airable)
retrovue catalog add --title "New Episode" --duration 1800 --tags "drama" --path "/media/new.mkv" --canonical false
```

**Options:**

- `--title` - Asset title as it should appear on-air
- `--duration` - Duration in seconds
- `--tags` - Comma-separated tags used by scheduling rules
- `--path` - Playable file path
- `--canonical` - Mark as approved-for-air
- `--json` - Output as JSON

#### `retrovue catalog update`

Update an existing catalog entry.

```bash
# Approve an asset for broadcast
retrovue catalog update --id 12 --canonical true

# Update metadata
retrovue catalog update --id 12 --title "Updated Title" --tags "sitcom,comedy"
```

**Options:**

- `--id` - Catalog ID
- `--title` - Updated title
- `--duration` - Updated duration in seconds
- `--tags` - Updated comma-separated tags
- `--path` - Updated file path
- `--canonical` - Updated canonical status
- `--json` - Output as JSON

#### `retrovue catalog list`

List catalog entries (airable assets).

```bash
# List all catalog entries
retrovue catalog list

# List only canonical (approved) assets
retrovue catalog list --canonical-only

# Filter by tag
retrovue catalog list --tag sitcom

# JSON output
retrovue catalog list --json
```

**Options:**

- `--canonical-only` - Show only assets approved for scheduling
- `--tag` - Filter by tag (e.g. sitcom)
- `--json` - Output in JSON format

### Channel Commands (Broadcast Domain)

#### `retrovue channel add`

Create/define a station channel.

```bash
# Create a new channel
retrovue channel add --name "RetroVue-1" \
  --grid-size-minutes 30 \
  --grid-offset-minutes 0 \
  --broadcast-day-start "06:00"
```

**Options:**

- `--name` - Channel identifier (required)
- `--grid-size-minutes` - Planning granularity in minutes (default: 30)
- `--grid-offset-minutes` - Offset from top of hour in minutes (default: 0)
- `--broadcast-day-start` - Broadcast day start in HH:MM local time (default: 06:00)

**Purpose:**
This is how you define "how the station rolls a day."

### Template Commands (Broadcast Domain)

#### `retrovue template add`

Build reusable daypart templates.

```bash
# Create a template
retrovue template add --name "All Sitcoms 24x7" \
  --description "24-hour sitcom programming"
```

**Options:**

- `--name` - Template identifier (required)
- `--description` - Human-readable description (optional)

#### `retrovue template block add`

Add rule blocks to templates.

```bash
# Add a content block to a template
retrovue template block add --template-id 1 \
  --start "00:00" \
  --end "24:00" \
  --tags "sitcom" \
  --episode-policy "syndication"
```

**Options:**

- `--template-id` - Template ID (required)
- `--start` - Block start time in HH:MM format (required)
- `--end` - Block end time in HH:MM format (required)
- `--tags` - Comma-separated content tags (required)
- `--episode-policy` - Episode selection policy (required)

**Purpose:**
The rules contain tags/episode_policy that tell ScheduleService what kind of content to pull.

### Schedule Commands (Broadcast Domain)

#### `retrovue schedule assign`

Assign a template to a specific channel and broadcast day.

```bash
# Assign template to channel for specific date
retrovue schedule assign --channel "RetroVue-1" \
  --template "All Sitcoms 24x7" \
  --day "2025-01-24"
```

**Options:**

- `--channel` - Channel name or ID (required)
- `--template` - Template name or ID (required)
- `--day` - Broadcast date in YYYY-MM-DD format (required)

**Purpose:**
This is how you declare tomorrow's programming spine.

### Assets Commands (Library Domain)

#### `retrovue assets list`

List assets with optional status filtering.

```bash
# List all assets
retrovue assets list

# List only pending assets
retrovue assets list --status pending

# List only canonical assets
retrovue assets list --status canonical

# Output in JSON format
retrovue assets list --json
```

**Options:**

- `--status [pending|canonical|all]` - Filter by asset status (default: all)
- `--json` - Output in JSON format

#### `retrovue assets select`

Select an asset (returning UUID + lightweight metadata).

This is the primary command for choosing assets. Use this UUID with `retrovue assets get <uuid> --json` to retrieve full details.

```bash
# Select a random episode from a series (positional argument)
retrovue assets select "Cheers" --mode random --json

# Select a random episode from a series (flag argument)
retrovue assets select --series "Cheers" --mode random --json

# Select the next episode in sequence (S01E01 when no history exists)
retrovue assets select --series "Cheers" --mode sequential

# Select by genre (when implemented)
retrovue assets select --genre horror --mode random --json

# Typical workflow: select then get full details
retrovue assets select "Cheers" --mode random --json \
| jq -r .uuid \
| xargs retrovue assets get --json
```

**Arguments:**

- `SERIES` - Series name (positional argument, mutually exclusive with --series)

**Options:**

- `--series TEXT` - Series name (flag argument, mutually exclusive with positional)
- `--genre TEXT` - Filter by genre (not yet implemented)
- `--mode [random|sequential]` - Selection mode (default: random)
- `--json` - Output in JSON format

**Selection Modes:**

- `random` - Choose a random episode from the series
- `sequential` - Choose the next episode in natural order (by season_number, episode_number)
  - For now, if there is no play history, picks the first episode (S01E01)
  - TODO: Add per-channel last-played logic

**JSON Output Format:**

```json
{
  "uuid": "b4739f5c-7f91-4937-a7b2-4a5ba8ef4249",
  "id": 5,
  "title": "The Tortelli Tort",
  "series_title": "Cheers",
  "season_number": 1,
  "episode_number": 3,
  "kind": "episode",
  "selection": {
    "mode": "random",
    "criteria": {
      "series": "Cheers"
    }
  }
}
```

**Human Output Format:**

```
Cheers S01E03 "The Tortelli Tort"  b4739f5c-7f91-4937-a7b2-4a5ba8ef4249
```

**Notes:**

- Numbers must be numeric (not strings)
- Use this UUID with `retrovue assets get <uuid> --json` to retrieve file_path/duration/etc.
- Selection requires at least one filter: series or genre
- You cannot provide both a positional argument and the --series flag

#### `retrovue assets series` (DEPRECATED)

List series or episodes for a specific series.

**DEPRECATED:** When a series is provided, use `assets select` to choose an episode.

```bash
# List all available series (still works)
retrovue assets series

# Show episodes for a specific series (DEPRECATED - use assets select)
retrovue assets series "Batman TAS"  # DEPRECATED: Use 'assets select "Batman TAS"'
retrovue assets series --series "Batman TAS"  # DEPRECATED: Use 'assets select --series "Batman TAS"'

# Output in JSON format
retrovue assets series "Batman TAS" --json  # DEPRECATED: Use 'assets select "Batman TAS" --json'
retrovue assets series --series "Batman TAS" --json  # DEPRECATED: Use 'assets select --series "Batman TAS" --json'
```

**Arguments:**

- `SERIES` - Series name (positional argument, mutually exclusive with --series)

**Options:**

- `--series TEXT` - Series name (flag argument, mutually exclusive with positional)
- `--json` - Output in JSON format

**Deprecation Behavior:**

When a series is provided, this command:

1. Prints a deprecation warning to stderr
2. Delegates internally to `assets select` with the same series and `--mode random`
3. Returns the same selection JSON as `assets select` (not the old seasons tree)

When no series is provided, it still lists all series as `{"series": [...]}`.

**JSON Output Format:**

When requesting a specific series (DEPRECATED), the JSON output now matches `assets select`:

```json
{
  "uuid": "b4739f5c-7f91-4937-a7b2-4a5ba8ef4249",
  "id": 5,
  "title": "The Tortelli Tort",
  "series_title": "Cheers",
  "season_number": 1,
  "episode_number": 3,
  "kind": "episode",
  "selection": {
    "mode": "random",
    "criteria": {
      "series": "Cheers"
    }
  }
}
```

When listing all series, the JSON output is:

```json
{
  "series": ["Batman TAS", "Frasier", "Cheers"]
}
```

**Notes:**

- Numeric fields (id, season_number, episode_number) are returned as numbers, not strings
- You cannot provide both a positional argument and the --series flag
- Use `assets select` for new code instead of this deprecated command

### Review Commands

#### `retrovue review list`

List items in the review queue.

```bash
# List all review items
retrovue review list

# Output in JSON format
retrovue review list --json
```

#### `retrovue review resolve`

Resolve a review queue item by associating it with an episode.

```bash
# Resolve a review item
retrovue review resolve <review-id> <episode-id>

# Resolve with notes
retrovue review resolve <review-id> <episode-id> --notes "Manually verified"

# Output in JSON format
retrovue review resolve <review-id> <episode-id> --json
```

**Arguments:**

- `review_id` - Review ID to resolve
- `episode_id` - Episode ID to associate

**Options:**

- `--notes TEXT` - Resolution notes
- `--json` - Output in JSON format

## JSON Output

When using the `--json` flag, all commands output structured JSON data that can be easily parsed by other tools or scripts.

### Example JSON Output

**Ingest Response:**

```json
{
  "source": "filesystem:/media",
  "library_id": null,
  "enrichers": ["ffprobe"],
  "counts": {
    "discovered": 10,
    "registered": 8,
    "enriched": 6,
    "canonicalized": 4,
    "queued_for_review": 2
  }
}
```

**Assets List Response:**

```json
{
  "assets": [
    {
      "id": "123e4567-e89b-12d3-a456-426614174000",
      "uri": "file:///media/movie.mp4",
      "size": 1048576,
      "duration_ms": 7200000,
      "video_codec": "h264",
      "audio_codec": "aac",
      "container": "mp4",
      "hash_sha256": "abc123...",
      "discovered_at": "2024-01-01T12:00:00Z",
      "canonical": true
    }
  ],
  "total": 1,
  "status_filter": "canonical"
}
```

## Error Handling

The CLI provides clear error messages and appropriate exit codes:

- **Exit code 0**: Success
- **Exit code 1**: General error (invalid arguments, service errors)
- **Exit code 2**: Not found (asset, review, etc.)

## Examples

### Complete Workflow

```bash
# 1. Ingest content from filesystem (Library Domain)
retrovue assets run filesystem:/media/movies --enrichers ffprobe

# 2. List discovered assets (Library Domain)
retrovue assets list --status pending

# 3. Check review queue
retrovue review list

# 4. Resolve a review item
retrovue review resolve 123e4567-e89b-12d3-a456-426614174000 987fcdeb-51a2-43d1-b456-426614174000

# 5. Promote approved content to broadcast catalog (Library → Broadcast Domain)
retrovue assets promote --uuid "123e4567-e89b-12d3-a456-426614174000" \
  --title "Approved Movie" \
  --tags "action" \
  --canonical true

# 6. List airable assets (Broadcast Domain)
retrovue catalog list --canonical-only

# 7. Create channel (Broadcast Domain)
retrovue channel add --name "RetroVue-1" \
  --grid-size-minutes 30 \
  --broadcast-day-start "06:00"

# 8. Create template (Broadcast Domain)
retrovue template add --name "All Movies 24x7" \
  --description "24-hour movie programming"

# 9. Add template block (Broadcast Domain)
retrovue template block add --template-id 1 \
  --start "00:00" \
  --end "24:00" \
  --tags "action" \
  --episode-policy "syndication"

# 10. Assign template to channel (Broadcast Domain)
retrovue schedule assign --channel "RetroVue-1" \
  --template "All Movies 24x7" \
  --day "2025-01-24"
```

### Automation Script

```bash
#!/bin/bash
# Automated content processing

echo "Starting content ingestion..."
retrovue assets run filesystem:/media --json > ingest_results.json

echo "Processing review queue..."
retrovue review list --json > review_queue.json

# Process review items automatically
jq -r '.reviews[] | select(.confidence < 0.5) | .id' review_queue.json | while read review_id; do
    echo "Auto-resolving low-confidence review: $review_id"
    retrovue review resolve "$review_id" "auto-resolved-episode" --notes "Auto-resolved due to low confidence"
done
```

## Integration

The CLI is designed to integrate seamlessly with the RetroVue service layer:

- **Service-oriented**: All commands call application services, never direct database access
- **Consistent responses**: Uses the same Pydantic models as the API
- **Transaction safety**: Proper commit/rollback handling for all operations
- **JSON-first**: Structured output for easy integration with other tools

## Troubleshooting

### Common Issues

**"Module not found" errors:**

```bash
# Make sure you've installed the package
pip install -e .
```

**Database connection errors:**

```bash
# Check your database configuration
# The CLI uses the same database settings as the API
```

**Permission errors:**

```bash
# Ensure you have read/write access to the media directories
# and database files
```

### Getting Help

```bash
# Get help for any command
retrovue --help
retrovue assets --help
retrovue catalog --help
retrovue assets list --help
retrovue catalog list --help
retrovue review resolve --help
```

### Play Commands (IPTV Streaming)

#### `retrovue play`

Resolve an episode from your content library and expose it as a live MPEG-TS stream for IPTV playback.

```bash
# Start streaming a specific episode on the default port
retrovue play "Cheers" --season 1 --episode 3

# Enable verbose debugging (FFmpeg -loglevel debug) and input validation
retrovue play "Cheers" --season 1 --episode 3 --debug

# Kill any process bound to the chosen port before starting
retrovue play "Cheers" --season 1 --episode 3 --kill-existing

# Custom HTTP port
retrovue play "Cheers" --season 1 --episode 3 --port 8080

# Transcode explicitly (H.264/AAC)
retrovue play "Cheers" --season 1 --episode 3 --transcode
```

**Arguments:**

- `SERIES` - Series title (e.g., "Cheers")

**Options:**

- `--season, -s INTEGER` - Season number (required)
- `--episode, -e INTEGER` - Episode number (required)
- `--channel-id, -c INTEGER` - Channel ID used in the streaming URL (default: 1)
- `--port, -p INTEGER` - HTTP port to serve MPEG-TS streams (default: 8000)
- `--transcode` - Force H.264/AAC output for broad compatibility
- `--debug` - Enable verbose FFmpeg logging and input validation
- `--kill-existing` - Kill any process already bound to the specified port

The stream will be available at:

```
http://localhost:<port>/iptv/channel/<channel_id>.ts
```

#### `retrovue play-channel`

Start the IPTV server and expose a single channel by channel ID.

```bash
# Start channel 1 on the default port
retrovue play-channel 1

# Kill existing process on port 8000 before starting
retrovue play-channel 1 --kill-existing

# Custom port
retrovue play-channel 1 --port 9000
```

**Options:**

- `--port, -p INTEGER` - HTTP port (default: 8000)
- `--kill-existing` - Kill any process already bound to the specified port

### Module Entry Points

The FFmpeg command builder can be imported from the streaming package:

```python
from retrovue.streaming.ffmpeg_cmd import build_cmd
```

You can also invoke it as a Python module (for quick availability checks):

```bash
python -m retrovue.streaming.ffmpeg_cmd
```
