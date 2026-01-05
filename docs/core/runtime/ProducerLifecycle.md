_Related: [Domain: Playout pipeline](../domain/PlayoutPipeline.md) • [Runtime: Channel manager](channel_manager.md) • [Runtime: Renderer](Renderer.md) • [Developer: Plugin authoring](../developer/PluginAuthoring.md)_

# Producer lifecycle

## Purpose

Define how a Producer is configured, invoked, and used at runtime to generate a playout plan.

## Core model / scope

- Each Channel is associated with a configured Producer instance.
- A Producer is responsible for generating "what should air right now" in a structured way.
- Producers do not decorate presentation (no bugs, crawls, VHS noise). That is handled by playout enrichers.

## Contract / interface

A Producer plugin must expose something like:

- `build_playout_plan(now, channel_config, schedule_context) -> playout_plan`
  - ordered segments
  - timing / offsets, including mid-segment joins
  - transitions
  - optional filtergraph directives needed for layout or composition of those segments

The playout plan is structured data that ChannelManager can hand to a Renderer for FFmpeg execution after enrichment.

## Execution model

- ChannelManager calls the Producer when the first viewer tunes in, and also when it needs to update or recover the plan.
- The Producer may read schedule/EPG/Playlog info to determine exactly what asset (episode, bumper, ad pod) is "on" at `now`.
- The Producer can be stateful for caching, but it cannot launch ffmpeg itself.
- The Channel's playout enrichers run after Producer returns.

## Failure / fallback behavior

- If the Producer cannot produce a valid plan, ChannelManager logs and may fall back to a safe slate Producer (test pattern, standby screen, etc.).

## Naming rules

- "Producer" is always the module that generates the base playout plan.
- A "Producer instance" is a configured instance registered via CLI.
- "Playout plan" is the structured output of the Producer before enrichers modify it.

See also:

- [Enricher](../domain/Enricher.md)
- [Playout pipeline](../domain/PlayoutPipeline.md)
- [Runtime: Renderer](Renderer.md) - How producers' input sources are converted to output streams
- [Plugin authoring](../developer/PluginAuthoring.md)
