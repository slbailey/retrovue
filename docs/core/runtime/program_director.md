# RetroVue Runtime — ProgramDirector

_Related: [Runtime: Channel manager](channel_manager.md) • [Runtime: Schedule service](schedule_service.md) • [Domain: MasterClock](../domain/MasterClock.md)_

> Global coordinator and emergency controller for system-wide broadcast operations.

## Purpose

ProgramDirector coordinates channels and can trigger emergency overrides. It provides system-wide coordination and monitoring capabilities without being involved in scheduling decisions.

**ProgramDirector cannot redefine schedule or override 06:00 rollover.**

## Coordination, Not Scheduling

ProgramDirector coordinates channels and can trigger emergency overrides.

ProgramDirector may ask ScheduleService "what's airing right now?" and "what broadcast day are we in?" for dashboards/UX.

ProgramDirector is not allowed to redefine slot alignment, force a new day at rollover, or schedule future blocks itself.

ProgramDirector never assumes 6:00am is "free." It must consult ScheduleService, which may say "the previous day's carryover still runs until 07:00."

**ProgramDirector is not a scheduler. It cannot force a content reset at broadcast day rollover.**

**ProgramDirector coordinates but does not schedule.**

## Core Responsibilities

### 1. **Global Coordination & Policy**

- **Coordinate all channels** and ensure consistent operation
- **Enforce system-wide policies** for content, timing, and viewer management
- **Manage emergency overrides** and system-wide mode changes
- **Provide system director capabilities** for operational control

### 2. **Per-Channel Runtime Control**

- **Manage ChannelManager instances** for each active channel
- **Coordinate content playback** based on schedule data
- **Handle channel-specific policies** and restrictions
- **Monitor channel health** and performance

### 3. **Producer Lifecycle & Playout Control**

- **Ensure each channel has an active Producer when needed, and no more than one at a time**
- **Select which Producer type should be active** (normal programming, emergency, guide, slate) based on global/system mode
- **Coordinate seamless transitions** between Producer types when system mode changes (e.g. emergency override)
- **Expose the Producer's output location** so viewers can attach

ChannelManager is responsible for actually starting and stopping Producers for its channel. ProgramDirector sets global mode and policy (normal, emergency, guide), but it does not directly spawn ffmpeg or manage Producer processes.

### 4. **Viewer Session Management**

- **Track viewer connections** and session state
- **Implement fanout model** for efficient resource usage
- **Manage Producer lifecycle** based on viewer demand
- **Handle graceful scaling** up and down

### 5. **Broadcast Day Coordination**

- **Coordinate channels** but does NOT redefine broadcast day logic
- **Ask ScheduleService** for current broadcast day or rollover information
- **Respect in-progress longform content** (e.g. movies spanning 05:00–07:00)
- **Treat broadcast day as reporting/scheduling grouping** rather than playout cut point

## Design Principles Alignment

The Program Director follows RetroVue's architectural patterns:

- **ProgramDirector and ChannelManager** act as Orchestrators
- **MasterClock** is an Authority over time
- **Producer implementations** are Capability Providers
- **Unit of Work** is used for any critical state changes that must succeed or fail as a whole (e.g. switching all channels into emergency mode)

**Invariant:** A channel is either fully active or fully failed. There is no such thing as a 'partially active' channel.

## System Boundaries

## Responsibilities

| Action                                | Description                                     |
| ------------------------------------- | ----------------------------------------------- |
| **Coordinate all channel operations** | System-wide broadcast coordination              |
| **Manage viewer sessions and fanout** | First viewer starts Producer, last viewer stops |
| **Handle emergency overrides**        | System-wide mode changes                        |
| **Coordinate broadcast streams**      | Output generation across channels               |
| **Enforce system-wide policies**      | Global operational rules                        |

## Forbidden Actions

| Action                                | Reason                                |
| ------------------------------------- | ------------------------------------- |
| **Generate schedules or programming** | ScheduleService owns scheduling       |
| **Ingest content or manage library**  | Content Manager owns content          |
| **Handle content discovery**          | Or metadata extraction                |
| **Manage external content sources**   | Outside scope of runtime coordination |

> **Key Principle:** Program Director is the **runtime coordinator** for broadcast operations. It consumes schedule data from Schedule Manager and content data from Content Manager—it doesn't generate or discover content itself.

## Core Data Model

All runtime information is stored in SQLAlchemy models. These represent the "source of truth" for what's currently playing and how the system is operating.

### Channel

Represents a broadcast channel with its runtime state and configuration.

**Key Properties:**

- `id` - Internal database primary key
- `uuid` - External stable identifier exposed to API, runtime, and logs
- `name` - Human-readable channel name
- `timezone` - Channel's time zone for scheduling
- `is_active` - Whether channel is active
- `current_mode` - Current operational mode (normal, emergency, guide)
- `viewer_count` - Number of active viewers
- `producer_status` - Status of the Producer (stopped, starting, running, stopping) (runtime field; reflects current Producer state and is not long-term schedule state)

**Relationships:**

- Has many ViewerSession records (active viewers)
- Has one Producer record (current output generator)
- Links to ChannelManager (runtime controller)

### ViewerSession

Represents an active viewer connection to a channel.

**Key Properties:**

- `id` - Internal database primary key
- `channel_id` - Which channel the viewer is watching
- `session_id` - Unique session identifier
- `started_at` - When the session began
- `last_activity` - Last activity timestamp
- `client_info` - Client device/browser information
- `stream_url` - Ephemeral per-session URL or handle for attaching to the current channel fanout stream

**Relationships:**

- Belongs to Channel
- Links to Producer (through channel)

ViewerSession is observational. It exists to track active viewers and drive fanout rules. It never influences scheduling and it cannot request content.

## Producer Protocol (Capability Provider)

The Producer is the component that actually emits audiovisual output for a channel (e.g. via ffmpeg, an emergency slate, or a guide channel).
Producers are swappable. ChannelManager chooses which Producer implementation to run for a channel.
All Producers must implement the same interface so ChannelManager can control them in a consistent way.

```python
class Producer(ABC):
    def start(self, playout_plan, start_at_station_time) -> bool: ...
    def stop(self) -> bool: ...
    def play_content(self, content_segment) -> bool: ...
    def get_stream_endpoint(self) -> Optional[str]: ...
    def health(self) -> str: ...
    def get_state(self) -> ProducerState: ...
    def get_producer_id(self) -> str: ...
```

**Required contract:**

- `start(playout_plan, start_at_station_time)` - Begin output for this channel. `playout_plan` is the resolved segment sequence that should air, and `start_at_station_time` (from MasterClock) allows us to join mid-program instead of always starting at frame 0. Returns True on successful startup.
- `get_stream_endpoint()` - Return a handle / URL / socket description that viewers can attach to.
- `health()` - Report whether the Producer is running, degraded, or stopped.
- `stop()` - Cleanly terminate output.
- `get_state()` - Return a structured snapshot (ProducerState) of the current producer: mode, status, started_at, output_url, etc.

A Producer is not allowed to:

- Query Content Manager directly
- Query Schedule Manager directly
- Pick its own content
- Modify horizons or scheduling data

It only executes the playout plan it was given.

Producer implementations will live under retrovue/runtime/producer/:

base.py – ProducerProtocol / BaseProducer interface + shared types

normal_producer.py – normal programming playout (typically ffmpeg-driven)

emergency_producer.py – emergency crawl / takeover mode

guide_producer.py – "TV guide channel" / listings output

All of them share a common interface in `producer/base.py`.

Example: NormalProducer (normal_producer.py) will ultimately launch and supervise an ffmpeg pipeline using a concat plan provided by ChannelManager.

## Major Services

### ProgramDirector

**File:** `src/retrovue/runtime/program_director.py`

**Role:** Global coordinator and policy layer for the entire broadcast system.

**Design Pattern:** Orchestrator + Policy Enforcer

**Key Responsibilities:**

- **Coordinate all channels at a system level**
- **Enforce global policy and mode** (normal vs emergency)
- **Trigger system-wide emergency override and revert**
- **Report system health and status**

**Important Behaviors:**

- **Global coordination** - Manages all channels as a unified system
- **Policy enforcement** - Applies system-wide rules and restrictions
- **Emergency handling** - Can override all channels to emergency mode
- **Resource management** - Coordinates shared resources across channels
- **Health monitoring** - Tracks system performance and alerts

**Authority Rule:**
ProgramDirector is the single authority over global operating mode (normal vs emergency) and system-wide overrides.
It is not the authority over schedule state, channel scheduling, or content approval. Those belong to ScheduleService and LibraryService.

**ProgramDirector never directly spawns or stops Producer instances and never talks to ffmpeg. That work is delegated to each ChannelManager.**

### ChannelManager

**File:** `src/retrovue/runtime/channel_manager.py`

**Role:** Per-channel runtime controller that manages individual channel operations.

**Design Pattern:** Orchestrator (per-channel)

**Key Responsibilities:**

- **Ask ScheduleService (Schedule Manager) what should be airing 'right now', using MasterClock to compute the correct offset into the current program**
- **Instantiate or reuse a Producer** that implements the Producer Protocol
- **Track viewer count and apply the fanout model** (first viewer starts Producer, last viewer stops it)
- **ChannelManager must never write schedule data, mutate horizons, or pick content assets directly. It only consumes schedule output and enforces lifecycle.**

**Key Behaviors:**

- **Never writes schedule** - Only reads from Schedule Manager
- **Manages Producer lifecycle** - Starts/stops based on viewer demand
- **Coordinates with MasterClock** - Uses authoritative time source
- **Handles channel policies** - Applies channel-specific rules
- **Monitors performance** - Tracks channel health and quality

ChannelManager manages the Producer lifecycle (start/stop/swap) for its channel, based on viewer demand and current operating mode.

**Boundary Rule:**
ChannelManager never writes schedule data and never picks content. It only consumes schedule data from Schedule Manager and controls Producer lifecycle.

### MasterClock

**File:** `src/retrovue/runtime/clock.py`

**Role:** Authority over "now" and system time synchronization.

**Design Pattern:** Authority

**Key Responsibilities:**

- **Provide authoritative time** for the entire system
- **Provide authoritative 'now' as station time; all runtime components must query MasterClock instead of calling system time directly**
- **Synchronize all components** to common time source
- **Handle time zone conversions** for different channels
- **Ensure time consistency** across all operations
- **Manage time-based events** and triggers

**Key Behaviors:**

- **Single source of truth** for system time
- **Synchronized across all components** - All components use MasterClock
- **Timezone aware** - Handles multiple time zones correctly
- **High precision** - Provides accurate timing for seamless playback
- **Event coordination** - Triggers time-based events and transitions

**Authority Rule:**
MasterClock is the only time source for runtime and scheduling. No other component may compute timestamps or offsets using system time. ChannelManager and ScheduleService must both consult MasterClock.

## Invariants

The Program Director maintains several critical invariants:

### Viewer Fanout Model

- **First viewer triggers Producer start**
- **Last viewer triggers Producer stop**
- **ChannelManager enforces this rule for its channel**
- **ProgramDirector does not directly start Producers; it only sets global policy (normal vs emergency) that ChannelManager must enforce**

### Emergency Override

- **ProgramDirector can swap all channels** to EmergencyProducer mode
- **System-wide emergency handling** - All channels can be overridden simultaneously
- **Immediate activation** - Emergency mode activates instantly
- **Recovery procedures** - Clear path back to normal operation
- **Only ProgramDirector may initiate or clear emergency override. ChannelManager must obey the current global mode when selecting which Producer to run.**

### Time Synchronization

- **MasterClock is the only time source** - All components use MasterClock
- **Consistent timing** - All channels synchronized to common time
- **Precise coordination** - Seamless transitions and event timing
- **Timezone handling** - Proper time zone conversion for all channels
- **ScheduleService uses MasterClock to assign absolute_start / absolute_end timestamps in the Playlog. ChannelManager uses MasterClock to align live playback to that timing when a viewer joins mid-program.**

## Boundaries

### ChannelManager Boundary: Read-only Consumer of Schedule

**What ChannelManager DOES:**

- ✅ Reads schedule data from Schedule Manager
- ✅ Coordinates runtime operations based on schedule
- ✅ Manages Producer lifecycle and viewer sessions
- ✅ Applies channel-specific policies and rules

**What ChannelManager DOES NOT:**

- ❌ Generate or modify schedule data
- ❌ Make scheduling decisions
- ❌ Override schedule content or timing
- ❌ Bypass Schedule Manager for content decisions
- ❌ **ChannelManager is not allowed to ask Content Manager or Schedule Manager for 'new content' on demand. If something is missing from the schedule, that's considered a scheduling failure upstream, not permission to improvise.**

### Producer Boundary: No Content Selection

**What Producer DOES:**

- ✅ Generate broadcast streams and output
- ✅ Handle real-time encoding and streaming
- ✅ Play content provided by ChannelManager
- ✅ Support multiple output modes

**What Producer DOES NOT:**

- ❌ Choose what content to play
- ❌ Make content decisions or selections
- ❌ Override content provided by ChannelManager
- ❌ Access Content Manager directly
- ❌ **Producer cannot talk to Content Manager or Schedule Manager directly. All instructions come from ChannelManager via the playout plan.**

### MasterClock Boundary: Single Time Authority

**What MasterClock DOES:**

- ✅ Provide authoritative system time
- ✅ Synchronize all components to common time
- ✅ Handle timezone conversions
- ✅ Coordinate time-based events

**What MasterClock DOES NOT:**

- ❌ Delegate time decisions to other components
- ❌ Allow multiple time sources
- ❌ Handle content or scheduling decisions
- ❌ Manage viewer sessions or channels

### Runtime Boundary: No Ingest Side Effects

**What Runtime Components DO:**

- ✅ Read from Content Manager and Schedule Manager
- ✅ Generate output and manage viewer sessions
- ✅ Coordinate real-time operations
- ✅ Handle emergency overrides and mode changes

**What Runtime Components DO NOT:**

- ❌ Call ingest or discovery operations
- ❌ Modify content library or schedules
- ❌ Access external content sources directly
- ❌ Perform content discovery or metadata extraction

## Future Integrations

### Viewer Management System

The Program Director will provide interfaces for:

- **Viewer session tracking** - Monitor active viewers and sessions
- **Stream URL generation** - Provide URLs for viewer access
- **Quality monitoring** - Track stream quality and performance
- **Analytics integration** - Provide data for viewer analytics

### Emergency Management System

The Program Director will support:

- **Emergency override** - System-wide emergency mode activation
- **Recovery procedures** - Clear path back to normal operation
- **Status monitoring** - Real-time system health and status
- **Alert integration** - Integration with monitoring and alerting systems

### Content Integration

The Program Director will coordinate with:

- **Schedule Manager** - For current programming and schedule data
- **Content Manager** - For asset metadata and playback information
- **External systems** - For emergency content and override materials

## Key Architectural Principles

### Single Responsibility

Each component has one clear purpose:

- **ProgramDirector** - Global coordination and policy
- **ChannelManager** - Per-channel runtime control
- **Producer** - Output generation and streaming
- **MasterClock** - Time authority and synchronization

### Resource Efficiency

- **Viewer fanout model** - Producers only run when needed
- **Graceful scaling** - Smooth startup and shutdown
- **Shared resources** - Efficient use of system resources
- **Load balancing** - Distribute load across available resources

### Time Consistency

- **Single time source** - MasterClock provides all timing
- **Synchronized operations** - All components use same time
- **Precise coordination** - Seamless transitions and events
- **Timezone handling** - Proper conversion for all channels

### Emergency Handling

- **System-wide overrides** - Can override all channels simultaneously
- **Immediate activation** - Emergency mode activates instantly
- **Recovery procedures** - Clear path back to normal operation
- **Status monitoring** - Real-time health and status tracking

## Runtime Package Layout

```
src/retrovue/runtime/
  program_director.py       # ProgramDirector (global orchestrator / policy enforcer)
  channel_manager.py       # ChannelManager (per-channel orchestrator, fanout model, Producer lifecycle)
  clock.py                  # MasterClock (time Authority)
  producer/
    __init__.py             # Clean import surface for Producer Protocol
    base.py                 # Producer Protocol / BaseProducer interface + shared types
    normal_producer.py      # normal programming output
    emergency_producer.py   # emergency override output
    guide_producer.py       # listings / guide channel output
```

This layout is intentional. It isolates runtime orchestration (ProgramDirector, ChannelManager) from actual output generation (Producer implementations), and both of those from time authority (MasterClock).

## Producer Protocol Package Design

The `producer/` package follows a specific architectural pattern that separates concerns and enables clean extensibility:

### Package Structure Principles

**Shared Foundation (`base.py`):**

- Contains the abstract `Producer` interface that all implementations must follow
- Defines shared types: `ProducerMode`, `ProducerStatus`, `ProducerState`, `ContentSegment`
- Establishes the contract that ChannelManager depends on
- Ensures consistent behavior across all producer types

**Implementation Isolation:**

- Each producer type (`normal_producer.py`, `emergency_producer.py`, `guide_producer.py`) is in its own file
- Implementations can evolve independently without affecting others
- New producer types can be added without modifying existing code
- Each file focuses on a single responsibility

**Clean Import Surface (`__init__.py`):**

- Exposes all public interfaces through a single import point
- Enables `from retrovue.runtime.producer import Producer, NormalProducer, ...`
- Hides internal package structure from consumers
- Maintains backward compatibility as the package evolves

### Benefits of This Design

- **Extensibility**: New producer types (e.g., `ffmpeg_producer.py`, `slate_producer.py`) can be added without changing existing code
- **Maintainability**: Each producer implementation is isolated and focused
- **Testability**: Individual producer types can be tested in isolation
- **Clarity**: The package structure makes the Producer Protocol contract explicit
- **Future-Proof**: The design accommodates complex producer implementations without cluttering a single file

This package design reflects the architectural principle that **Producers are swappable capability providers behind a common protocol** - the package structure makes this principle concrete and enforceable.

ChannelManager and ProgramDirector must only depend on the public surface exposed by retrovue.runtime.producer (and by producer/base.py). They are not allowed to import or manipulate internal details of specific producer implementations. ChannelManager can construct/select a Producer and tell it what to play, but it cannot reach into that Producer's internals (for example, it cannot manage ffmpeg subprocesses directly).

## Broadcast Day Behavior

RetroVue uses a broadcast day model that runs from 06:00 → 06:00 local channel time instead of midnight → midnight. Program Director coordinates channels but does NOT redefine broadcast day logic.

### Key Principles

**ProgramDirector coordinates channels, but does NOT redefine broadcast day logic.**

**ProgramDirector can ask ScheduleService for the current broadcast day or what's rolling over, but it does not slice content or reschedule content at day boundaries.**

**Emergency / override logic should respect in-progress longform content (e.g. a movie spanning 05:00–07:00) unless an emergency explicitly overrides normal playout.**

**Goal: ProgramDirector should treat broadcast day mostly as a reporting/scheduling grouping, not as a playout cut point.**

### Rollover Handling

When coordinating channels during broadcast day rollover:

1. **Respect Ongoing Content** - Never interrupt programs that span the 06:00 boundary
2. **Coordinate with ScheduleService** - Ask for broadcast day information and rollover status
3. **Maintain Continuous Operation** - Ensure seamless playback across rollover
4. **Emergency Override Considerations** - Emergency mode should respect ongoing longform content unless explicitly overriding

### Implementation Notes

- ProgramDirector relies on ScheduleService for broadcast day logic
- MasterClock provides consistent time references across rollover
- ChannelManager handles actual playback continuity
- AsRunLogger may split continuous assets across broadcast days for reporting

## Summary

The Program Director is RetroVue's runtime and playback coordination system. It:

- **Coordinates** all channel operations and viewer sessions
- **Coordinates** Producer instances that generate real-time broadcast output
- **Enforces** system-wide policies and emergency procedures
- **Provides** seamless viewer experiences across all channels
- **Ensures** efficient resource usage and graceful scaling
- **Manages** broadcast day coordination without redefining broadcast day logic

It follows RetroVue's architectural patterns and provides the runtime foundation that enables live broadcast operations. The system maintains strict boundaries between scheduling, content management, and runtime operations.

**Program Director does not invent schedules or pick content; it enforces them at runtime.**

**ChannelManager is the per-channel orchestrator.**

**Producers are swappable capability providers behind a common protocol.**

**Remember:** Program Director is about **runtime coordination and playback**—not scheduling, content discovery, or library management. It consumes data from other systems and coordinates real-time broadcast operations.

In broadcast terms: Program Director is master control. It doesn't decide what's on the log — it makes sure the log actually goes to air, on time, synchronized, and recoverable.

ProgramDirector operates on Channel entities using UUID identifiers for external operations and logs.

## Cross-References

| Component                                  | Relationship                                                  |
| ------------------------------------------ | ------------------------------------------------------------- |
| **[ChannelManager](channel_manager.md)**  | Per-channel runtime controller and Producer lifecycle manager |
| **[ScheduleService](schedule_service.md)** | Provides current airing status and broadcast day information  |
| **[MasterClock](../domain/MasterClock.md)**          | Provides authoritative station time for all operations        |
| **[AsRunLogger](asrun_logger.md)**         | Coordinates with emergency response logging                   |

_Document version: v0.1 · Last updated: 2025-10-24_
