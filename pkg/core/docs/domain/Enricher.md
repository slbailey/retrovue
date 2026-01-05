_Related: [Architecture](../architecture/ArchitectureOverview.md) • [Runtime](../runtime/ChannelManager.md) • [Operator CLI](../cli/README.md)_

# Domain — Enricher

## Purpose

Enricher defines a pluggable module that adds value to an object and returns the improved object. Enrichers are stateless pure functions: they receive an object and return the updated object; they do not persist and they do not own orchestration. Enrichers are optional and may be applied in sequence.

## Core model

Enrichers are identified by their type, which determines both their functionality and when they are allowed to run.

**type=ingest**
Input: Asset generated during ingest.
Output: Asset with richer metadata.
Examples:

- Parse .nfo / .jpg sidecar files (tinyMediaManager style).
- Pull metadata from TheTVDB / TMDB.
- Use an LLM to generate synopsis, parental guidance tags, and ad-break markers.

**type=playout**
Input: a playout plan for a channel (the assembled "what to stream now" structure before ffmpeg is launched).
Output: a modified playout plan.
Examples:

- Apply crossfade between segments instead of hard cuts.
- Add a network watermark bug.
- Add an "Up Next" lower-third.
- Add an emergency crawl/ticker.
- Apply VCR/noise aesthetic.

## Contract / interface

Each enricher must implement:

- a unique type identifier (e.g. ingest, playout)
- a parameter spec describing its enrichment parameters (for CLI help)
- apply(input) -> output, where input and output types depend on the enricher type

Enrichers must be pure in the sense that they receive an object and return a new or updated version of that object. Enrichers do not perform persistence themselves.

Enrichers must tolerate being skipped. The system is allowed to run zero enrichers.

## Removal Safety Metadata

Each enricher instance MUST track whether it is protected from removal in production.

**protected_from_removal** (bool, default false)

- `true` means removing this enricher in production would create harm, and the system MUST block removal even with `--force`.
- `false` means the enricher may be removed when it is not actively in use.

This flag is evaluated by the removal command, not by the enricher itself.

## Production Safety Philosophy

Enricher removal is governed by a harm-prevention philosophy rather than static categories. The system prevents removal of enrichers that would cause harm to running or future operations.

**Harm Definition:**

- Breaking an active process
- Violating an operational expectation
- Leaving the system in an invalid state

**Safety Criteria:**

1. **Active Usage**: Enricher is currently in use by an active ingest or playout operation
2. **Explicit Protection**: Enricher is marked as `protected_from_removal = true`

**Environment Behavior:**

- **Production**: Strict safety checks enforced, `--force` cannot override safeguards
- **Non-Production**: Permissive behavior, no safety checks applied

**Historical Usage**: Past usage is not considered harmful unless the enricher is explicitly protected from removal.

## Enrichment Parameters

Enrichers require specific parameters to perform their enrichment tasks. These parameters vary by enricher type and implementation:

**Ingest Enrichers:**

- **FFmpeg/FFprobe enrichers**: Typically require no parameters (use system defaults)
- **TheTVDB enrichers**: Require `--api-key` for API authentication
- **TMDB enrichers**: Require `--api-key` for API authentication
- **File parser enrichers**: May require `--pattern` for filename parsing rules
- **LLM enrichers**: Require `--model`, `--api-key`, and `--prompt-template`

**Playout Enrichers:**

- **Watermark enrichers**: Require `--overlay-path` for watermark image location
- **Crossfade enrichers**: Require `--duration` for transition timing
- **Lower-third enrichers**: Require `--template-path` and `--data-source`
- **Emergency crawl enrichers**: Require `--message` and `--speed`

**Parameter Updates:**
The `enricher update` command allows modification of these enrichment parameters without recreating the enricher instance. Some enrichers may not require updates (e.g., FFmpeg enrichers using system defaults), while others may need frequent updates (e.g., API keys for external services).

## Execution model

Enrichers run under orchestration, not autonomously.

**Ingest orchestration:**

After an importer produces Asset objects for a Collection, RetroVue looks up which ingest-type enrichers are attached to that Collection.

RetroVue runs those enrichers in priority order.

The final enriched Asset is then stored in the RetroVue catalog.

**Playout orchestration:**

After a Producer generates a base playout plan for a Channel, RetroVue looks up which playout-type enrichers are attached to that Channel.

RetroVue runs those enrichers in priority order.

The final enriched playout plan is used to launch ffmpeg.

Collections can have 0..N ingest enrichers attached.

Channels can have 0..N playout enrichers attached.

Each attachment has an integer priority or order.

Enrichers are applied in ascending priority.

This resolves conflicts such as:

- "Filename parser" sets a title.
- "TheTVDB enricher" fills missing fields but does not overwrite certain fields.
- "LLM enricher" writes synopsis and content warnings last.

## Failure / fallback behavior

Enrichers are not permitted to block ingestion or playout by default.

If an enricher fails on a single Asset during ingest, that error is logged and ingest continues with the partially enriched asset.

If a playout enricher fails when assembling the playout plan for a channel, RetroVue falls back to the most recent successful version of the plan without that enricher's mutation.

Fatal stop conditions (skip entirely) are defined outside the enricher layer:

- Collection not allowed (sync_enabled=false)
- Collection path not resolvable / not reachable
- Importer cannot enumerate assets

## Operator workflows

**retrovue enricher list-types**
List known enricher types available in this build.

**retrovue enricher add --type <type> --name <label> [config...]**
Create an enricher instance. Stores configuration values such as API keys, fade duration, watermark asset path.

**retrovue enricher list**
Show configured enricher instances.

**retrovue enricher update <enricher_id> [enrichment-parameters...]**
Update enrichment parameters for an enricher instance. The specific parameters depend on the enricher type:

- **FFmpeg enrichers**: No parameters needed (informs user updates are not necessary)
- **TheTVDB enrichers**: `--api-key <new-key>` to update API credentials
- **Metadata enrichers**: `--sources <comma-separated-list>` to update data sources
- **Custom enrichers**: Type-specific parameters as defined by the enricher implementation

**retrovue enricher remove <enricher_id>**
Remove configuration.

**retrovue source <source_id> attach-enricher <enricher_id> --priority <n>**
Attach an ingest-type enricher to all Collections in a Source.

**retrovue source <source_id> detach-enricher <enricher_id>**
Detach an ingest-type enricher from all Collections in a Source.

**retrovue collection attach-enricher <collection_id> <enricher_id> --priority <n>**
Attach an ingest-type enricher to a Collection.

**retrovue collection detach-enricher <collection_id> <enricher_id>**

**retrovue channel attach-enricher <channel_id> <enricher_id> --priority <n>**
Attach a playout-type enricher to a Channel.

**retrovue channel detach-enricher <channel_id> <enricher_id>**

## Naming rules

The word "enricher" is universal. We do not use "enhancer," "overlay stage," or "post-processor."

- "ingest enricher" means an enricher with type=ingest.
- "playout enricher" means an enricher with type=playout.
- "Asset" is the ingest-time object before catalog promotion.
- "Playout plan" is the channel's assembled output plan prior to ffmpeg launch.

## See also

- [Playout pipeline](PlayoutPipeline.md) - Live stream generation
- [Channel manager](../runtime/ChannelManager.md) - Stream execution
- [Operator CLI](../cli/README.md) - Operational procedures
