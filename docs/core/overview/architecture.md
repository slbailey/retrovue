# RetroVue System Architecture

_Related: [Architecture overview](../architecture/ArchitectureOverview.md) • [Data flow](../architecture/DataFlow.md) • [Runtime: Channel manager](../runtime/ChannelManager.md)_

> **The single source of truth for understanding RetroVue's architecture**  
> What we're building, why we built it this way, and how the components fit together.

---

## Vision

RetroVue simulates a **24/7 television network** — complete with multiple channels, scheduled shows, commercials, bumpers, promos, and emergency crawls — **without actually running 24/7 encoders**.

### Core Concept

Each channel maintains a **virtual linear timeline** in the database that always advances with wall-clock time. Even when nobody is watching, the system "knows" what's airing right now. When a viewer tunes in, RetroVue spins up a real playout pipeline at the correct point in the schedule — and when the last viewer leaves, the pipeline shuts down.

> **The illusion of a continuous broadcast is preserved without burning compute.**

### Design Philosophy

- **Scheduling is intentional and rule-driven**, just like a real broadcast station
- RetroVue isn't a playlist or shuffle engine — it's a **simulation of television as a medium**: predictable, rhythmic, and time-based
- **The goal is authenticity, not convenience**
- You don't pick what to watch — you tune in to whatever's on, mid-show if necessary
- **That feeling of shared linear time is the product**

### What RetroVue Is Not

| System         | Purpose                                                      | RetroVue's Difference                                                                                        |
| -------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------ |
| **Plex**       | VOD (video-on-demand) system — browse and play what you want | Linear, not on-demand. Generates channels that follow fixed schedules with ads, bumpers, and promos          |
| **VOD Server** | Responds to user requests for files                          | Curates time — channels appear to run continuously on their own schedules, whether anyone is watching or not |

---

## High-Level Architecture

RetroVue is composed of several layers working together to maintain, schedule, and deliver believable "live" channels.

### Library Domain (Content Ingest Layer)

**Purpose:** Gather metadata about available content (shows, movies, promos, commercials) and prepare it for broadcast scheduling.

#### Core Concepts

**Source**  
An origin of media content (e.g., Plex server, local filesystem, ad library). Sources are discovered and enumerated to find available content.

**Collection**  
A logical grouping of related content from a source (e.g., "The Simpsons", "Classic Movies", "Commercials"). Collections organize content into broadcast-relevant categories.

**Asset**  
The leaf unit RetroVue can eventually broadcast. Each asset belongs to exactly one collection and has a lifecycle state indicating its readiness for scheduling.

#### Ingest Flow

1. **Content Discovery**: Content is discovered from a source
2. **Organization**: Content is organized into a collection
3. **Storage**: Content is stored as an asset
4. **Enrichment**: Assets progress through a state machine: `new` → `enriching` → `ready` → `retired`

#### Asset Lifecycle States

| State       | Description                             | Broadcast Eligibility |
| ----------- | --------------------------------------- | --------------------- |
| `new`       | Recently discovered, minimal metadata   | ❌ Not eligible       |
| `enriching` | Being processed by enrichers            | ❌ Not eligible       |
| `ready`     | Fully processed, approved for broadcast | ✅ Eligible           |
| `retired`   | No longer available or approved         | ❌ Not eligible       |

> **Critical Rule:** Scheduling and playout only operate on assets in state `ready`.

**How it works:**

- **Adapters** connect to external libraries (e.g., Plex, local folders, ad libraries)
- **Enrichers** process asset metadata to extract what broadcast scheduling needs: runtime, ratings, ad break markers, tags, and restrictions
- **State Machine** ensures only fully-processed, approved content reaches the scheduling layer

**Contract:** Library Domain is authoritative for content availability and metadata quality, but runtime never queries Library Domain directly. It's batch, not real-time.

> **Important:** Library Domain operations can be slow. Playback cannot depend on it.

See also:

- [Data flow](../architecture/DataFlow.md)
- [Domain: Ingest pipeline](../domain/IngestPipeline.md)
- [Domain: Source](../domain/Source.md)
- [Domain: Asset](../domain/Asset.md)

### Broadcast Domain (Scheduling Layer)

Builds and maintains the scheduling pipeline: **SchedulableAsset → ScheduleDay → Playlist → Producer(ffmpeg) → AsRun**.

#### Pipeline Stages

| Stage           | Purpose                                                                      | Horizon                      |
| --------------- | ---------------------------------------------------------------------------- | ---------------------------- |
| **ScheduleDay** | Planned daypart lineup for EPG. Holds SchedulableAssets (not files) in Zones | 3–4 days ahead (EPG horizon) |
| **Playlist**    | Resolved pre–AsRun list of physical assets with absolute timecodes           | Rolling few hours ahead      |
| **Playlog**     | Runtime execution plan aligned to MasterClock                                | Rolling few hours ahead      |
| **AsRun**       | Observed ground truth — what actually aired                                  | Real-time                    |

#### Timing Model

Every scheduled item has an `absolute_start` and `absolute_end` timestamp in wall-clock time. That's how we can determine, at 09:05, that a sitcom which began at 09:00 should start 5 minutes in. Because every Playlog Event carries `absolute_start` and `absolute_end`, ChannelManager can start playback mid-show at the correct offset instead of always starting from the top of the file.

**Broadcast-Day Display:** Human-readable times in plan show and ScheduleDay views reflect channel broadcast-day start (e.g., 06:00 → 05:59 next day). JSON outputs include canonical times plus `broadcast_day_start` for UI offset calculation.

#### Block Alignment Rule

- **EPG blocks** always align to 30-minute boundaries, even if episode runtimes don't
- **Playlist/Playlog** fills the leftover time with ad pods, bumpers, and promos to end exactly on the boundary

> **Key Insight:** This pipeline model lets RetroVue act like a real network without needing to prebuild byte-accurate schedules for days in advance.

See also:

- [Scheduling system architecture](../architecture/SchedulingSystem.md)
- [Runtime: ScheduleService](../runtime/schedule_service.md)

### Runtime / Channel Orchestration Layer

> **This is where channels come to life.**

#### Key Components

- **ProgramManager (ProgramDirector)** — supervises all channels
- **ChannelManager** — runs one specific channel

#### Responsibilities

- **ProgramManager** coordinates high-level system behavior — startup, shutdown, emergency mode — and monitors channel health
- **ChannelManager** owns the runtime lifecycle of its channel, handling viewer sessions and Producers

#### Viewer Flow

```mermaid
graph TD
    A[Viewer tunes in] --> B[ChannelManager asks ScheduleService<br/>"what should be airing right now + offset?"]
    B --> C[ChannelManager builds playout plan<br/>starting at correct position within current show]
    C --> D[ChannelManager spins up Producer<br/>to emit the stream]
    D --> E[Subsequent viewers attach<br/>to that same Producer]
    E --> F{Viewer count = 0?}
    F -->|Yes| G[ChannelManager tears down Producer]
    F -->|No| E
```

#### Fanout Invariant

- **Exactly one Producer** may be active per channel
- **Many viewers** can watch it simultaneously
- **When none remain**, the Producer stops

#### Responsibility Boundary

> **ProgramManager never assembles playout plans** — it delegates per-channel logic to ChannelManagers.

### Playout / Producer Layer

**Producers** are output-oriented runtime components that drive playout. Examples: AssetProducer, SyntheticProducer, future LiveProducer.

#### Types of Producers

| Type                  | Purpose                                             |
| --------------------- | --------------------------------------------------- |
| **AssetProducer**     | Standard episodes, ads, bumpers (physical assets)   |
| **SyntheticProducer** | Generated content (test patterns, countdown clocks) |
| **LiveProducer**      | Live feeds (future)                                 |

#### Key Principles

- **Producers are output-oriented** — they drive playout execution
- **ffmpeg is not a Producer** — it's the playout/encoding engine that Producers feed
- **Producers are modular** — ChannelManager decides which Producer to use and what plan to give it
- **Producers don't pick content** — they render the playout plan they're given

#### Requirements

- ✅ **Must start mid-show** at any offset, matching current wall-clock time
- ✅ **Must follow the Playlog plan exactly** — order, duration, transitions
- ✅ **Must be composable** with overlays
- ✅ **Must terminate cleanly** when instructed
- ✅ **Must feed ffmpeg** with appropriate inputs for playout/encoding

### System Time / MasterClock

> **A single MasterClock defines "station time" for the entire system.**

#### Rules

- **All scheduling, offset math, and playout alignment** reference this clock
- **No other component** may call `datetime.now()` or keep its own clock
- **MasterClock is also what future As-Run logging will use** to prove what actually aired
- **This ensures** logs, playback, and schedule alignment all agree

> **MasterClock is law.**  
> **Everyone asks it what "now" means.**

---

## Core Components

### ContentManager

#### **WHAT**

Handles ingestion of media metadata from external sources. Stores only broadcast-relevant info — runtime, rating, ad breaks, tags.

#### **WHY**

Scheduling depends on accurate runtime and ad break data to create believable commercial pods. We don't need full media management.

#### **HOW**

- Uses **adapters and enrichers** to populate the content catalog
- Marks items with scheduling eligibility (safe-for-daytime, genre tags, etc.)

> **In practice:** ContentManager provides the universe of eligible content that ScheduleManager can draw from.

### ScheduleManager (ScheduleService)

#### **WHAT**

Maintains the scheduling pipeline: ScheduleDay (EPG horizon), Playlist, and Playlog for each channel.

#### **WHY**

Viewers need a guide; the playout engine needs exact timing. The pipeline lets us plan days in broad strokes (ScheduleDay with SchedulableAssets) without resolving every frame ahead of time, then expand to physical assets (Playlist) and align to MasterClock (Playlog) for execution.

#### **HOW**

- **Generates ScheduleDays** from SchedulePlans (Zones holding SchedulableAssets directly) — 3–4 days ahead (EPG horizon)
- **Generates Playlists** by expanding SchedulableAssets to physical Assets — rolling few hours ahead
- **Generates Playlogs** by aligning Playlist entries to MasterClock — rolling few hours ahead
- **Persists pipeline stages** with `absolute_start` / `absolute_end` timestamps
- **Rolls EPG daily** (~3–4 days out) and **Playlist/Playlog continuously** (~few hours ahead)

#### Invariants

- **EPG Horizon** ≥ 2 days ahead at all times
- **Playlog Horizon** ≥ 2 hours ahead at all times
- **ChannelManager assumes** these horizons exist and never builds schedules itself

### ProgramManager (ProgramDirector)

#### **WHAT**

Global supervisor and policy layer. Oversees all channels.

#### **WHY**

We need a single authority that can coordinate state across channels — e.g., triggering emergency takeover or reporting overall health.

#### **HOW**

- **Holds all ChannelManager instances**
- **Can toggle emergency mode** (swap all channels to EmergencyProducer)
- **Monitors channel health** and orchestrates lifecycle events
- **Provides a single control point for system-wide state** (for example, "all channels go to emergency crawl now.")

> **ProgramManager does not pick content or assemble plans** — it orchestrates systems and state.

### ChannelManager

#### **WHAT**

Per-channel runtime controller. Tracks viewer count and manages Producer lifecycle.

#### **WHY**

We only spin up resources when needed. It's also how viewers "drop in" mid-show without seeing startup artifacts.

#### **HOW**

- **On tune-in:** query ScheduleManager → get current item + offset → build playout plan → start Producer
- **On tune-out:** decrement viewer_count; if it hits 0, tear down Producer
- **Swaps Producers** if mode changes (e.g., emergency override)

#### Invariants

- **At most one Producer** active per channel
- **Producers start mid-show** if required
- **Viewer count reaching zero** triggers teardown

> **Operationally, ChannelManager is the channel at runtime.**

### Producer

#### **WHAT**

Output-oriented runtime component that drives playout for a channel. Examples: AssetProducer, SyntheticProducer, future LiveProducer.

#### **WHY**

Separates "what to play" (scheduling) from "how to render/encode." Producers are output drivers; ffmpeg is the playout/encoding engine that Producers feed.

#### **HOW**

- **Reads playlog:** resolved physical assets with absolute timecodes
- **Feeds ffmpeg** with appropriate inputs to produce continuous MPEG-TS output
- **Supports mid-program start**, overlays, and clean stop
- **Other viewers attach** to this output stream (fanout model)

> **Only one Producer per channel.** Others may view its stream, but not spawn new ones.  
> **ffmpeg is not a Producer** — it's the playout/encoding engine that Producers feed.

See also:

- [Runtime: ProgramDirector](../runtime/program_director.md)
- [Runtime: ChannelManager](../runtime/channel_manager.md)

### Overlay / Branding Layer

#### **WHAT**

Visual layer for logos, lower-thirds, crawls, and rating bugs.

#### **WHY**

Adds authenticity, identity, and compliance features without modifying core video assets.

#### **HOW**

ChannelManager applies overlays to the playout plan before starting a Producer. Overlays are composable and independent of Producers.

> **Overlay exists to decorate output without changing how Producers function.**

### MasterClock

#### **WHAT**

Centralized station time authority.

#### **WHY**

Keeps scheduling, playout, and logging in perfect sync and makes time-based debugging possible.

#### **HOW**

- **Provides current station time** to ScheduleManager, ProgramManager, ChannelManager, and logging
- **All modules use this** — none call system time directly

> **If the scheduler says "play at 3:15 PM," everyone agrees what "3:15 PM" means.**

---

## Design Paradigms / Patterns

### Modular Components with Narrow Responsibilities

Each component solves one tier of the problem:

| Component           | Responsibility      |
| ------------------- | ------------------- |
| **ContentManager**  | metadata ingestion  |
| **ScheduleManager** | future planning     |
| **ProgramManager**  | global coordination |
| **ChannelManager**  | per-channel runtime |
| **Producer**        | output              |

> **This modularity keeps the system testable, composable, and safe to extend.**

### Adapters and Enrichers

- **Adapters** connect to diverse data sources (Plex, filesystem, ad libraries)
- **Enrichers** convert raw metadata into the broadcast concepts (runtime, ad breaks, rating, "safe for daypart")

> **This separation lets us evolve or replace sources without touching core scheduling.**

### Producers as Swap-In Output Drivers

- **Runtime never hardcodes** streaming logic
- **ChannelManager simply asks** a Producer to execute a plan
- **This allows alternate Producers** (guide channel, emergency feed) without changing orchestration logic

### Horizon-Based Scheduling

Planning happens in two scopes:

| Horizon             | Type                    | Scope       |
| ------------------- | ----------------------- | ----------- |
| **EPG Horizon**     | human-facing, coarse    | days ahead  |
| **Playlog Horizon** | machine-facing, precise | hours ahead |

> **This allows real-network authenticity without excessive precomputation.**

### On-Demand Channel Activation

- **Channels are virtual** until watched
- **The first viewer starts** the Producer, additional viewers attach to the same output, and the last viewer stops it
- **That's how RetroVue looks like** a 24/7 cable network while using minimal resources

> **This is the core economic insight: full network experience, fractional infrastructure cost.**

---

## Glossary

| Term                         | Definition                                                                                                                                   |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| **Channel**                  | A virtual broadcast stream with its own schedule and identity                                                                                |
| **SchedulableAsset**         | Abstract base for all schedule entries. Concrete types: Program, Asset, VirtualAsset, SyntheticAsset                                         |
| **Program**                  | SchedulableAsset type with asset_chain (linked list of SchedulableAssets) and play_mode (random, sequential, manual)                         |
| **VirtualAsset**             | SchedulableAsset type that represents input-driven composite. Expands to physical Assets at playlist generation                              |
| **Zone**                     | Named time window within the programming day that holds SchedulableAssets                                                                    |
| **ScheduleDay**              | Planned daypart lineup for EPG. Holds SchedulableAssets (not files) in Zones. Generated 3–4 days ahead (EPG horizon)                         |
| **Playlist**                 | Resolved pre–AsRun list of physical assets with absolute timecodes. Generated from ScheduleDay                                               |
| **Playlog**                  | Runtime execution plan aligned to MasterClock. Derived from Playlist                                                                         |
| **AsRun**                    | Observed ground truth — what actually aired. Records what was observed during playout execution                                              |
| **EPG Horizon**              | Coarse, grid-aligned programming schedule, 3–4 days ahead. Rolled forward daily (ScheduleDay)                                                |
| **Playlist/Playlog Horizon** | Fine-grained, fully resolved playout plan, few hours ahead. Continuously extended                                                            |
| **Viewer Fanout**            | Model where the first viewer triggers Producer startup, additional viewers share the same output, and last viewer shutdowns it               |
| **ProgramManager**           | Oversees all channels; handles global policies and emergencies                                                                               |
| **ChannelManager**           | Controls runtime state of one channel; handles viewer count and Producer lifecycle                                                           |
| **Producer**                 | Output-oriented runtime component (AssetProducer, SyntheticProducer, future LiveProducer). ffmpeg is the playout engine that Producers feed. |
| **Overlay**                  | Visual branding or crawl applied over the video feed                                                                                         |
| **MasterClock**              | Single authoritative notion of "now." All timing derives from it; direct system time calls are prohibited                                    |
| **Broadcast Day**            | 24-hour period starting at channel's broadcast_day_start (e.g., 06:00). Human-readable times reflect broadcast-day offset                    |
| **Ad Pod**                   | Cluster of commercials played together during a break                                                                                        |
| **Bumper**                   | Short station ID or transition clip between programs                                                                                         |

---

_This document serves as the architectural foundation for RetroVue's development and maintenance._

## See also

- [Architecture overview](../architecture/ArchitectureOverview.md) - Detailed architecture documentation
- [Data flow](../architecture/DataFlow.md) - End-to-end data movement
- [Repo review and roadmap](RepoReviewAndRoadmap.md) - Contract-first audit notes and prioritization
- [Runtime: Channel manager](../runtime/ChannelManager.md) - Channel runtime operations
- [Runtime: Program director](../runtime/program_director.md) - System-wide coordination
- [Domain: Playout pipeline](../domain/PlayoutPipeline.md) - Stream generation process
