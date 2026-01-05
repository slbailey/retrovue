# Comprehensive Documentation Verification Report

## Unified SchedulableAsset Architecture

**Generated:** 2025-11-07  
**Purpose:** Verify documentation consistency after refactoring to unified SchedulableAsset architecture

---

## 1️⃣ Architecture Summary (Current State)

### Core Conceptual Model

The unified scheduling architecture centers on **`SchedulableAsset`** as the root abstraction for anything that can appear on a schedule. The system follows a clear separation of concerns across planning, runtime, and logged layers.

#### Key Entities

**SchedulableAsset** (Root Abstraction)

- Concrete types: `Program`, `Asset`, `VirtualAsset`, `SyntheticAsset`
- Anything that can be placed in a Zone within a SchedulePlan
- Defines content and sequencing, not timing or duration

**Program**

- SchedulableAsset type that is a **linked list** of SchedulableAssets
- Contains `asset_chain` (JSON array of linked list nodes) and `play_mode` (random, sequential, manual)
- Defines **ordering and sequencing**, not duration
- Duration is controlled by Zone placement, not intrinsic to Programs
- Expands at playlist generation to physical assets based on `play_mode`

**VirtualAsset**

- SchedulableAsset type that acts as an input-driven composite
- Template/composite wrapper referencing other assets, not a file itself
- Behaves like regular assets during scheduling
- Expands to physical assets at **playlist generation**, not ScheduleDay time
- Enables modular programming blocks (e.g., branded intro → episode → outro)

**Zone**

- Named time window within the programming day (e.g., "Morning Cartoons," "Prime Time")
- Contains one or more **SchedulableAssets directly** (not through Patterns)
- Controls timing and **duration** — duration is zone-controlled, not asset-controlled
- Uses broadcast day time (00:00–24:00 relative to `programming_day_start`)
- Can span midnight (e.g., 22:00–05:00) within the same broadcast day

**SchedulePlan**

- Top-level operator-created plans defining channel programming
- Contains Zones (time windows) that hold SchedulableAssets directly
- Timeless and reusable — same plan generates different ScheduleDays for different dates
- Supports layering with priority resolution (higher priority plans override lower priority)

**ScheduleDay**

- Resolved, immutable daily schedule for a specific channel and date
- Generated from SchedulePlan 3–4 days in advance (EPG horizon)
- Contains SchedulableAssets placed in Zones with wall-clock times
- **SchedulableAssets remain intact** — expansion to physical assets occurs at playlist generation
- Immutable once generated (frozen) unless force-regenerated

**Playlist**

- Resolved pre–AsRun list of physical assets with absolute timecodes
- Generated from ScheduleDay by expanding SchedulableAssets to physical Assets
- Programs expand their asset chains based on `play_mode`
- VirtualAssets expand into one or more physical Assets
- Provides timeline input for runtime Playlog
- Generated using rolling horizon (few hours ahead)

**PlaylogEvent**

- Runtime execution plan aligned to MasterClock
- Derived from Playlist entries (may diverge for substitutions/timing corrections)
- Contains resolved physical assets with precise timestamps
- Transient and rolling — continuously extended ~3–4 hours ahead of real time
- Drives actual playout execution

**AsRun Log**

- Observed ground truth — what actually aired
- Records what was observed during playout execution
- Includes actual start times from MasterClock
- Used for historical accuracy, audits, and reporting

### Time Flow: Planning → Schedule → Playlist → Playout → As-Run

```
SchedulePlan (Zones + SchedulableAssets)
    ↓ [3–4 days in advance - EPG horizon]
ScheduleDay (SchedulableAssets placed in Zones with wall-clock times)
    ↓ [Rolling horizon - few hours ahead]
Playlist (Expanded to physical assets with absolute timecodes)
    ↓ [Rolling horizon - few hours ahead, aligned to MasterClock]
PlaylogEvent (Runtime execution plan)
    ↓ [Real-time execution]
AsRun Log (Observed ground truth)
```

**Key Timing Principles:**

- **EPG Horizon**: ScheduleDays generated 3–4 days in advance for viewer EPG
- **Playlist/Playlog Horizon**: Rolling few hours ahead for actual playout
- **Broadcast Day Start**: 06:00 convention (configurable per channel)
- **MasterClock Alignment**: PlaylogEvents aligned to centralized time authority for synchronized playout

### Relationships and Responsibilities

**Who Owns What:**

- **Channel**: Owns Grid configuration (`grid_block_minutes`, `block_start_offsets_minutes`, `programming_day_start`)
- **SchedulePlan**: Owns Zones and SchedulableAsset placements
- **Zone**: Owns timing windows and duration control
- **Program**: Owns asset chain ordering and sequencing (not duration)
- **ScheduleDay**: Owns resolved daily schedule (immutable once generated)
- **Playlist**: Owns expanded physical assets with timecodes
- **PlaylogEvent**: Owns runtime execution plan
- **AsRun Log**: Owns observed playback records

**What's Derived From What:**

- **ScheduleDay** ← derived from SchedulePlan (Zones + SchedulableAssets)
- **Playlist** ← derived from ScheduleDay (expands SchedulableAssets to physical assets)
- **PlaylogEvent** ← derived from Playlist (aligned to MasterClock)
- **AsRun Log** ← derived from actual playback observation

### Separation: Data Models, Runtime Services, and Daemons

**Data Models (Domain Layer):**

- `SchedulePlan`, `Zone`, `Program`, `VirtualAsset`, `Asset`, `ScheduleDay`, `PlaylogEvent`, `AsRunLog`
- Persistent entities stored in database
- Define the structure and relationships of scheduling data

**Runtime Services:**

- **ScheduleService**: Generates ScheduleDays from SchedulePlans, extends plan horizon 3–4 days ahead
- **PlaylistGenerator**: Generates Playlist from ScheduleDay, expands SchedulableAssets to physical assets
- **PlaylogGenerator**: Generates PlaylogEvents from Playlist, aligns to MasterClock
- **AsRunLogger**: Records actual playback observations

**Daemons:**

- **ScheduleService daemon**: Continuously monitors active plans and extends horizon
- **PlaylistGenerator daemon**: Continuously generates Playlist entries for rolling horizon
- **PlaylogGenerator daemon**: Continuously generates PlaylogEvents aligned to MasterClock
- **ChannelManager**: Per-channel runtime controller, executes playout, manages Producer lifecycle
- **ProgramDirector**: Global system coordinator, manages ChannelManagers, handles emergency overrides

**Producer (Playout Layer):**

- Output-oriented rendering engine (e.g., ffmpeg)
- Operates at playout time, not tied to Program definitions
- Receives playout plan from ChannelManager
- Generates broadcast streams for assigned channel
- **Not** a scheduling-time entity — Producers are runtime components

---

## 2️⃣ Legacy vs New Model Comparison

### What Changed

**Terminology Changes:**

- **"Pattern" → "Program"**: The old "Pattern" concept (ordered list of Programs with no duration) has been replaced by "Program" (linked list of SchedulableAssets with `play_mode`)
- **"PatternZone" → "Zone"**: Zones now hold SchedulableAssets directly, not Patterns
- **"VirtualProducer" → Removed**: No such concept exists — VirtualAssets expand to physical Assets which then feed standard Producers

**Architectural Changes:**

- **Duration Ownership**: Duration is now explicitly **zone-controlled**, not intrinsic to Programs or SchedulableAssets
- **Direct Placement**: Zones now hold SchedulableAssets **directly**, eliminating the intermediate Pattern layer
- **Linked List Model**: Programs now use a linked list structure (`asset_chain`) instead of separate intro/outro fields
- **Playlist Layer**: New intermediate layer between ScheduleDay and PlaylogEvent for asset expansion
- **Expansion Timing**: Programs and VirtualAssets expand at **playlist generation**, not at ScheduleDay resolution

**Conceptual Consolidations:**

- **Pattern + Program → Program**: The old Pattern (container) and Program (content) distinction is unified into a single Program entity with linked list structure
- **PatternZone + Zone → Zone**: Zones are simplified to directly contain SchedulableAssets
- **VirtualProducer → Producer**: Producers are unified as output-oriented runtime components, not tied to VirtualAssets

### What Was Renamed

| Legacy Term               | New Term                           | Notes                                                             |
| ------------------------- | ---------------------------------- | ----------------------------------------------------------------- |
| Pattern                   | Program                            | Programs are now linked lists of SchedulableAssets with play_mode |
| PatternZone               | Zone                               | Zones directly hold SchedulableAssets                             |
| VirtualProducer           | (removed)                          | Producers are runtime components, not tied to VirtualAssets       |
| Pattern reference in Zone | SchedulableAsset placement in Zone | Zones hold SchedulableAssets directly                             |

### What Concepts Were Removed

- **Pattern as separate entity**: Eliminated — Programs now serve this role
- **PatternZone as intermediate layer**: Eliminated — Zones directly contain SchedulableAssets
- **VirtualProducer**: Eliminated — VirtualAssets expand to physical Assets which feed standard Producers
- **Duration in Programs**: Removed — Duration is zone-controlled, not program-controlled
- **Intro/outro fields in Programs**: Removed — Replaced by linked list nodes in `asset_chain`

### What Concepts Were Consolidated

- **Pattern + Program → Program**: Unified into single Program entity with linked list
- **PatternZone + Zone → Zone**: Simplified Zone model with direct SchedulableAsset placement
- **VirtualAsset expansion timing**: Consolidated to playlist generation (not ScheduleDay or Playlog time)

---

## 3️⃣ Remaining Inconsistencies / Cleanup Notes

### Critical Issues Found (✅ FIXED)

1. **`docs/runtime/schedule_service.md` (Line 6)** ✅ FIXED

   - **Issue**: Missing Playlist in chain: "SchedulePlan → ScheduleDay → PlaylogEvent → AsRunLog"
   - **Fixed**: Updated to "SchedulePlan → ScheduleDay → Playlist → PlaylogEvent → AsRunLog"
   - **Severity**: High — incorrect architecture description

2. **`docs/domain/Zone.md` (Line 9)** ✅ FIXED

   - **Issue**: Still says "Program or VirtualAsset blocks" instead of "SchedulableAssets"
   - **Fixed**: Updated to "contain one or more SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets)"
   - **Severity**: Medium — terminology inconsistency

3. **`docs/domain/VirtualAsset.md` (Line 82)** ✅ FIXED

   - **Issue**: Says "Expansion happens at ScheduleDay time (preferred) or Playlog time (fallback)"
   - **Fixed**: Updated to "Expansion happens at playlist generation, not at ScheduleDay time"
   - **Severity**: High — incorrect expansion timing

4. **`docs/domain/Zone.md` (Line 5)** ✅ FIXED
   - **Issue**: Chain description missing Playlist: "SchedulePlan (Zones + SchedulableAssets) → ScheduleDay (resolved) → PlaylogEvent (runtime) → AsRunLog"
   - **Fixed**: Updated to "SchedulePlan (Zones + SchedulableAssets) → ScheduleDay (resolved) → Playlist → PlaylogEvent (runtime) → AsRunLog"
   - **Severity**: High — incorrect architecture description

### Contract Files (Legacy References)

**Enforced Legacy Contracts Removed:**

- ✅ `docs/contracts/resources/SchedulingInvariants.md` - REMOVED (was enforced legacy contract)
- ✅ `docs/contracts/resources/SchedulePlanContract.md` - REMOVED (was enforced legacy contract)

**Legacy Contracts with Deprecation Notices:**
The following contract files in `docs/contracts/` still reference the old Pattern model but are marked with deprecation notices:

- `docs/contracts/resources/ZoneContract.md` (references Pattern extensively, has deprecation notice)
- `docs/contracts/resources/ZoneAddContract.md` (references Pattern, has deprecation notice)
- `docs/contracts/resources/ZoneUpdateContract.md` (references Pattern, has deprecation notice)
- `docs/contracts/resources/ZoneShowContract.md` (references Pattern, has deprecation notice)
- `docs/contracts/resources/ZoneListContract.md` (references Pattern, has deprecation notice)
- `docs/contracts/resources/ZoneDeleteContract.md` (references Pattern, has deprecation notice)

**Note**: These contract files are intentionally preserved with deprecation notices for backward compatibility reference. They are not marked as "Enforced" and serve as historical documentation.

### Legitimate "Pattern" References

The following are legitimate uses of the word "pattern" (not the old Pattern entity):

- "Test Pattern" (SyntheticAsset name) — proper noun, not an entity
- "design pattern" (general software term)
- "pattern of programming" (general English usage)
- "registration pattern" (CLI pattern)
- "holding pattern" (fallback behavior)

### Ambiguous Areas

1. **ScheduleDay Resolution Terminology**

   - Some docs say "ScheduleDay resolution" when referring to ScheduleDay generation from SchedulePlan
   - Clarify: "ScheduleDay generation" or "ScheduleDay resolution" — both are used, but "generation" may be clearer

2. **Playlist vs Playlog Naming**

   - Playlist: Resolved pre–AsRun list of physical assets
   - Playlog: Runtime execution plan (PlaylogEvent)
   - Some docs use "Playlog" to refer to both — clarify distinction

3. **Producer Integration**
   - Producers are clearly positioned as runtime components
   - Some docs mention "Producer type" or "Producer instance" — ensure consistent terminology

---

## 4️⃣ Completeness Assessment

### Major Lifecycle Stages Coverage

✅ **EPG (Electronic Program Guide)**

- Covered in `docs/architecture/SchedulingSystem.md`
- ScheduleDay provides EPG data (3–4 days ahead)
- Human-readable times reflect broadcast-day start (06:00)
- JSON outputs include `broadcast_day_start` for UI offset calculation

✅ **Playlist**

- Covered in `docs/architecture/Playlist.md`
- Generated from ScheduleDay by expanding SchedulableAssets
- Contains resolved physical assets with absolute timecodes
- Programs expand asset chains, VirtualAssets expand to physical Assets

✅ **Playlog**

- Covered in `docs/domain/PlaylogEvent.md`
- Runtime execution plan aligned to MasterClock
- Derived from Playlist (may diverge for substitutions)
- Transient and rolling (~3–4 hours ahead)

✅ **AsRun**

- Covered in `docs/domain/PlaylogEvent.md` (AsRun section)
- Observed ground truth — what actually aired
- Records actual playback observations
- Used for historical accuracy and audits

### Runtime Processes Mapping

✅ **ScheduleService (scheduler_daemon)**

- Covered in `docs/runtime/schedule_service.md`
- Generates ScheduleDays from SchedulePlans (3–4 days ahead)
- Extends plan horizon continuously
- Maps cleanly to SchedulePlan → ScheduleDay flow

✅ **ChannelManager**

- Covered in `docs/runtime/ChannelManager.md`
- Per-channel runtime controller
- Executes playout, manages Producer lifecycle
- Reads PlaylogEvents for playout instructions
- Maps cleanly to PlaylogEvent → Playout flow

✅ **Producer**

- Covered in `docs/runtime/ProducerLifecycle.md` and `docs/domain/PlayoutPipeline.md`
- Output-oriented rendering engine (e.g., ffmpeg)
- Operates at playout time, not scheduling time
- Receives playout plan from ChannelManager
- Maps cleanly to PlaylogEvent → Producer → Stream flow

✅ **ProgramDirector**

- Covered in `docs/runtime/program_director.md`
- Global system coordinator
- Manages ChannelManagers
- Handles emergency overrides
- Maps cleanly to system-wide coordination

### Virtual Timeline + On-Demand Playout System

✅ **Virtual Timeline**

- Covered in `docs/overview/architecture.md`
- Each channel maintains a virtual linear timeline in the database
- Timeline always advances with wall-clock time
- System "knows" what's airing right now even when nobody is watching

✅ **On-Demand Playout**

- Covered in `docs/runtime/ChannelManager.md`
- When viewer tunes in, ChannelManager spins up Producer at correct point
- When last viewer leaves, Producer shuts down
- Illusion of continuous broadcast without burning compute

✅ **MasterClock Alignment**

- Covered in `docs/domain/MasterClock.md`
- Centralized time authority for synchronized playout
- PlaylogEvents aligned to MasterClock
- Enables mid-show joins at correct offset

### Documentation Gaps

⚠️ **Minor Gaps:**

- Some contract files in `docs/contracts/` still reference old Pattern model (may be intentional for backward compatibility)
- Some terminology inconsistencies (e.g., "ScheduleDay resolution" vs "ScheduleDay generation")
- Some docs use "Playlog" to refer to both Playlist and PlaylogEvent — clarify distinction

✅ **Overall Assessment:**
The documentation is **comprehensive and consistent** with the new unified SchedulableAsset architecture. All major lifecycle stages are covered, runtime processes map cleanly to the models, and the virtual timeline + on-demand playout system is well-documented. The remaining issues are minor inconsistencies that can be addressed with targeted fixes.

---

## 5️⃣ Before/After Mapping Table

| Legacy Concept                            | New Concept                                                           | Mapping Notes                                                                                                                                            |
| ----------------------------------------- | --------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Pattern**                               | **Program**                                                           | Programs are now linked lists of SchedulableAssets with `play_mode` (random, sequential, manual). Programs define ordering and sequencing, not duration. |
| **PatternZone**                           | **Zone**                                                              | Zones now hold SchedulableAssets directly (Programs, Assets, VirtualAssets, SyntheticAssets). Duration is zone-controlled.                               |
| **Pattern reference in Zone**             | **SchedulableAsset placement in Zone**                                | Zones directly contain SchedulableAssets, eliminating the Pattern intermediate layer.                                                                    |
| **VirtualProducer**                       | **Producer** (runtime component)                                      | VirtualProducers don't exist. VirtualAssets expand to physical Assets which then feed standard Producers (runtime components).                           |
| **Duration in Program**                   | **Duration in Zone**                                                  | Duration is now zone-controlled, not program-controlled. Programs define ordering and sequencing only.                                                   |
| **Intro/outro fields in Program**         | **Linked list nodes in `asset_chain`**                                | Intro/outro bumpers are now nodes in the Program's `asset_chain` linked list, not separate fields.                                                       |
| **Pattern expansion at ScheduleDay**      | **Program expansion at Playlist generation**                          | Programs expand their asset chains at playlist generation, not at ScheduleDay resolution.                                                                |
| **VirtualAsset expansion at ScheduleDay** | **VirtualAsset expansion at Playlist generation**                     | VirtualAssets expand to physical Assets at playlist generation, not at ScheduleDay time.                                                                 |
| **ScheduleDay → PlaylogEvent**            | **ScheduleDay → Playlist → PlaylogEvent**                             | New Playlist layer between ScheduleDay and PlaylogEvent for asset expansion.                                                                             |
| **Pattern repetition to fill Zone**       | **Zone controls duration, SchedulableAssets play within Zone window** | Zones control timing and duration. SchedulableAssets play within the Zone's time window.                                                                 |
| **Pattern as container**                  | **Program as linked list**                                            | Programs are now linked lists of SchedulableAssets with `play_mode`, not containers.                                                                     |
| **PatternProducer**                       | **Producer** (runtime component)                                      | Producers are unified as output-oriented runtime components, not tied to Patterns or Programs.                                                           |

### Key Architectural Shifts

1. **Elimination of Pattern Layer**: Patterns are eliminated — Programs now serve this role with linked list structure
2. **Direct SchedulableAsset Placement**: Zones directly contain SchedulableAssets, not Patterns
3. **Duration Ownership**: Duration is explicitly zone-controlled, not asset-controlled
4. **Playlist Layer**: New intermediate layer for asset expansion between ScheduleDay and PlaylogEvent
5. **Expansion Timing**: Programs and VirtualAssets expand at playlist generation, not ScheduleDay resolution
6. **Producer Unification**: Producers are unified as runtime components, not tied to scheduling-time entities

---

## Summary

The documentation has been successfully updated to reflect the unified SchedulableAsset architecture. The core conceptual model is consistent, terminology is unified, and the flow from planning → schedule → playlist → playout → as-run is clearly documented.

**Remaining work:**

1. ✅ **FIXED**: 4 critical inconsistencies identified in Section 3 have been resolved
2. Review contract files in `docs/contracts/` for Pattern references (may need separate effort)
3. Clarify terminology (e.g., "ScheduleDay resolution" vs "ScheduleDay generation") — minor improvement

**Overall status:** ✅ **Documentation is comprehensive and consistent**. All critical issues have been resolved.
