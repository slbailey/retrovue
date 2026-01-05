_Related: [Architecture](../architecture/ArchitectureOverview.md) • [Runtime](../runtime/ChannelManager.md) • [ScheduleItem](ScheduleItem.md) • [PlaylogEvent](PlaylogEvent.md) • [Channel](Channel.md) • [PlayoutPipeline](PlayoutPipeline.md)_

# Domain — PlayoutRequest

## Purpose

A PlayoutRequest is a **message describing the next asset to load into Retrovue Air's PREVIEW buffer**. It provides Retrovue Air with all data needed to prepare an asset for playout. **Important:** A PlayoutRequest represents the next asset to load into **PREVIEW**, not the next stream to output directly.

**Note:** Phase 8 implements a simplified one-file playout pipeline for testing. In Phase 8, Air may play the asset directly without preview/live switching. Future phases add PREVIEW/LIVE buffers, continuous playout, signaling, and scheduling logic where PlayoutRequest represents assets loaded into preview for eventual live switching.

**What PlayoutRequest is:**

- **Preview asset instruction**: Instruction to Retrovue Air to load an asset into the PREVIEW buffer (forward-compatible API, even if Phase 8 simplifies this)
- **Channel-specific**: Each request targets a specific channel playout instance
- **Time-bound**: Defines presentation timestamp offset for playback
- **Mode-specific**: Specifies playout mode (LIVE or VOD)

**Retrovue Air's True Architecture (Forward-Compatible):**

Retrovue Air has **two internal players: preview and live**. The correct playout flow (implemented in future phases):

1. ChannelManager sends asset X → Air's **preview** buffer
2. Air signals back: **"preview is ready"**
3. ChannelManager tells Air: **"switch preview → live"**
4. Once switched, ChannelManager fetches the next asset and loads it into preview
5. This repeats forever → a **continuous playout chain**

**Phase 8 Simplification:**

In Phase 8, Air may play assets directly without preview/live switching for testing purposes. However, the PlayoutRequest API structure must remain forward-compatible with Air's true preview/live architecture. Even in Phase 8, PlayoutRequest conceptually represents an asset for preview, not a direct playout command.

**What PlayoutRequest is not:**

- Not a schedule entry (that's [ScheduleItem](ScheduleItem.md))
- Not a runtime record (that's [PlaylogEvent](PlaylogEvent.md))
- Not a playlist entry (that's [Playlist](../architecture/Playlist.md))

## Data Fields

PlayoutRequest is managed with the following canonical fields:

| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `asset_path` | string | Absolute path to media file | ✔ |
| `start_pts` | integer | Presentation timestamp offset (milliseconds) | ✔ |
| `mode` | `"LIVE"` \| `"VOD"` | Phase 8 uses "LIVE" only | ✔ |
| `channel_id` | string | Channel playout instance belongs to | ✔ |
| `metadata` | object | Passthrough metadata | ✖ |

### Field Details

- **asset_path**: Absolute local filesystem path to the media file to play. Must be accessible to Retrovue Air. Example: `/mnt/media/tv/Cheers_S01E03.mp4`
- **start_pts**: Presentation timestamp offset in milliseconds. For Phase 8, this is always `0`. Reserved for future use when supporting resume/seek operations.
- **mode**: Playout mode indicator. **MUST be uppercase**:
  - `"LIVE"`: Live broadcast mode (Phase 8 default)
  - `"VOD"`: Video-on-demand mode (reserved for future use)
  
  **Important:** The `mode` field MUST be uppercase (e.g., `"LIVE"`, not `"live"` or `"Live"`). This differs from ScheduleItem's `program_type` field which uses lowercase (e.g., `"series"`, `"movie"`).
- **channel_id**: Channel identifier (e.g., "retro1"). Identifies which channel playout instance this request targets.
- **metadata**: Optional object containing passthrough metadata from ScheduleItem. Retrovue Air MUST NOT inspect metadata beyond logging. Example contents may include commercial break types, bumper instructions, overlay configurations, etc.
  
  **Important:** Metadata can be:
  - Omitted entirely (field not present)
  - An empty object `{}`
  - An object with one or more key-value pairs
  
  Both omitted and empty `{}` are valid. Channel Manager must accept both forms when generating PlayoutRequests.

## Phase 8 Rules

For Phase 8 implementation:

- **start_pts is always 0**: Phase 8 always starts playback from the beginning of the asset. No seek/resume functionality.
- **mode is always "LIVE"**: Phase 8 operates exclusively in live broadcast mode. VOD mode is reserved for future phases.
- **Retrovue Air MUST NOT inspect metadata**: Retrovue Air should log metadata for debugging purposes but must not parse or act on metadata content. Metadata is opaque to the playout system in Phase 8.

## Phase 8 Limitations

**Phase 8-Only Behavior:**

In Phase 8, Channel Manager and Retrovue Air operate with the following limitations:

- **One PlayoutRequest per execution**: Channel Manager sends exactly one PlayoutRequest per Retrovue Air process execution. Channel Manager does not manage transitions or send follow-up items.
- **No transition management**: Channel Manager does not track when content ends or trigger automatic transitions to the next ScheduleItem.
- **No operator triggers**: Channel Manager does not handle immediate playout changes triggered by operators.
- **No content ending detection**: Channel Manager does not monitor Retrovue Air process status to detect when content playback ends.

**Phase 8 Execution Flow:**

1. Channel Manager loads schedule.json
2. Channel Manager selects active ScheduleItem based on current time
3. Channel Manager generates one PlayoutRequest
4. Channel Manager launches Retrovue Air process (if not running)
5. Channel Manager sends PlayoutRequest via stdin and closes stdin
6. Retrovue Air reads complete JSON and begins playout immediately
7. Retrovue Air plays the asset until end of file or process termination

Future phases will add transition management, follow-up request handling, and operator-triggered changes.

## Phase 8 vs Future Phases — PlayoutRequest Scope

### Phase 8 PlayoutRequest Scope

**NOTE: Phase 8 implements a simplified one-file playout pipeline for testing. Future phases add PREVIEW/LIVE buffers, continuous playout, signaling, and scheduling logic.**

**Phase 8 Simplified Behavior:**

In Phase 8, PlayoutRequest has a simplified scope for testing purposes:

- **PlayoutRequest contains only one asset_path**: Each PlayoutRequest references exactly one media file
- **Phase 8 simplified playout**: Air may play the file directly without preview/live switching (simplified for Phase 8 testing)
- **ChannelManager sends exactly one PlayoutRequest during runtime**: ChannelManager sends one PlayoutRequest when launching Air (when `client_count` transitions 0 → 1)
- **When the file finishes or last viewer disconnects, Air terminates**: Air continues playing until EOF or all clients disconnect (`client_count` drops to 0)
- **Preview/live architecture not yet active**: Air's preview/live architecture exists but is not actively used in Phase 8

**Important Forward-Compatible Design:**

Even though Phase 8 simplifies playout, **PlayoutRequest represents the next asset to load into PREVIEW**, not the next stream to output directly. This ensures forward compatibility with Air's true architecture:

- **Preview/live buffers exist**: Air has preview and live internal players (architecture exists, Phase 8 may not use fully)
- **Conceptual preview loading**: PlayoutRequest conceptually loads assets into preview, even if Phase 8 plays them directly
- **Future preview switching**: Future phases will implement "preview is ready" → "switch preview → live" → "load next into preview" flow
- **Continuous playout chain**: Future phases will create continuous playout chains via preview/live switching

**Phase 8 Limitations (Temporary Simplifications):**

- **Simplified playout**: Air may bypass preview/live switching and play assets directly (Phase 8 testing only)
- **No preview switching commands**: ChannelManager does not send "switch preview → live" commands (reserved for future phases)
- **No preview ready signals**: Air does not signal "preview is ready" back to ChannelManager (reserved for future phases)
- **No continuous chaining**: ChannelManager does not automatically load next assets into preview (reserved for future phases)
- **Single file per launch**: ChannelManager sends only one PlayoutRequest per Air launch (reserved for future phases: multiple PlayoutRequests for continuous chains)

### Future Phases PlayoutRequest Scope

In future phases, PlayoutRequest will expand to support more sophisticated playout operations:

**Extended PlayoutRequest Capabilities:**

- **"Load this into preview"**: PlayoutRequest will explicitly load assets into Air's preview buffer (architecture already exists, will be fully active)
- **"Switch preview → live"**: PlayoutRequest or separate commands will trigger preview → live transitions
- **"Preview is ready" signals**: Air will signal back to ChannelManager when preview buffer is ready
- **Continuous preview chaining**: ChannelManager will continuously load next assets into preview before current asset finishes
- **"Play this chain in order"**: Multiple PlayoutRequests will create continuous asset chains via preview/live switching
- **Slate/bumper control**: PlayoutRequest will support slate insertion and bumper management
- **Clock-based start cues**: PlayoutRequest will support time-based synchronization and start cues
- **Multi-asset support**: PlayoutRequest may contain multiple assets or asset sequences

**Future Phase Capabilities:**

- **Preview/live buffer management**: Air maintains preview and live buffers with seamless switching (architecture exists, fully active in future phases)
- **Live/preview switching**: Air will support seamless transitions between preview and live assets
- **Asset chaining via preview**: Continuous playout chains created by loading assets into preview, switching to live, then loading next into preview
- **Preview ready signaling**: Air signals "preview is ready" → ChannelManager sends "switch preview → live" → ChannelManager loads next asset into preview
- **Slate insertion**: PlayoutRequest will specify when and how to insert slates between content
- **Bumper management**: PlayoutRequest will control bumper insertion and management
- **Time synchronization**: PlayoutRequest will support clock-based cues for precise timing
- **Multiple PlayoutRequests**: ChannelManager will send multiple PlayoutRequests during runtime to maintain continuous preview chains

## Relationships

PlayoutRequest relates to:

- **ScheduleItem** (derived from): PlayoutRequests are generated from [ScheduleItem](ScheduleItem.md) entries when playout is ready to execute
- **Channel** (via `channel_id`): The [Channel](Channel.md) playout instance this request targets
- **Asset** (via `asset_path`): The physical [Asset](Asset.md) file that will be played
- **PlayoutPipeline**: PlayoutRequests are consumed by the [PlayoutPipeline](PlayoutPipeline.md) for execution

## Execution Model

PlayoutRequests are generated from [ScheduleItem](ScheduleItem.md) entries when playout is ready to begin:

1. **ScheduleItem Selection**: Select the next ScheduleItem to play based on current time and channel schedule
2. **Request Generation**: Create PlayoutRequest with asset path, timing, and mode
3. **Metadata Passthrough**: Copy metadata from ScheduleItem to PlayoutRequest unchanged
4. **Request Delivery**: Send PlayoutRequest to Retrovue Air for the target channel
5. **Playout Execution**: Retrovue Air receives the request and begins playout

**Request Timing (Phase 8):** In Phase 8, Channel Manager sends exactly one PlayoutRequest per Retrovue Air process execution:
- Channel Manager selects the active ScheduleItem based on current time
- Channel Manager generates one PlayoutRequest and sends it to Retrovue Air via stdin
- Channel Manager does not manage transitions or send follow-up items in Phase 8
- Channel Manager does not track when content ends or trigger immediate changes

**Request Timing (Future Phases):** In future phases, PlayoutRequests may be sent:
- Just before the scheduled start time (typically a few seconds ahead for buffering)
- For the next item in sequence when current content is ending
- When operators trigger immediate playout changes

**Asset Validation:** Before sending a PlayoutRequest:
- Verify that `asset_path` exists and is accessible
- Check file permissions and readability
- Validate that the asset format is supported by Retrovue Air

**Relationship to ScheduleItem:** PlayoutRequests are **derived from ScheduleItems** when playout is ready to execute:

- **One-to-one mapping**: Each PlayoutRequest corresponds to one ScheduleItem
- **Timing conversion**: ScheduleItem's `start_time_utc` determines when the PlayoutRequest is sent (but does not affect PlayoutRequest's `start_pts`)
- **Metadata passthrough**: ScheduleItem's `metadata` is copied unchanged to PlayoutRequest
- **Asset path**: ScheduleItem's `asset_path` becomes PlayoutRequest's `asset_path`

## ScheduleItem → PlayoutRequest Mapping

ChannelManager generates PlayoutRequests from ScheduleItems using the following formal mapping rules:

### Mapping Table

| ScheduleItem Field | PlayoutRequest Field | Mapping Rule |
|-------------------|---------------------|--------------|
| `asset_path` | `asset_path` | Direct copy (string → string) |
| `metadata` | `metadata` | Direct copy (object → object, or omitted → omitted, or `null` → `{}`) |
| `channel_id` | `channel_id` | Direct copy (string → string) |
| *(not used)* | `start_pts` | Always set to `0` in Phase 8 (not derived from ScheduleItem) |
| *(not used)* | `mode` | Always set to `"LIVE"` in Phase 8 (not derived from ScheduleItem) |
| `start_time_utc` | *(not mapped)* | Used only for selecting active ScheduleItem, not included in PlayoutRequest |
| `duration_seconds` | *(not mapped)* | Used only for selecting active ScheduleItem, not included in PlayoutRequest |
| `id` | *(not mapped)* | Not included in PlayoutRequest (may be included in metadata if needed) |
| `program_type` | *(not mapped)* | Not included in PlayoutRequest (may be included in metadata if needed) |
| `title` | *(not mapped)* | Not included in PlayoutRequest (may be included in metadata if needed) |
| `episode` | *(not mapped)* | Not included in PlayoutRequest (may be included in metadata if needed) |

### Mapping Rules

**Phase 8 Mapping Behavior:**

1. **asset_path**: Copy directly from ScheduleItem's `asset_path` field
2. **metadata**: Copy directly from ScheduleItem's `metadata` field:
   - If ScheduleItem has `metadata` (object), copy the entire object
   - If ScheduleItem has `metadata: null`, treat as empty object `{}` or omit (implementation choice)
   - If ScheduleItem omits `metadata`, PlayoutRequest may omit it or use `{}` (both valid)
3. **channel_id**: Copy directly from ScheduleItem's `channel_id` field
4. **start_pts**: Always set to `0` in Phase 8 (not derived from any ScheduleItem field)
5. **mode**: Always set to `"LIVE"` (uppercase) in Phase 8 (not derived from any ScheduleItem field)

**Important Notes:**

- **No temporal relationship**: ScheduleItem's `start_time_utc` is used only for selecting which item is active. It does not affect PlayoutRequest's `start_pts` (which is always `0` in Phase 8).
- **Case sensitivity**: `mode` MUST be uppercase `"LIVE"` (not `"live"` or `"Live"`). This differs from ScheduleItem's lowercase `program_type` values (e.g., `"series"`, `"movie"`).
- **Metadata handling**: Both omitted metadata and empty `{}` are valid in PlayoutRequest. Channel Manager should preserve the ScheduleItem's metadata format (if ScheduleItem has `{}`, PlayoutRequest can have `{}`; if ScheduleItem omits it, PlayoutRequest can omit it).
- **Unused fields**: ScheduleItem fields like `id`, `program_type`, `title`, `episode`, `start_time_utc`, and `duration_seconds` are not included in PlayoutRequest. If needed for debugging, they may be included in the `metadata` object.

**Pipeline Flow:**

```
ScheduleItem (resolved schedule entry)
    ↓
PlayoutRequest (playout instruction)
    ↓
Retrovue Air (actual playout execution)
```

## Retrovue Air Consumer Contract

Retrovue Air is the **consumer** of PlayoutRequest objects. This section defines the contract that Retrovue Air must implement to receive and process PlayoutRequests.

### Objective

Receive a PlayoutRequest and initiate playback of the specified asset.

### Responsibilities

1. **Parse CLI flags**: Process command-line arguments to determine operation mode
2. **Read full JSON object from STDIN if `--request-json-stdin` is present**: When the `--request-json-stdin` flag is provided, read a complete JSON object from standard input
3. **Deserialize into PlayoutRequest**: Parse the JSON input and deserialize it into a PlayoutRequest object, validating required fields
4. **Replace hardcoded file from Phase 7**: Use the `asset_path` from PlayoutRequest instead of hardcoded file paths used in Phase 7
5. **Start internal MPEG-TS pipeline using `asset_path`**: Initialize the MPEG-TS encoding pipeline using the asset file specified in `asset_path`
6. **Expose HTTP MPEG-TS endpoint (same as Phase 7)**: Provide the same HTTP endpoint for MPEG-TS stream access as implemented in Phase 7

### Non-Responsibilities

Retrovue Air explicitly does **not** handle:

- **Schedule logic**: Retrovue Air does not determine what should play or when; it only plays what it is told via PlayoutRequest
- **Playlist generation**: Retrovue Air does not generate or manage playlists; it plays single assets as specified
- **Transition management**: Retrovue Air does not manage transitions between multiple items; it plays one asset at a time
- **Multi-item playlists**: Retrovue Air plays a single asset per PlayoutRequest; it does not handle playlists with multiple items

### Implementation Requirements

**CLI Interface:**

Retrovue Air accepts the following command-line arguments:

### Required Arguments

- `--channel-id <id>`: Channel identifier (e.g., "retro1"). Overrides `channel_id` from JSON if both provided.
- `--mode live`: Phase 8 only; used for logging/routing inside Air. Must be set to "live" for Phase 8.
- `--request-json-stdin`: Causes Retrovue Air to block until it reads full JSON from stdin.

### CLI Behavior

| Argument | Behavior |
|----------|----------|
| `--request-json-stdin` | Causes Retrovue Air to block until it reads full JSON from stdin. When this flag is absent, Retrovue Air may use default behavior (e.g., hardcoded file for testing). |
| `--channel-id <id>` | Overrides `channel_id` from JSON if both provided. **CLI precedence rule:** If both JSON and CLI supply `channel_id`, Retrovue Air MUST use the CLI value. Channel Manager SHOULD NOT specify `channel_id` via CLI unless explicitly required by architecture. |
| `--mode live` | Phase 8 only; used for logging/routing inside Air. Must be set to "live" for Phase 8 operations. |

### Example CLI Usage

```bash
retrovue_air --channel-id retro1 --mode live --request-json-stdin
```

In this example:
- Retrovue Air will read PlayoutRequest JSON from stdin
- Channel ID is set to "retro1" (may be overridden by JSON if present)
- Mode is set to "live" for Phase 8 logging/routing
- Retrovue Air blocks until complete JSON is read from stdin

**JSON Parsing:**
- Retrovue Air must parse the complete JSON object from stdin
- Retrovue Air must validate that all required PlayoutRequest fields are present:
  - `asset_path` (required)
  - `start_pts` (required)
  - `mode` (required, MUST be uppercase: `"LIVE"` or `"VOD"`)
  - `channel_id` (required)
  - `metadata` (optional - may be omitted or empty `{}`)
- Retrovue Air must validate that `mode` is uppercase (e.g., `"LIVE"`, not `"live"`)
- Retrovue Air must accept both omitted `metadata` and empty `{}` as valid
- Retrovue Air must handle JSON parsing errors gracefully

### PlayoutRequest JSON Contract (stdin)

Channel Manager writes PlayoutRequest JSON to Retrovue Air's stdin. This is the complete contract for the stdin payload:

```json
{
  "asset_path": "/media/shows/beaver/S01E03.mp4",
  "start_pts": 0,
  "mode": "LIVE",
  "channel_id": "retro1",
  "metadata": {
    "schedule_item_id": "retro1-2025-11-15-2000",
    "program_type": "series",
    "title": "Leave It to Beaver",
    "episode": "S01E03",
    "commType": "NONE",
    "bumpers": []
  }
}
```

**Contractual Requirements:**

- **JSON must be complete (no streaming fragments)**: Channel Manager must send the complete JSON object in one write operation. Retrovue Air must read the complete JSON before parsing.
- **JSON must be sent once, then stdin closed**: After sending the PlayoutRequest JSON, Channel Manager closes stdin. Retrovue Air must read the complete JSON before stdin is closed.
- **Retrovue Air must begin playout immediately after stdin closes**: Once Retrovue Air has read the complete JSON and stdin is closed, it must begin playout immediately without waiting for additional signals or delays.
- **Retrovue Air must treat missing required fields as fatal errors**: If any required field (`asset_path`, `start_pts`, `mode`, `channel_id`) is missing, Retrovue Air must fail immediately with an error.
- **Unknown metadata keys are allowed and ignored**: Retrovue Air may log unknown metadata keys but must not fail if it encounters keys it does not recognize in the `metadata` object.

**Asset Playback:**
- Retrovue Air must use `asset_path` to locate and open the media file
- Retrovue Air must respect `start_pts` (Phase 8: always 0, start from beginning)
- Retrovue Air must operate in the mode specified by `mode` (Phase 8: always "LIVE")
- Retrovue Air must not inspect `metadata` beyond logging (per Phase 8 rules)

**Broken Asset Path Behavior:**
If `asset_path` does not exist or cannot be accessed, Retrovue Air must:
- **Fail loudly**: Exit immediately with a non-zero exit status
- **Emit error log**: Log the message `"FATAL: asset not found: <path>"` where `<path>` is the actual `asset_path` value
- **No recovery attempt**: Retrovue Air must not attempt to find alternative assets or use fallback content

**MPEG-TS Pipeline:**
- Retrovue Air must start its internal MPEG-TS encoding pipeline using the asset from `asset_path`
- Retrovue Air must expose an HTTP endpoint for MPEG-TS stream access (same interface as Phase 7)
- Retrovue Air must handle asset file errors according to the "Broken Asset Path Behavior" rules above

## Examples

### Example: Basic PlayoutRequest

```json
{
  "asset_path": "/mnt/media/tv/Cheers/Season2/Cheers_S02E05.mp4",
  "start_pts": 0,
  "mode": "LIVE",
  "channel_id": "retro1",
  "metadata": {
    "commType": "standard",
    "bumpers": {
      "intro": true,
      "outro": true
    }
  }
}
```

### Example: Minimal PlayoutRequest (No Metadata)

```json
{
  "asset_path": "/mnt/media/movies/Airplane_1980.mp4",
  "start_pts": 0,
  "mode": "LIVE",
  "channel_id": "retro1"
}
```

## Naming Rules

The canonical name for this concept in code and documentation is **PlayoutRequest**.

PlayoutRequests represent the interface between the scheduling system and the playout execution engine — they define "what Retrovue Air should play now" with all necessary execution parameters.

## Operator Workflows

**Request Inspection**: View PlayoutRequests sent to Retrovue Air to verify playout instructions. Each request shows the asset path, timing, mode, and metadata.

**Playout Verification**: Verify that PlayoutRequests match ScheduleItem entries and that asset paths are valid and accessible.

**Asset Validation**: Ensure that all PlayoutRequest asset paths reference accessible files. Validate that assets exist and are readable by Retrovue Air.

**Metadata Review**: Review metadata passed through to Retrovue Air. Note that Retrovue Air must not inspect metadata beyond logging (per Phase 8 rules).

**Playout Debugging**: Use PlayoutRequests to diagnose playout issues. Trace requests back to their source ScheduleItem entries and original schedule plans.

## See Also

- [ScheduleItem](ScheduleItem.md) - Schedule entries that generate PlayoutRequests
- [PlaylogEvent](PlaylogEvent.md) - Runtime execution records
- [Channel](Channel.md) - Channel configuration
- [PlayoutPipeline](PlayoutPipeline.md) - Playout execution pipeline
- [Asset](Asset.md) - Physical media files referenced by PlayoutRequests

