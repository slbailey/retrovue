_Related: [Documentation standards](../standards/documentation-standards.md) • [Architecture overview](architecture/ArchitectureOverview.md) • [Runtime: Channel manager](runtime/channel_manager.md)_

# Glossary

Short authoritative definitions for internal terms. Use these spellings and meanings consistently.

## Content Layer

**Asset**  
The leaf unit RetroVue can eventually broadcast. Each asset belongs to exactly one collection and has a lifecycle state (`new`, `enriching`, `ready`, `retired`) indicating its readiness for scheduling. Only assets in `ready` state are eligible for broadcast.

**Collection**  
A logical grouping of related content from a source (e.g., "The Simpsons", "Classic Movies", "Commercials"). Collections organize content into broadcast-relevant categories.

**Source**  
An origin of media content (e.g., Plex server, local filesystem, ad library). Sources are discovered and enumerated to find available content.

## Scheduling Layer — Planned (Tier 1)

**SchedulableAsset**
Abstract base for all schedule entries. Concrete types: [Program](#program), [Asset](#asset), [VirtualAsset](#virtualasset), SyntheticAsset. SchedulableAssets are placed in Zones within SchedulePlans and resolve to physical assets during Tier 2 resolution.

**Program**
[SchedulableAsset](#schedulableasset) type that represents a logical collection with metadata and playback policies. Contains `asset_chain` (linked list of SchedulableAssets: Programs, Assets, VirtualAssets, SyntheticAssets) and `play_mode` (random, sequential, manual). Programs resolve to concrete files via linked chain expansion and pool selection during Tier 2 resolution. See [Program](domain/Program.md).

**VirtualAsset**
[SchedulableAsset](#schedulableasset) type that represents an input-driven composite template (e.g., "SpongeBob Episode Block" = intro + 2 episodes). VirtualAssets are indistinguishable from regular Assets at scheduling time but expand into one or more physical Assets during Tier 2 resolution. See [VirtualAsset](domain/VirtualAsset.md).

**ScheduleDay**
Resolved, immutable daily schedule for a specific channel and calendar date. Contains ScheduleItems placed in Zones with real-world wall-clock times. Derived from SchedulePlans, resolved 3–4 days in advance, and serves as the foundation for EPG generation. ScheduleDay is frozen after generation unless force-regenerated or manually overridden. See [ScheduleDay](domain/ScheduleDay.md).

**ScheduleItem**
The canonical, persistent unit of editorial scheduling. Defines a single airing on a channel's timeline: one grid-aligned program slot selected by the scheduling system. Created during DSL schedule compilation. Replaces the previous `program_blocks` representation. Provides direct SQL inspection, targeted operator modifications, and deterministic expansion into PlaylistEvents. See [ScheduleItem](../../docs/domains/ScheduleItem.md).

**EPG**
Electronic program guide. High-level future schedule for a Channel ("9:00 Movie", "11:00 Cartoons"). Typically planned days ahead. Derived from [ScheduleDay](#scheduleday).

## Scheduling Layer — Execution (Tier 2)

**PlaylistEvent**
Execution-intent unit representing a single time-bounded instruction for playout. Derived from [ScheduleItem](#scheduleitem) during Tier 2 resolution. Contains segment structure (content, filler, pad, transition), wall-clock timestamps, and resolved asset references. PlaylistEvents tile the timeline without gaps or overlaps within a channel. See [PlaylistEvent](../../docs/domains/playout/PlaylistEvent.md).

**ExecutionSegment**
Frame-accurate playback instruction derived from [PlaylistEvent](#playlistevent). The final Core-produced artifact before handoff to AIR. Contains seek positions, asset URIs, PTS offsets, and segment-level metadata. See [ExecutionSegment](../../docs/domains/playout/ExecutionSegment.md).

**BlockPlan**
The AIR execution unit fed via gRPC (`FeedBlockPlan`). Contains a sequence of ExecutionSegments for a single time window. Core feeds BlockPlans to AIR; AIR executes them frame-accurately. See [BlockPlanFeedingContract](../../docs/contracts/core/BlockPlanFeedingContract.md).

**AsRun**
Observed ground truth — what actually aired during playout execution. Records what was observed during playout, including actual timestamps from MasterClock. AsRun can be compared to the planned PlaylistEvents to identify discrepancies between planned and actual playout.

## Channel & Runtime

**Channel**  
A persistent virtual linear feed with identity, schedule, branding, and attached enrichers. A Channel exists even if nobody is watching.

**ChannelManager**  
Runtime controller that decides when to start ffmpeg for a Channel, what playout plan to feed it, and when to tear it down. See [ChannelManager](runtime/channel_manager.md).

**Producer**  
Output-oriented runtime component that drives playout. Examples: AssetProducer, SyntheticProducer, future LiveProducer. ffmpeg is not a Producer; it's the playout engine that Producers feed.

**Producer Registry**  
Registry where Producer plugin types are registered and configured for Channels.

**MasterClock**  
Authoritative "now" for scheduling, playout, and logging decisions. All timing aligns to MasterClock.

**Segment**  
A concrete playout chunk derived from a scheduled asset. A segment contains file path(s), time offsets, and overlay instructions that ffmpeg will actually execute. Assets are conceptual content; segments are executable playout instructions.

**Enricher**  
Pluggable module that takes an input object and returns an updated version of that object.

- `scope=ingest`: operates on Asset during ingest enrichment.
- `scope=playout`: operates on a playout plan before ffmpeg launch.  
  Enrichers are ordered and can be attached to Collections (ingest) or Channels (playout).

Ingest enrichers are allowed to mutate asset metadata and state (e.g. move new → enriching → ready).  
Playout enrichers do not mutate assets; they decorate playout segments.

**Broadcast Day**  
24-hour period starting at channel's broadcast_day_start (e.g., 06:00). Human-readable times in plan show and ScheduleDay views reflect broadcast-day offset.

**Operator**  
A human configuring Sources, Collections, Channels, Producers, and Enrichers using the CLI.

## Canonical Pipeline

```
SchedulePlan → ScheduleRevision → ScheduleItem → PlaylistEvent → ExecutionSegment → BlockPlan → AIR → AsRun
```

**Tier 1 (Editorial)**
The planning layer that operates days in advance: [SchedulePlan](domain/SchedulePlan.md) → [ScheduleRevision](../../docs/domains/scheduling/ScheduleRevision.md) → [ScheduleItem](#scheduleitem). ScheduleDay is a derived grouping of ScheduleItems by broadcast_day, not an authority. Contains editorial intent. Frozen and immutable once generated.

**Tier 2 (Execution)**
The resolution layer that operates hours ahead: [PlaylistEvent](#playlistevent) → [ExecutionSegment](#executionsegment) → [BlockPlan](#blockplan). Resolves editorial intent into concrete playout instructions. Immutable once inside the locked execution window.

**Runtime**
AIR renders ExecutionSegments frame-accurately. [AsRun](#asrun) records what actually played. Aligned to MasterClock.

See also:

- [Documentation standards](../standards/documentation-standards.md)
- [Channel manager](runtime/channel_manager.md)
- [Producer lifecycle](runtime/ProducerLifecycle.md)
- [ScheduleDay](domain/ScheduleDay.md)
- [PlaylistEvent](../../docs/domains/playout/PlaylistEvent.md)
- [ExecutionSegment](../../docs/domains/playout/ExecutionSegment.md)
