# Zones + SchedulableAssets Contracts

_Related: [Domain: Channel](../domain/Channel.md) • [Domain: SchedulePlan](../domain/SchedulePlan.md) • [Domain: ScheduleDay](../domain/ScheduleDay.md) • [Domain: Program](../domain/Program.md) • [Domain: Scheduling](../domain/Scheduling.md)_

## Purpose

This document defines **testable behavioral contracts** for the Zones + SchedulableAssets scheduling model. These contracts ensure that the scheduling engine correctly implements the core policies and behaviors that guarantee EPG accuracy, ad math consistency, and predictable schedule generation.

**Critical Rule:** These contracts are **testable assertions** that must be verified through automated tests. Each contract defines a specific behavior that the scheduling system must guarantee.

## Scope

This contract applies to:

- **Channel** - Defines the Grid configuration (`grid_block_minutes`, `block_start_offsets_minutes`, `programming_day_start`) that all scheduling aligns to
- **SchedulePlan** - Defines Zones (time windows) that hold SchedulableAssets directly
- **Zone** - Named time windows within the programming day that hold SchedulableAssets directly
- **SchedulableAssets** - Programs, Assets, VirtualAssets, and SyntheticAssets placed directly in Zones
- **Program** - Catalog entities (series, movie, block, composite) that are SchedulableAssets with asset_chain and play_mode
- **ScheduleDay** - Resolved, immutable schedules generated from Plans
- **EPG Generation** - Electronic Program Guide derived from ScheduleDay

## Testable Contracts

### C-GRID-01: All Scheduled Starts Align to Channel Grid

**Contract:** All program starts in a generated ScheduleDay MUST align to the Channel's grid boundaries defined by `grid_block_minutes` and `block_start_offsets_minutes`.

**Behavior:**
- When Zones expand their SchedulableAssets across time windows, each SchedulableAsset starts at the next valid grid boundary
- No program starts at arbitrary times (e.g., 19:07) — all starts align to grid boundaries (e.g., 19:00, 19:30)
- Grid boundaries are determined by the Channel's `grid_block_minutes` (e.g., 30 minutes) and `block_start_offsets_minutes` (e.g., :00, :30 within each hour)

**Test Assertions:**
- Given a Channel with `grid_block_minutes=30` and `block_start_offsets_minutes=[0, 30]`, all ScheduleDay entries must start at :00 or :30
- Given a Channel with `grid_block_minutes=15` and `block_start_offsets_minutes=[0, 15, 30, 45]`, all ScheduleDay entries must start at :00, :15, :30, or :45
- No ScheduleDay entry may have a start time that does not align to a valid grid boundary

**Related Documentation:**
- [Channel.md](../domain/Channel.md) - Grid & Boundaries section
- [SchedulingPolicies.md](../domain/SchedulingPolicies.md) - Grid Alignment policy
- [ScheduleDay.md](../domain/ScheduleDay.md) - Resolution Semantics section

**Entities:** Channel, ScheduleDay

---

### C-ZONE-03: SchedulableAssets Fill Zone Window

**Contract:** SchedulableAssets in a Zone MUST be placed across the Zone's active window until the Zone is full, snapping to Channel grid boundaries.

**Behavior:**
- When a Zone's SchedulableAssets are expanded, they are placed sequentially across the Zone's time window
- SchedulableAssets continue to be placed until the Zone's declared end time is reached
- Each placement snaps to the next valid grid boundary
- If SchedulableAssets do not fully fill the Zone, under-filled time becomes avails
- Programs expand their asset chains at playlist generation based on play_mode

**Test Assertions:**
- Given a Zone `00:00-06:00` with SchedulableAssets `["A", "B"]` on a 30-minute grid:
  - SchedulableAsset A starts at 00:00
  - SchedulableAsset B starts at 00:30 (or next grid boundary after A)
  - SchedulableAssets repeat as needed: A at 01:00, B at 01:30, A at 02:00, etc.
  - Placement continues until Zone end (06:00)
- Given a Zone `19:00-22:00` with SchedulableAsset `["Movie Block"]` that fills 1.5 hours:
  - Movie plays 19:00-20:30
  - Next SchedulableAsset starts at 20:30 (or next grid boundary)
  - Zone ends at 22:00 as declared

**Related Documentation:**
- [SchedulePlan.md](../domain/SchedulePlan.md) - Zones and SchedulableAssets section
- [SchedulingPolicies.md](../domain/SchedulingPolicies.md) - Grid Alignment and Fixed Zone End policies
- [ScheduleDay.md](../domain/ScheduleDay.md) - Zone Expansion section

**Entities:** SchedulePlan, Zone, SchedulableAsset, ScheduleDay

---

### C-ZONE-01: Zone Soft-Starts After In-Flight, Snaps to Next Boundary

**Contract:** If a Zone opens while content is already playing, the Zone MUST wait until the current item ends, then start its SchedulableAssets at the next grid boundary.

**Behavior:**
- When a Zone becomes active but content from a previous Zone or carry-in is still playing, the new Zone does not interrupt
- The Zone's SchedulableAssets begin at the next grid boundary after the current content completes
- This prevents mid-content interruptions and ensures smooth transitions

**Test Assertions:**
- Given content playing from 19:00 expected to end at 21:15, and a Zone opening at 20:00:
  - Current content continues until 21:15
  - Zone's SchedulableAssets start at 21:30 (next grid boundary after 21:15)
- Given content playing from 04:00 expected to end at 06:45, and a Zone opening at 06:00:
  - Current content continues until 06:45
  - Zone's SchedulableAssets start at 07:00 (next grid boundary after 06:45)

**Related Documentation:**
- [SchedulePlan.md](../domain/SchedulePlan.md) - Conflict Resolution section
- [SchedulingPolicies.md](../domain/SchedulingPolicies.md) - Soft-Start-After-Current policy
- [ScheduleDay.md](../domain/ScheduleDay.md) - Soft-Start and Carry-In section

**Entities:** Zone, ScheduleDay

---

### C-ZONE-02: Zone Ends at Declared Time (No Auto-Extend)

**Contract:** Zones MUST end at their declared end time, even if the SchedulableAssets have not fully filled the Zone. Under-filled time becomes avails.

**Behavior:**
- If SchedulableAssets do not fully fill a Zone, the Zone ends at its declared end time
- Under-filled blocks become avails (available time slots for ads, promos, or filler content)
- The scheduler does not extend the Zone or repeat SchedulableAssets beyond the declared end time

**Test Assertions:**
- Given a Zone `20:00-22:00` (2 hours) with SchedulableAsset `["Movie Block"]` that fills 1.5 hours:
  - Movie plays 20:00-21:30
  - Zone ends at 22:00 as declared
  - 21:30-22:00 becomes avails (not filled by SchedulableAssets)
- Given a Zone `06:00-12:00` (6 hours) with SchedulableAssets `["A", "B"]` where each fills 1 hour:
  - SchedulableAssets placed: A at 06:00, B at 07:00, A at 08:00, B at 09:00, A at 10:00, B at 11:00
  - Zone ends at 12:00 as declared (no extension to fill remaining time)

**Related Documentation:**
- [SchedulePlan.md](../domain/SchedulePlan.md) - Zone section
- [SchedulingPolicies.md](../domain/SchedulingPolicies.md) - Fixed Zone End policy
- [ScheduleDay.md](../domain/ScheduleDay.md) - Block Consumption and Avails section

**Entities:** Zone, ScheduleDay

---

### C-LF-01: Longform Never Cut; Consumes Multiple Blocks if Needed

**Contract:** Longform content (movies, specials, extended episodes) MUST never be cut mid-play, even if it extends beyond the intended block or zone. The scheduler MUST consume additional grid blocks to accommodate the full content.

**Behavior:**
- If a Program resolves to content that is longer than its allocated block(s), the content continues playing
- The scheduler consumes additional grid blocks to accommodate the full content
- This applies to movies, specials, and any content where `slot_units` or series pick results in overlength
- Content is only cut if explicitly allowed by the Program's configuration (not the default)

**Test Assertions:**
- Given a Program `["Movie Block"]` with `slot_units=4` (2 hours on 30-min grid) that resolves to a 2.5-hour movie:
  - Movie plays for 2.5 hours (5 grid blocks instead of 4)
  - Movie is never cut mid-play
- Given a Program `["Special"]` that resolves to a 3-hour special on a 30-minute grid:
  - Special consumes 6 grid blocks
  - Special plays to completion without interruption

**Related Documentation:**
- [Program.md](../domain/Program.md) - Resolution section, slot_units
- [SchedulingPolicies.md](../domain/SchedulingPolicies.md) - No Mid-Longform Cuts policy
- [ScheduleDay.md](../domain/ScheduleDay.md) - Block Consumption and Avails section

**Entities:** Program, ScheduleDay

---

### C-BD-01: Carry-In Across Programming-Day Seam Supported

**Contract:** If content is playing when the programming day boundary (`programming_day_start`) is reached, Day+1 MUST start with a carry-in until the content completes, then snap to the next grid boundary.

**Behavior:**
- The programming day is defined by the Channel's `programming_day_start` (e.g., 06:00)
- If content is still playing when the day boundary is reached, the next day's schedule starts with a carry-in
- Day+1's first Zone begins at the next grid boundary after the carry-in completes
- This ensures seamless transitions across day boundaries without content interruption

**Test Assertions:**
- Given `programming_day_start=06:00`, content playing from 04:00 expected to end at 06:45:
  - Content continues until 06:45 (carry-in into Day+1)
  - Day+1's first Zone starts at 07:00 (next grid boundary after carry-in)
- Given `programming_day_start=06:00`, content playing from 05:30 expected to end at 06:20:
  - Content continues until 06:20 (carry-in into Day+1)
  - Day+1's first Zone starts at 06:30 (next grid boundary after carry-in, if 06:30 is a valid grid boundary)

**Related Documentation:**
- [Channel.md](../domain/Channel.md) - Grid & Boundaries section, programming_day_start
- [SchedulingPolicies.md](../domain/SchedulingPolicies.md) - Carry-In Across Programming-Day Seam policy
- [ScheduleDay.md](../domain/ScheduleDay.md) - Soft-Start and Carry-In section

**Entities:** Channel, ScheduleDay

---

### C-EPG-01: EPG Reflects Actual Expected Start Times from Compiled ScheduleDay

**Contract:** The Electronic Program Guide (EPG) MUST reflect the actual expected start times from the compiled ScheduleDay, not the Zone declarations or SchedulableAsset definitions.

**Behavior:**
- EPG generation reads from ScheduleDay records, which contain the resolved, grid-aligned start times
- EPG shows the actual start times after all policies have been applied (grid alignment, soft-start, carry-in)
- EPG does not show Zone start times or SchedulableAsset definitions — only the resolved ScheduleDay entries

**Test Assertions:**
- Given a Zone `20:00-22:00` with SchedulableAsset `["Drama"]`, but content from previous Zone carries until 20:15:
  - ScheduleDay shows Drama starting at 20:30 (next grid boundary after 20:15)
  - EPG shows Drama starting at 20:30 (not 20:00)
- Given a Zone `06:00-12:00` with SchedulableAsset `["Cartoons"]`, but carry-in from previous day ends at 06:45:
  - ScheduleDay shows Cartoons starting at 07:00 (next grid boundary after 06:45)
  - EPG shows Cartoons starting at 07:00 (not 06:00)

**Related Documentation:**
- [ScheduleDay.md](../domain/ScheduleDay.md) - Immutability and EPG Truthfulness section
- [EPGGeneration.md](../domain/EPGGeneration.md) - EPG generation from ScheduleDay
- [SchedulingPolicies.md](../domain/SchedulingPolicies.md) - All policies affect EPG accuracy

**Entities:** ScheduleDay, EPGGeneration

---

## Contract Interaction

These contracts work together to ensure deterministic, predictable schedule generation:

1. **C-GRID-01** provides the foundation for all timing decisions
2. **C-ZONE-03** ensures SchedulableAssets fill Zones correctly
3. **C-ZONE-01** handles zone transitions gracefully
4. **C-ZONE-02** ensures zones respect their declared boundaries
5. **C-LF-01** preserves content integrity
6. **C-BD-01** ensures seamless day transitions
7. **C-EPG-01** guarantees EPG accuracy

**Critical Rule:** These contracts are applied in order during ScheduleDay resolution. The scheduler evaluates Zones, expands SchedulableAssets, resolves Programs, and applies these contracts to generate the final immutable ScheduleDay.

## Test Coverage Requirements

Each contract (C-GRID-01 through C-EPG-01) MUST have corresponding test coverage that:

1. **Validates the contract holds** in normal operation
2. **Verifies edge cases** and boundary conditions
3. **Confirms policy application** matches documented behavior
4. **Tests contract interaction** when multiple contracts apply simultaneously

## Related Contracts

- [SchedulePlanInvariantsContract](resources/SchedulePlanInvariantsContract.md) - Cross-entity invariants for SchedulePlan
- [ScheduleDayContract](resources/ScheduleDayContract.md) - ScheduleDay generation and validation contracts
- [UnitOfWorkContract](_ops/UnitOfWorkContract.md) - Transaction boundaries for schedule operations

## See Also

- [Domain: Channel](../domain/Channel.md) - Channel Grid configuration
- [Domain: SchedulePlan](../domain/SchedulePlan.md) - Zones and SchedulableAssets model
- [Domain: ScheduleDay](../domain/ScheduleDay.md) - Resolved schedules
- [Domain: Program](../domain/Program.md) - Catalog entities (SchedulableAssets)
- [Domain: Scheduling Policies](../domain/SchedulingPolicies.md) - Detailed policy descriptions
- [Domain: EPGGeneration](../domain/EPGGeneration.md) - EPG generation from ScheduleDay

---

**Note:** These contracts ensure that RetroVue generates predictable, EPG-accurate schedules that operators can rely on for content planning, ad revenue calculations, and viewer expectations. All contracts prioritize content integrity, EPG truthfulness, and deterministic behavior.

