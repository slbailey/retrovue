_Related: [Architecture overview](ArchitectureOverview.md) • [System boundaries](SystemBoundaries.md) • [Domain: Source](../domain/Source.md)_

# Data flow

This describes how content moves through RetroVue from disk/library to screen.

## 1. Source → Collection → Asset

- An importer plugin (Source type) knows how to talk to something like Plex or a filesystem.
- Operator registers that Source: `retrovue source add ...`
- Operator discovers collections from that Source: `retrovue source discover <source_id>`
- Operator enables ingest on selected Collections.
- When ingest runs:
  - The importer returns DiscoveredItem objects for each item in that Collection.
  - The ingest service converts DiscoveredItem to Asset records.
  - Ingest-scope enrichers run (filename parser, TheTVDB, LLM synopsis, etc.).
  - Assets are persisted in the RetroVue catalog.

At this point the system "knows" about that content.

## 2. Scheduling / EPG / Playlog horizon

- The scheduler / EPG service assigns specific assets (episodes, bumpers, ad pods) into time slots per Channel.
- This creates a rolling future plan:
  - EPG horizon: coarse "9:00 Movie", "11:00 Cartoons".
  - Playlog horizon: fine-grained segments, ad pods, bumpers with timestamps.
- This timeline advances with real wall clock.

## 3. Producer

- When a viewer tunes a Channel, RetroVue asks: "What should be airing right now?"
- The Channel's configured Producer builds a base playout plan for the current moment.
- The plan includes:
  - ordered segments
  - offsets (if we are joining mid-show)
  - transitions between segments
  - any filtergraph directives required to compose layouts

## 4. Playout enrichers

- The Channel's playout-scope enrichers run in priority order.
- They decorate how the stream should look/feel (branding bug, lower-third, emergency crawl, VHS static aesthetic).
- They do NOT change what content airs; they change presentation.

## 5. ChannelManager and ffmpeg

- ChannelManager takes the final playout plan and launches ffmpeg.
- The ffmpeg process streams MPEG-TS (or equivalent transport) to viewers.
- If viewer count goes to zero, ChannelManager tears ffmpeg down.

## 6. As-run logging

- While the Channel "airs", ChannelManager/Producer/Playlog info is recorded into an as-run log.
- The as-run log is later used for auditing, promos, and analytics.

See also:

- [Source](../domain/Source.md)
- [Enricher](../domain/Enricher.md)
- [Playout pipeline](../domain/PlayoutPipeline.md)
- [Producer lifecycle](../runtime/ProducerLifecycle.md)
- [As-run logging](../runtime/AsRunLogging.md)
