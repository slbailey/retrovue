_Related: [Architecture](../architecture/ArchitectureOverview.md) • [Runtime: Channel manager](../runtime/channel_manager.md) • [Runtime: Renderer](../runtime/Renderer.md) • [Operator CLI](../cli/README.md)_

# Domain — Playout pipeline

## Purpose

Define how RetroVue turns scheduled programming into an actual MPEG-TS stream for viewers. This includes producer selection, playout plan assembly, playout enrichers, and ffmpeg launch.

## Core model / scope

A Channel is a continuously programmed virtual linear feed.

Channels always exist in the database, with identities, branding, etc., even if nobody is currently tuned in.

Each Channel is associated with:

- A currently active Producer instance
- A list of playout-scope enrichers (with priorities)
- Channel-level branding and presentation rules

Viewer activity does not define the Channel. Viewer activity only decides whether we spin up a live ffmpeg process.

## Contract / interface

**Note:** There are two related but distinct concepts in RetroVue:

1. **Input Producers** (in `adapters/producers/`): Modular source components that provide FFmpeg-compatible
   input specifiers (files, test patterns, network streams). The lifecycle contract for producer selection
   and execution lives in [Runtime: Producer lifecycle](../runtime/ProducerLifecycle.md).

2. **Playout Plan Producers** (in `runtime/producer/`): Components that generate playout plans from schedules. These determine "what to air" based on schedule context, then select appropriate Input Producers to provide the actual media sources.

A Producer (in the playout plan sense) is a module responsible for generating a base playout plan. Producers generate the "what to air" plan, not how to render it (no ffmpeg launch).

### Asset vs Segment Distinction

**Critical Distinction:** Playout cares about segments derived from scheduled assets:

- **Asset** = what we air conceptually ("Transformers S01E03")
- **Segment** = the actual chunk+offset+overlays we're feeding ffmpeg right now

**Flow:**

1. **PlaylogEvent** references one asset
2. **Playout pipeline** turns that into one or more segments fed to ffmpeg, maybe with overlays
3. **Segment** contains the actual media file path, timing offsets, and any overlays or filters

This distinction protects against reintroducing "broadcast asset" as a separate entity - assets are the conceptual content, segments are the technical playout instructions.

Examples:

- Linear content Producer (scheduled shows + ad breaks)
- Guide/Prevue Producer (EPG grid scroll + promo window)
- Holiday fireplace / yule log Producer
- Weather radar Producer
- Test pattern Producer

Producers are registered in the Producer Registry. The Producer Registry is structurally similar to the Source Registry and Enricher Registry:

- `retrovue producer list-types`
- `retrovue producer add --type <type> --name <label> [config...]`
- `retrovue producer list`
- `retrovue producer update <producer_id> ...`
- `retrovue producer remove <producer_id>`

Channels reference a specific configured Producer instance.

## Execution model

A playout plan is the structured description of what should be streaming right now for a channel, including:

- ordered segments (media files, bumpers, ad pods)
- timing offsets / join offsets
- transitions between segments
- any ffmpeg filtergraph directives needed for composition

The Producer generates the base playout plan for "now" using schedule and timing information (e.g. from EPG / playlog horizon). The plan converts scheduled assets into playout segments with specific timing and overlay instructions.

After the Producer returns the base playout plan, RetroVue applies any playout-scope enrichers attached to that Channel in priority order.

Playout enrichers can modify transitions, add branding bugs, add lower-thirds, inject an emergency crawl, etc.

Playout enrichers do not choose what content airs; they decorate how it airs.

If a playout enricher fails, RetroVue logs the failure and continues with the most recent valid plan.

After playout enrichment, the final playout plan is given to the Renderer for FFmpeg execution.

The ChannelManager manages the Renderer lifecycle, which owns the live FFmpeg process.

When the first viewer tunes in, ChannelManager asks for "what should be airing right now + offset", generates the playout plan via Producer + playout enrichers, selects the Producer's input source, and starts the Renderer to execute FFmpeg.

When the last viewer leaves, ChannelManager stops the Renderer (which tears down FFmpeg). The Channel itself still logically "continues to air" on the master schedule.

## Failure / fallback behavior

If a playout enricher fails when assembling the playout plan for a channel, RetroVue falls back to the most recent successful version of the plan without that enricher's mutation.

## Naming rules

- "Producer" always means a module that can generate a playout plan for a Channel at a given moment in time.
- "Playout plan" is the Producer's output, optionally modified by playout enrichers, and used to drive ffmpeg.
- "Channel" is the persistent concept of a linear feed with identity, schedule, and branding. A Channel may or may not currently have an ffmpeg process running.

## See also

- [Enricher](Enricher.md) - Playout enricher details
- [Channel manager](../runtime/channel_manager.md) - Stream execution and Renderer lifecycle
- [Renderer](../runtime/Renderer.md) - FFmpeg execution and output stream management
- [Producer lifecycle](../runtime/ProducerLifecycle.md) - Producer management
- [Operator CLI](../cli/README.md) - Operational procedures
