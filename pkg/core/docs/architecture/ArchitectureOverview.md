_Related: [Data flow](DataFlow.md) • [System boundaries](SystemBoundaries.md) • [Runtime: Channel manager](../runtime/ChannelManager.md)_

# Architecture overview

RetroVue presents as a continuous TV network with multiple Channels. Viewers can "tune in" at any time and see whatever is "on right now."

Key ideas:

- Channels are logical and persistent. A Channel always exists in the database even if nobody is watching.
- We do not burn CPU 24/7. We only spin up ffmpeg when there is at least one active viewer on that Channel.
- The system keeps a virtual schedule for each Channel so we always know what _should_ be airing at any wall-clock moment.

Major layers:

1. Scheduling / EPG / Playlog

   - Builds a future plan for each Channel: what show, which episode, which ad pod, at what timestamp.
   - Exists ahead of real time (EPG horizon ~days, Playlog horizon ~hours).

2. Playout pipeline

   - A Producer turns "what should be airing right now" into a playout plan: ordered segments, offsets, transitions.
   - Playout-scope enrichers decorate that plan (branding bug, lower-third, emergency crawl, etc.).
   - Output: a final playout plan that ffmpeg can execute.

3. Runtime / ChannelManager

   - ChannelManager owns live ffmpeg for that Channel.
   - First viewer in: build playout plan and launch ffmpeg.
   - Last viewer out: tear down ffmpeg, but the Channel timeline keeps advancing logically.

4. Operator surface

   - Operators configure Sources, Collections, Enrichers, Producers, and Channels using the `retrovue` CLI.
   - Nothing auto-runs without operator intent (e.g. ingest is explicit).

5. Plugin surface
   - Importer plugins return DiscoveredItems from Sources (plex, filesystem, etc.).
   - Enricher plugins add metadata or decorate playout.
   - Producer plugins generate base playout plans.
   - All plugins are registered through registries and surfaced in the CLI.

See also:

- [Scheduling system architecture](SchedulingSystem.md) - Detailed scheduling system architecture
- [Data flow](DataFlow.md)
- [Playout pipeline](../domain/PlayoutPipeline.md)
- [Channel manager](../runtime/ChannelManager.md)
