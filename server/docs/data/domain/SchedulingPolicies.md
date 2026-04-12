# Scheduling Policies

_Related: [Scheduling overview](Scheduling.md) • [Zones + SchedulableAssets contracts](../contracts/ZonesPatterns.md)_

## Purpose

Define the **operator-visible outcomes** and **testable guarantees** for RetroVue scheduling.

These are intentionally stated as **what must be true**, not how it is implemented.

## Policy catalog (outcomes)

### Grid alignment

- **Guarantee**: All scheduled starts align to the Channel grid (`grid_block_minutes` + `block_start_offsets_minutes`).
- **Why it matters**: EPG and downstream playout assume predictable boundaries.
- **Contract**: `docs/contracts/ZonesPatterns.md` (C-GRID-01).

### Zone fill semantics

- **Guarantee**: Zone content fills sequentially through the zone window, snapping to grid boundaries; underfill becomes avails.
- **Contract**: `docs/contracts/ZonesPatterns.md` (C-ZONE-03, C-ZONE-02).

### Soft-start after in-flight content

- **Guarantee**: If a zone opens while content is already playing, scheduling does **not** cut; the zone starts after the current item ends, at the next grid boundary.
- **Contract**: `docs/contracts/ZonesPatterns.md` (C-ZONE-01).

### Fixed zone end (no auto-extend)

- **Guarantee**: Zones end at their declared end time; they do not auto-extend to fit longform.
- **Contract**: `docs/contracts/ZonesPatterns.md` (C-ZONE-02).

### Carry-in across programming-day seam

- **Guarantee**: Content may carry across the programming-day boundary without interruption; the next day’s first zone respects carry-in and starts after completion.
- **Contract**: `docs/contracts/ZonesPatterns.md` (C-DAY-01 / seam-related contracts).

## Notes

- This document is the **policy index**. The authoritative, testable rules live in the contracts.

_Related: [Channel](Channel.md) • [SchedulePlan](SchedulePlan.md) • [ScheduleDay](ScheduleDay.md) • [Scheduling](Scheduling.md)_

# Domain — Scheduling Policies

## Purpose

This document describes the **default scheduling policies** used by SchedulingService. These policies govern how Zones and their SchedulableAssets are resolved into concrete [ScheduleDay](ScheduleDay.md) schedules, ensuring consistent behavior, predictable EPG output, and reliable ad math calculations.

**Critical Rule:** These are the **default policies** applied by SchedulingService. They ensure deterministic, predictable schedule generation that operators can rely on for EPG accuracy and ad revenue calculations.

## Core Policies

### 1. Grid Alignment (Snap All Starts to Channel Grid)

**Policy:** All program starts snap to the [Channel](Channel.md) grid boundaries defined by `grid_block_minutes` and `block_start_offsets_minutes`.

**Behavior:**
- When SchedulableAssets are placed in a Zone, each starts at the next valid grid boundary
- Grid boundaries are determined by the Channel's `grid_block_minutes` (e.g., 30 minutes) and `block_start_offsets_minutes` (e.g., :00, :30 within each hour)
- SchedulableAssets never start at arbitrary times (e.g., 19:07) — they always align to grid boundaries (e.g., 19:00, 19:30)

**User-Facing Outcomes:**
- **EPG Truth:** EPG systems can reliably predict start times because all content aligns to known grid boundaries
- **Ad Math Consistency:** Ad breaks occur at predictable intervals, enabling accurate revenue calculations and ad inventory management
- **Predictable Scheduling:** Operators can plan content knowing exactly when content will start

**Example:**
- Channel grid: 30-minute blocks starting at :00 and :30
- Zone: 19:00–21:00 with SchedulableAssets: [Program A, Program B]
- Result: Program A starts at 19:00, Program B starts at 19:30 (or 20:00 if Program A fills a full block)

**See Also:** [Channel.md](Channel.md) - Grid & Boundaries section

---

### 2. Soft-Start-After-Current (Zone Opens During In-Flight Content)

**Policy:** If a Zone opens while content is already playing (e.g., a Zone starts at 20:00 but a movie is still playing from 19:00), the Zone waits until the current item ends, then snaps to the next grid boundary.

**Behavior:**
- When a Zone becomes active but content from a previous Zone or carry-in is still playing, the new Zone does not interrupt
- The Zone's SchedulableAssets begin at the next grid boundary after the current content completes
- This prevents mid-content interruptions and ensures smooth transitions

**User-Facing Outcomes:**
- **EPG Truth:** EPG accurately reflects when new content actually starts, not when the Zone technically opens
- **No Content Interruption:** Viewers never see content cut off mid-scene when zones change
- **Predictable Transitions:** Operators can rely on smooth transitions between zones without manual intervention

**Example:**
- Current content: Movie playing from 19:00, expected to end at 21:15
- Zone opens: "Prime Time" zone starts at 20:00 with SchedulableAssets: [Drama Program]
- Result: Movie continues until 21:15, then Drama Program starts at 21:30 (next grid boundary)

**See Also:** [SchedulePlan.md](SchedulePlan.md) - Conflict Resolution section

---

### 3. Fixed Zone End (Do Not Extend to Make Up)

**Policy:** Zones end at their declared end time, even if the SchedulableAssets have not fully filled the Zone. Under-filled time becomes avails.

**Behavior:**
- If SchedulableAssets do not fully fill a Zone (e.g., Zone is 19:00–21:00 but content only fills 1.5 hours), the Zone ends at 21:00 as declared
- Under-filled blocks become avails (available grid blocks for ads, promos, or filler content)
- The scheduler does not extend the Zone beyond the declared end time

**User-Facing Outcomes:**
- **EPG Truth:** EPG accurately reflects Zone boundaries, and operators know exactly when zones end
- **Ad Inventory:** Under-filled zones create predictable avails that can be sold or filled with promos
- **Predictable Scheduling:** Operators can rely on Zone end times matching their declarations

**Example:**
- Zone: "Prime Time" 20:00–22:00 (2 hours)
- SchedulableAssets: [Movie Program] (Program with `slot_units=3` on 30-min grid = 1.5 hours)
- Result: Movie plays 20:00–21:30, then 21:30–22:00 becomes avails

**See Also:** [ScheduleDay.md](ScheduleDay.md) - Resolution Semantics section

---

### 4. Cuts Only at Authorized Breakpoints

**Policy:** Playout may transition from program content to interstitial or ad content only at authorized breakpoints within the program. Mid-segment cuts at arbitrary positions are invalid. Programs with no breakpoints play to completion without interruption.

**Behavior:**
- Programs may declare breakpoints (cue points, act breaks, SCTE markers, or explicit chapter markers) that define valid transition positions
- Traffic may insert interstitial events only at declared breakpoints during Schedule Day resolution
- Programs with no breakpoints play to completion — they are never cut mid-segment
- If a program (with or without breakpoints) extends beyond its allocated block(s), the scheduler consumes additional grid blocks to accommodate the full content
- This applies to all program types: movies, specials, series episodes, and any content where `slot_units` or series pick results in overlength

**User-Facing Outcomes:**
- **Content Integrity:** Viewers see complete content without arbitrary cuts. Breaks occur only at natural transition points (act breaks, chapter markers)
- **EPG Truth:** EPG reflects actual content duration, including any interstitials inserted at breakpoints
- **Predictable Behavior:** Operators know that programs will only be interrupted at declared breakpoints, and programs without breakpoints will always play to completion

**Example (no breakpoints):**
- Zone contains Movie Program with `slot_units=4` (2 hours on 30-min grid)
- Movie resolves to 2.5 hours at playlist generation, has no declared breakpoints
- Result: Movie plays for 2.5 hours uninterrupted, consuming 5 grid blocks instead of 4

**Example (with breakpoints):**
- Zone contains a 90-minute episode with a breakpoint declared at 45:00
- Traffic inserts a 2-minute interstitial event at the 45:00 breakpoint
- Result: 45 minutes of program, 2-minute break, 45 minutes of program — no cuts at any other position

**See Also:** [Program.md](Program.md) - Resolution section, [ScheduleDay.md](ScheduleDay.md) - Block Consumption and Avails section, [ScheduleTrafficArchitecture.md](../scheduling/ScheduleTrafficArchitecture.md) - INV-BRK-01

---

### 5. Carry-In Across Programming-Day Seam

**Policy:** If content is playing when the programming day boundary (`programming_day_start`) is reached, Day+1 starts with a carry-in until the content completes, then snaps to the next grid boundary.

**Behavior:**
- The programming day is defined by the Channel's `programming_day_start` (e.g., 06:00)
- If content is still playing when the day boundary is reached (e.g., movie playing from 04:00 to 06:30), the next day's schedule starts with a carry-in
- Day+1's first Zone begins at the next grid boundary after the carry-in completes
- This ensures seamless transitions across day boundaries without content interruption

**User-Facing Outcomes:**
- **EPG Truth:** EPG accurately reflects carry-in content at the start of each day
- **No Content Interruption:** Viewers never see content cut off at midnight or day boundaries
- **Predictable Day Boundaries:** Operators can rely on consistent day boundary handling

**Example:**
- Programming day start: 06:00
- Day 1: Movie playing from 04:00, expected to end at 06:45
- Day 2: "Morning Zone" starts at 06:00 with SchedulableAssets: [Cartoon Program]
- Result: Movie continues until 06:45, then Cartoon Program starts at 07:00 (next grid boundary after carry-in)

The same carry-in rule applies across broadcast day boundaries (e.g., a film beginning before 6 AM continues uninterrupted).

**See Also:** [Channel.md](Channel.md) - Grid & Boundaries section, [ScheduleDay.md](ScheduleDay.md) - Soft-Start and Carry-In section

---

## Policy Interaction

These policies work together to ensure deterministic, predictable schedule generation:

1. **Grid Alignment** provides the foundation for all timing decisions
2. **Soft-Start-After-Current** handles zone transitions gracefully
3. **Fixed Zone End** ensures zones respect their declared boundaries
4. **Cuts Only at Authorized Breakpoints** preserves content integrity
5. **Carry-In Across Day Seam** ensures seamless day transitions

**Critical Rule:** These policies are applied in order during ScheduleDay resolution. The scheduler evaluates Zones, places SchedulableAssets, and applies these policies to generate the final immutable ScheduleDay. Programs expand their asset chains and VirtualAssets expand to physical Assets during playlist generation, not during ScheduleDay resolution.

## Implementation Notes

**Default Behavior:**
- These policies are the **default** behavior of SchedulingService
- They cannot be disabled or overridden in the current implementation
- All ScheduleDay records are generated using these policies

**Policy Layering:**

Policies are applied in a hierarchical layering system:

- **Global policies** live under `/etc/retrovue/policies/*.yaml` - These are system-wide defaults that apply to all channels and plans
- **Channel-level policies** override global policies - Channel-specific policy configurations stored in the Channel entity override global defaults for that channel
- **Plan-level policies** are attached to a specific SchedulePlan object - Plan-specific policy configurations stored in the SchedulePlan entity override both global and channel-level policies for that plan

**Policy Resolution Order:**
1. Global policies (`/etc/retrovue/policies/*.yaml`) are loaded first
2. Channel-level policies override global policies
3. Plan-level policies override both global and channel-level policies

**Future Considerations:**
- Future versions may allow per-Channel or per-Plan policy overrides
- Policy configuration would be stored in Channel or SchedulePlan entities
- Default policies would remain as fallback behavior

## Related Documentation

- **[Channel.md](Channel.md)** - Defines the Grid configuration that policies align to
- **[SchedulePlan.md](SchedulePlan.md)** - Defines Zones and SchedulableAssets that policies operate on
- **[ScheduleDay.md](ScheduleDay.md)** - The resolved schedule output that policies generate
- **[Scheduling.md](Scheduling.md)** - High-level scheduling system overview
- **[Program.md](Program.md)** - Catalog entities that policies resolve into concrete content

---

**Note:** These scheduling policies ensure that RetroVue generates predictable, EPG-accurate schedules that operators can rely on for content planning, ad revenue calculations, and viewer expectations. All policies prioritize content integrity, EPG truthfulness, and deterministic behavior.

