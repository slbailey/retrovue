# RetroVue Runtime — ChannelManager

_Related: [Runtime: Schedule service](schedule_service.md) • [Runtime: Program director](program_director.md) • [Runtime: Renderer](Renderer.md) • [Domain: MasterClock](../domain/MasterClock.md)_

> Per-channel board operator that executes scheduled content playback on the air.

## Purpose

ChannelManager is responsible for executing scheduled content playback on the air. It receives ScheduledSegments from ScheduleService and plays them according to the precise timing specified.

**Lifecycle (post–PD/CM collapse):** ChannelManagers have **no autonomous lifecycle**. They exist only while in ProgramDirector's active registry. ProgramDirector is the sole authority for creation, health ticking, fanout attachment, and teardown. ChannelManagers never self-terminate or assume daemon semantics. Code: `pkg/core/src/retrovue/runtime/channel_manager.py` (no separate daemon module).

## Time and Rollover Behavior

ChannelManager receives ScheduledSegments and executes them.

**ChannelManager does not cut playback at broadcast day rollover.**

If content started at 05:00 and ends at 07:00, ChannelManager plays it straight through 06:00.

ChannelManager does not compute broadcast day, slot offsets, or rollover. It trusts ScheduleService.

ChannelManager uses MasterClock to determine "where are we right now in this content?" but it never uses datetime.now() directly.

**If ScheduleService says "this movie started at 05:00 and ends at 07:00," ChannelManager must honor that whole window without interruption, even if broadcast day rolled at 06:00.**

**ChannelManager is forbidden from fetching content or changing schedule.**

## Core Responsibilities

### 1. **Runtime Playback Control**

- Ask ScheduleService (Schedule Manager) what should be airing "right now" for this channel
- Use MasterClock to compute the correct offset into the current program (e.g. if a viewer shows up mid-episode at 21:05:33, don't restart from frame 0)
- Resolve the playout plan (content sequence, timing, etc.) and hand it to a Producer
- Ensure the correct Producer is active for the current mode (normal, emergency, guide)

### 2. **Producer Lifecycle & Fanout Model**

- Track active viewer sessions for this channel
- When the first viewer connects, start (or reuse) a Producer for this channel
- When the last viewer disconnects, stop and tear down the Producer
- Ensure there is never more than one active Producer for a channel at a time
- Swap Producers cleanly if ProgramDirector changes the global mode (e.g. emergency override)
- Surface the Producer's stream endpoint so viewers can attach

### 3. **Channel Policy Enforcement**

- Enforce channel-level restrictions and behavior (content restrictions, blackout handling, etc.)
- Obey ProgramDirector's global mode (normal vs emergency vs guide)
- Apply operational state (enabled/disabled, maintenance, etc.) for this channel

### 4. **Health, State, and Reporting**

- Track channel health and Producer status (starting / running / degraded / stopping)
- Keep runtime data like viewer_count, producer_status, and current mode
- Report that state upward to ProgramDirector
- Expose observability hooks (for dashboards / director console / analytics)
- ChannelManager is the authoritative status reporter for its channel; ProgramDirector and any operator UI should treat ChannelManager as the source of truth for on-air state and health

### 5. **Broadcast Day Support**

- **Seamless playback across 06:00 rollover** - Never interrupts ongoing content at broadcast day boundaries
- **Source-driven approach** - Continues playing content that spans the 06:00 boundary without interruption
- **No broadcast day computation** - Asks ScheduleService for current content rather than computing broadcast day labels
- **Rollover handling** - Properly manages programs that start before 06:00 and continue after 06:00

## Design Principles Alignment

ChannelManager is an Orchestrator (per-channel). Producers are Capability Providers that ChannelManager selects and controls. MasterClock is the only authority for "now" and ChannelManager is not allowed to compute time directly.

**Invariant:** A channel is either fully active or fully failed. There is no such thing as "partially started."

## Lifecycle Model: Viewer Fanout

The Producer only runs when there are active viewers.

- First viewer triggers Producer start
- Last viewer triggers Producer stop
- ChannelManager enforces this rule for its channel

ProgramDirector never directly starts or stops a Producer; it can only set global policy that ChannelManager must obey.

ViewerSession is observational and exists to drive fanout and analytics. ViewerSession never influences scheduling and cannot request content.

Viewers never talk to Producers directly; they attach via the stream endpoint exposed by ChannelManager.

## Relationship to Other Components

### ProgramDirector

- ChannelManager is subordinate to ProgramDirector
- ProgramDirector sets global operating mode (normal / emergency / guide)
- ChannelManager must obey that mode when choosing which Producer to run
- ProgramDirector may demand emergency override; ChannelManager is responsible for actually swapping the Producer
- ProgramDirector is allowed to ask "ensure channel X is on-air," but ProgramDirector is not allowed to micromanage ffmpeg or internal Producer state

### ScheduleService (Schedule Manager)

- ChannelManager is a read-only consumer of schedule data
- ChannelManager asks "what should be airing right now and at what offset?"
- ChannelManager is not allowed to:
  - edit schedules
  - backfill gaps
  - request "new content"
  - slide or retime assets
- If the schedule is bad or missing content, that is an upstream scheduling failure. ChannelManager must not improvise programming
- ChannelManager does not ask ScheduleService for future programming beyond what it needs to start or resume playout "right now." It is a runtime consumer, not a forward scheduler

### Producer

- ChannelManager selects, instantiates, and manages one Producer at a time for its channel
- ChannelManager calls Producer methods like start(), stop(), get_stream_endpoint(), and health()
- ChannelManager may replace the active Producer with a different Producer type (e.g. swap from NormalProducer to EmergencyProducer)
- ChannelManager is not allowed to reach into a Producer's internals (e.g. cannot manage an ffmpeg subprocess directly). It can only use the Producer interface defined in retrovue.runtime.producer.base

### Renderer

- ChannelManager manages the Renderer lifecycle (start, stop, switch) for its channel
- ChannelManager hands Producer input URLs to the Renderer for FFmpeg execution
- ChannelManager does not directly control FFmpeg; it uses the Renderer interface
- Renderer handles all FFmpeg process management, encoding, and stream delivery
- See [Runtime: Renderer](Renderer.md) for detailed documentation

### MasterClock

- ChannelManager must use MasterClock to determine "now" and offset into the current asset
- ChannelManager must never call system time directly
- ChannelManager relies on MasterClock timestamps to align viewers joining mid-program

### ViewerSession

- ChannelManager owns tracking of active ViewerSessions for that channel
- Each ViewerSession represents an active tuning/viewer
- ViewerSessions drive the fanout model (start/stop) and populate viewer_count
- ViewerSession does NOT drive scheduling decisions and cannot ask for new content

## Runtime Data Model

ChannelManager operates on Channel entities and tracks runtime state:

- **Channel.uuid** - External stable identifier for channel operations
- **viewer_count** - number of active ViewerSessions for this channel
- **producer_status** - current Producer state (stopped, starting, running, stopping, error)
- **current_mode** - mode (normal / emergency / guide)

ChannelManager must keep these in sync with reality and report them to ProgramDirector.

ChannelManager can query a Producer for ProducerState via get_state(), but does not own Producer's internals.

## Responsibilities

| Action                        | Description                                |
| ----------------------------- | ------------------------------------------ |
| **Read schedule data**        | "What should be airing right now + offset" |
| **Select and start Producer** | Based on viewer demand and global mode     |
| **Stop Producer**             | When viewer_count drops to 0               |
| **Surface stream endpoint**   | To viewers for attachment                  |
| **Report health/status**      | Up to ProgramDirector                      |

## Forbidden Actions

| Action                              | Reason                          |
| ----------------------------------- | ------------------------------- |
| **Invent or substitute content**    | When the schedule is wrong      |
| **Edit or write schedule data**     | ScheduleService owns scheduling |
| **Directly access Content Manager** | Or ingest systems               |
| **Spawn emergency content**         | Without ProgramDirector policy  |
| **Reach inside Producer internals** | E.g. directly control ffmpeg    |
| **Compute wall clock time**         | Must ask MasterClock            |

## Failure and Recovery Model

If a Producer crashes or reports degraded health:

- ChannelManager can attempt to restart the same Producer for the channel
- If ProgramDirector has set an emergency mode, ChannelManager can switch to the EmergencyProducer instead of retrying normal playout

ProgramDirector defines policy for what should happen on failure (e.g. go to emergency crawl), but ChannelManager actually performs the swap.

If ChannelManager cannot bring up any Producer for a channel, that channel is considered failed (not 'partially on').

## Broadcast Day Support

RetroVue uses a broadcast day model that runs from 06:00 → 06:00 local channel time instead of midnight → midnight. This is the standard model used by broadcast television and ensures proper handling of programs that span the 06:00 rollover.

### Key Principles

**ChannelManager NEVER snaps playout to the 06:00 broadcast day boundary.**

**ChannelManager is source-driven.** If a program started at 05:00 and runs until 07:00, ChannelManager continues it seamlessly past 06:00.

**ChannelManager does not attempt to "start the new broadcast day" at 06:00 in the middle of ongoing content.**

**ChannelManager does NOT compute broadcast day labels.** It asks ScheduleService what's playing "right now" given MasterClock.now_utc(), and uses that for playout offset only.

### Rollover Handling

When a program spans the 06:00 rollover boundary (e.g., a movie airing 05:00–07:00):

1. **Continuous Playback** - ChannelManager continues the program seamlessly across the boundary
2. **No Interruption** - No restart or cut occurs at 06:00
3. **Proper Offset Calculation** - Uses MasterClock to calculate the correct offset into the ongoing program
4. **Schedule Coordination** - ScheduleService handles broadcast day classification and rollover detection

### Implementation Notes

- ChannelManager relies on ScheduleService for broadcast day logic
- MasterClock provides consistent time references across rollover
- AsRunLogger may split continuous assets across broadcast days for reporting
- This approach prevents the "cut at 6am" bug common in broadcast systems

## Summary

ChannelManager is the per-channel board operator. It runs the fanout model. It is the only component that actually starts/stops Producers. It obeys ProgramDirector's global mode. It consumes the schedule but does not write it. It never chooses content; it only plays what it is told.

ChannelManager is how a RetroVue channel actually goes on-air.

**First viewer starts Producer, last viewer stops Producer** - this fanout rule is enforced by ChannelManager.

ChannelManager operates on Channel entities using UUID identifiers for external operations and logs.

## Cross-References

| Component                                  | Relationship                                                |
| ------------------------------------------ | ----------------------------------------------------------- |
| **[ScheduleService](schedule_service.md)** | Provides ScheduledSegments for playout execution            |
| **[MasterClock](../domain/MasterClock.md)**          | Provides authoritative station time for offset calculations |
| **[ProgramDirector](program_director.md)** | Sets global mode and emergency overrides                    |
| **[Renderer](Renderer.md)**                | Executes FFmpeg and manages output streams                  |
| **[AsRunLogger](asrun_logger.md)**         | Receives playback events for compliance logging             |

_Document version: v0.1 · Last updated: 2025-10-24_
