_Related: [Architecture](../architecture/ArchitectureOverview.md) • [SchedulePlan](SchedulePlan.md) • [ScheduleDay](ScheduleDay.md) • [Program](Program.md) • [Channel](Channel.md) • [Operator CLI](../cli/README.md)_

# Domain — Zone

> **Note:** This document reflects the modern scheduling architecture. Active chain: **SchedulePlan (Zones + SchedulableAssets) → ScheduleDay (resolved) → Playlist → PlaylogEvent (runtime) → AsRunLog.**

## Purpose

Zone is a **scheduling abstraction** — a named time window within the programming day that organizes the broadcast schedule into logical areas. Zones divide the broadcast day into meaningful segments (e.g., "Morning Cartoons," "Prime Time," "Overnight") and contain one or more SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets) that define what content plays during those windows.

**Zones are NOT a runtime construct.** They are a scheduling abstraction that helps humans and the scheduler:
- Reason about dayparts
- Express constraints
- Choose appropriate content

**What a Zone is:**

- A **scheduling abstraction** used during planning and schedule compilation
- A **logical organizer** that divides the broadcast day into named time segments
- A **time window** declaring when content should play (e.g., `06:00–12:00`, `19:00–22:00`, `22:00–05:00`)
- A **container** for SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets) that play during the Zone's window
- A **planning construct** used by ScheduleDay for readability and organization

**What a Zone is not:**

- **NOT a runtime execution entity** — Zones exist only during planning and resolution
- **NOT executed by the playout system** — only the resolved content in ScheduleDay is executed
- **NOT seen by ChannelManager** — Zones are never sent to runtime components
- **NOT sent to Air** — Zones are never sent to the playout engine
- **NOT visible in the final playout stream** — Zones are organizational aids for operators

**Compilation Flow:**

Once a schedule is compiled:
```
Zone → SchedulePlan → ScheduleItems → PlaylogSegments
```

From that point on, Zones disappear. They have no runtime presence.

Zones are components of [SchedulePlan](SchedulePlan.md). When a SchedulePlan is compiled into a [ScheduleDay](ScheduleDay.md), the Zones and their SchedulableAssets are placed with wall-clock times. At this point, Zones disappear — they are never seen by ChannelManager, never sent to Air, and have no runtime presence.

## Core Model / Scope

Zone enables:

- **Day organization**: Zones divide the broadcast day into logical areas that make planning intuitive (e.g., "Morning Cartoons," "Prime Time," "Late Night")
- **Time window declaration**: Zones define when content should play within the programming day
- **SchedulableAsset placement**: Zones contain one or more SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets) that play during the Zone's window
- **Readability and planning**: Zones make ScheduleDay easier to understand and maintain by grouping related content
- **Day-of-week filtering**: Optional day filters restrict when Zones are active (e.g., weekday-only, weekend-only)
- **Broadcast day alignment**: Zones use broadcast day time (00:00–24:00 relative to `programming_day_start`), not calendar day time

**Key Points:**

- Zones are **scheduling abstractions** — they help organize schedules but are NOT runtime entities
- Zones are **never executed** — they exist only during planning and compilation
- Zones are **never seen by ChannelManager** — they are not sent to runtime components
- Zones are **never sent to Air** — they are not sent to the playout engine
- Zones divide the day into **logical areas** for operator clarity (e.g., "Morning Cartoons," "Prime Time")
- Each Zone contains **one or more Program or VirtualAsset blocks** that define content
- Zones are used by ScheduleDay for **readability and planning** but disappear after compilation
- **Compilation flow:** Zone → SchedulePlan → ScheduleItems → PlaylogSegments (Zones disappear after this)
- Zones use broadcast day time (00:00–24:00 relative to `programming_day_start`), not calendar day time
- Zones can span midnight (e.g., `22:00–05:00`) within the same broadcast day
- Test pattern or idle zones exist internally for system use but don't need to appear in human-facing EPGs

## Example: Three-Zone Schedule

Here's an example showing how Zones organize a broadcast day:

**Zone 1: Morning Cartoons**

- **Start time**: `06:00:00` (broadcast day time)
- **End time**: `12:00:00` (broadcast day time)
- **SchedulableAssets**:
  - Program: "Tom & Jerry" (series)
  - Program: "Looney Tunes" (series)
  - VirtualAsset: "Kids Interstitial Block"

**Zone 2: Prime Time**

- **Start time**: `19:00:00` (broadcast day time)
- **End time**: `22:00:00` (broadcast day time)
- **SchedulableAssets**:
  - Program: "Cheers" (series)
  - Program: "The Big Bang Theory" (series)
  - Program: "Movie Block" (composite)

**Zone 3: Overnight**

- **Start time**: `22:00:00` (broadcast day time)
- **End time**: `05:00:00` (broadcast day time, spans midnight)
- **SchedulableAssets**:
  - Program: "Classic Movies" (series)
  - SyntheticAsset: "Test Pattern" (idle/filler content)

**Notes:**

- The "Test Pattern" in Zone 3 is a system placeholder that may not appear in human-facing EPGs
- All times are in broadcast day time (relative to `programming_day_start`)
- Zone 3 spans midnight, covering from 22:00 on one calendar day to 05:00 the next
- When this plan is compiled into a ScheduleDay, the Zones organize the content, but only the resolved SchedulableAssets with wall-clock times are stored. Zones disappear after compilation — they are never seen by ChannelManager, never sent to Air.

## Persistence Model

Zone is managed by SQLAlchemy with the following fields:

- **id** (UUID, primary key): Unique identifier for relational joins and foreign key references
- **plan_id** (UUID, required, foreign key): Reference to parent [SchedulePlan](SchedulePlan.md)
- **name** (Text, required): Human-readable identifier (e.g., "Morning Cartoons", "Prime Time", "Overnight", "Base")
- **start_time** (Time, required): Start time of the Zone's active window in broadcast day time (e.g., `00:00:00`, `19:00:00`, `22:00:00`)
- **end_time** (Time, required): End time of the Zone's active window in broadcast day time (e.g., `24:00:00`, `22:00:00`, `05:00:00`)
- **schedulable_assets** (JSON, required): Array of SchedulableAsset IDs (Programs, Assets, VirtualAssets, SyntheticAssets) placed in this Zone
- **day_filters** (JSON, optional): Day-of-week constraints that restrict when the Zone is active (e.g., `["MON", "TUE", "WED", "THU", "FRI"]` for weekdays, `["SAT", "SUN"]` for weekends). If null, Zone is active on all days.
- **enabled** (Boolean, required, default: true): Whether the Zone is active and eligible for schedule generation. Disabled Zones are ignored during resolution.
- **effective_start** (Date, optional): Start date for Zone validity (inclusive). If null, Zone is valid from plan creation.
- **effective_end** (Date, optional): End date for Zone validity (inclusive). If null, Zone is valid indefinitely.
- **dst_policy** (Text, optional): DST transition handling policy - one of: "reject", "shrink_one_block", "expand_one_block". If null, defaults to system-wide DST policy. On DST transition dates, Zone duration is validated per this policy.
- **created_at** (DateTime(timezone=True), required): Record creation timestamp
- **updated_at** (DateTime(timezone=True), required): Record last modification timestamp

**Note:** Zones use broadcast day time (00:00–24:00 relative to `programming_day_start`), not calendar day time. A Zone like `22:00–05:00` spans from 22:00 on one calendar day to 05:00 the next calendar day, but both times are within the same broadcast day (e.g., 06:00 to 06:00 next day).

**24:00 Storage Semantics:** Postgres TIME type cannot store 24:00:00. Zones with `end_time=24:00:00` are stored as `23:59:59.999999` in the database, with a flag or normalization logic indicating end-of-day. The domain layer normalizes this for clarity, but documentation uses 24:00:00 for conceptual accuracy.

### Table Name

The table is named `zones` (plural). Schema migration is handled through Alembic. Postgres is the authoritative backing store.

### Constraints

- `name` must be non-empty and unique within the SchedulePlan
- `start_time` and `end_time` must be valid times in broadcast day format (00:00:00 to 24:00:00)
- `start_time` must be less than `end_time` (unless spanning midnight, in which case end_time < start_time is allowed, e.g., `22:00–05:00`)
- `plan_id` must reference a valid SchedulePlan
- `schedulable_assets` must be a valid JSON array of SchedulableAsset IDs (non-empty)
- All SchedulableAsset IDs in `schedulable_assets` must reference valid SchedulableAssets (Programs, Assets, VirtualAssets, or SyntheticAssets)
- `day_filters` must be a valid JSON array of day abbreviations if provided (e.g., `["MON", "TUE", "WED", "THU", "FRI"]`)
- `enabled` defaults to true; disabled Zones are ignored during resolution
- `dst_policy` must be one of: "reject", "shrink_one_block", "expand_one_block" if provided
- `effective_start` and `effective_end` must form a valid date range (effective_start <= effective_end) if both are provided
- **Grid divisibility invariant**: Zone duration in minutes must be divisible by the Channel's `grid_block_minutes`. Validation occurs at Zone creation/update time (domain-level validation), not only during ScheduleDay resolution. If not divisible, the system rejects the configuration unless a policy allows rounding to nearest boundary.
- **Zone time windows alignment**: Zone start and end times must align with the Channel's Grid boundaries (`block_start_offsets_minutes`). Validation occurs at Zone creation/update time (domain-level validation).

### Relationships

Zone has relationships with:

- **SchedulePlan** (many-to-one): Multiple Zones belong to a single SchedulePlan
- **SchedulableAssets** (many-to-many): Zones contain SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets)
- **ScheduleDay** (one-to-many via resolution): Zones and their SchedulableAssets are placed in ScheduleDay during generation

## Contract / Interface

Zone is a named time window within the programming day that organizes the broadcast schedule. It defines:

- **Plan membership** (plan_id) - the SchedulePlan this Zone belongs to
- **Time window** (start_time, end_time) - when the Zone applies (broadcast day time, 00:00–24:00)
- **SchedulableAssets** (schedulable_assets) - SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets) placed in this Zone
- **Day-of-week filtering** (day_filters) - optional constraints that restrict when the Zone is active
- **Name** (name) - human-readable identifier for operator reference

Zones declare **when** content should play and **which SchedulableAssets** are placed in the Zone. Zones are used by ScheduleDay for readability and planning but are NOT runtime entities. When a SchedulePlan is compiled into a ScheduleDay, Zones organize the content, but only the resolved SchedulableAssets with wall-clock times are stored. Zones disappear after compilation — they are never seen by ChannelManager, never sent to Air.

**Zone Alignment:**

- Zones align to **broadcast days**, not calendar days
- The broadcast day is defined by the Channel's `programming_day_start` (e.g., 06:00)
- Zones use broadcast day time (00:00–24:00 relative to `programming_day_start`)
- A Zone like `22:00–05:00` spans from 22:00 on one calendar day to 05:00 the next calendar day, but both times are within the same broadcast day

**Test Pattern and Idle Zones:**

- Test pattern or idle zones (containing SyntheticAssets like "Test Pattern") exist internally for system use
- These zones ensure full 24-hour coverage when no other content is scheduled
- Test pattern zones don't need to appear in human-facing EPGs — they are system placeholders
- Human-readable views can omit test pattern zones, while JSON outputs may include them for system operations

## Compilation Model (NOT Execution)

Zones are consumed during schedule compilation (NOT runtime execution):

1. **Plan Resolution**: ScheduleService identifies active SchedulePlans for a channel and date
2. **Zone Identification**: For each active plan, identify its Zones (time windows) that apply to the date (considering `enabled`, `effective_start`/`effective_end`, `day_filters`, and time window)
3. **Layering Resolution**: When multiple plans match, priority resolves overlapping Zones. Higher-priority plans' Zones override lower-priority plans' Zones for overlapping time windows
4. **SchedulableAsset Resolution**: For each Zone, retrieve its SchedulableAssets and resolve them to concrete content selections
5. **Time Calculation**: Zone time windows are combined with the Channel's Grid boundaries to produce real-world wall-clock times
6. **ScheduleDay Generation**: Resolved Zones and their SchedulableAssets are used to create [ScheduleDay](ScheduleDay.md) records (resolved 3-4 days in advance)

**Compilation Flow:**
```
Zone → SchedulePlan → ScheduleItems → PlaylogSegments
```

After compilation, Zones disappear. They are never seen by ChannelManager, never sent to Air, and have no runtime presence.

**Time Resolution:** Zone time windows are combined with the Channel's Grid boundaries to produce real-world wall-clock times. Zones declare when they apply (e.g., base 00:00–24:00, or Overnight 22:00–05:00), and the plan engine places SchedulableAssets in Zones, snapping to Grid boundaries.

**Conflict Resolution:** When multiple Zones from different plans overlap, priority resolution determines which Zone applies. Higher-priority plans' Zones override lower-priority plans' Zones for overlapping time windows. When a Zone opens while content is already playing, the soft-start-after-current policy ensures clean transitions without mid-program interruptions.

## Relationship to ScheduleDay

Zones flow into [ScheduleDay](ScheduleDay.md) via compilation during schedule generation:

1. **Zone Identification**: Zones from active SchedulePlans are identified for the channel and date
2. **Priority Resolution**: When multiple plans match, priority resolves overlapping Zones
3. **SchedulableAsset Resolution**: SchedulableAssets in Zones are resolved to concrete content selections
4. **Time Calculation**: Zone time windows are combined with Grid boundaries to produce real-world wall-clock times
5. **ScheduleDay Creation**: Resolved SchedulableAssets with wall-clock times become the resolved asset selections in ScheduleDay

**Compilation Flow:**
```
Zone → SchedulePlan → ScheduleItems → PlaylogSegments
```

**Key Point:** Zones are **scheduling abstractions** that organize the schedule for readability and planning. Once a ScheduleDay is generated, Zones have served their purpose and disappear. The ScheduleDay contains only the resolved SchedulableAssets with wall-clock times — Zones themselves are not stored in ScheduleDay, are never seen by ChannelManager, are never sent to Air, and have no runtime presence.

**Example Flow:**

- Zone: 19:00–22:00 (Prime Time) — **scheduling abstraction only**
- SchedulableAssets: [Cheers (series Program), Movie Block (composite Program)]
- Compilation at ScheduleDay time: System resolves Programs to specific episodes/assets and places them with wall-clock times
- ScheduleDay: Contains resolved asset UUIDs with wall-clock times (e.g., 2025-12-25 19:00:00 UTC for Cheers episode S11E05)
- **Zones disappear** — they are not in ScheduleDay, not seen by ChannelManager, not sent to Air

ScheduleDays are resolved 3-4 days in advance for EPG and playout purposes, based on the Zones and SchedulableAssets in the active SchedulePlan. After compilation, Zones have no further role.

## Day-of-Week Filtering

Zones support optional day-of-week filters that restrict when the Zone is active. This enables recurring patterns like "weekday mornings" or "weekend afternoons."

**Day Filter Format:**

- `day_filters` is a JSON array of day abbreviations (e.g., `["MON", "TUE", "WED", "THU", "FRI"]`)
- If `day_filters` is null, the Zone is active on all days
- Day abbreviations: `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, `SUN`

**Examples:**

- Weekday Zone: `day_filters: ["MON", "TUE", "WED", "THU", "FRI"]` - Active Monday through Friday
- Weekend Zone: `day_filters: ["SAT", "SUN"]` - Active Saturday and Sunday
- All Days Zone: `day_filters: null` - Active every day

**Zone Activation Evaluation:**
During ScheduleDay resolution, Zones are evaluated for activation in this order:

1. **Enabled check**: If `enabled=false`, Zone is skipped
2. **Effective date range**: If `effective_start` or `effective_end` are provided, date must fall within the range (inclusive)
3. **Day-of-week filter**: If `day_filters` is provided, the date's day of week must match
4. **Time window**: The Zone's time window must apply to the schedule being generated

If all checks pass, the Zone is active for that date.

## Operator Workflows

**Create Zone in Plan**: Operators create Zones as time windows within SchedulePlans. They specify:

- Name (e.g., "Morning Cartoons", "Prime Time", "Overnight")
- Time window (start_time, end_time in broadcast day time)
- SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets) to place in the Zone
- Optional day filters (restrict to specific days of week)

**Edit Zone**: Operators modify existing Zones to:

- Change time window
- Update SchedulableAssets
- Modify day filters
- Update name

**Preview Zone**: Operators preview how a Zone will resolve:

- See how SchedulableAssets are placed in the Zone's time window
- View grid alignment and timing
- Check for conflicts or rule violations

**Layer Zones**: Operators use multiple SchedulePlans with different priorities to layer Zones:

- Base plan with general Zones (e.g., weekday plan)
- Higher-priority plans with specific Zones (e.g., holiday plan)
- Higher-priority Zones override lower-priority Zones for overlapping time windows

## Examples

### Example 1: Morning Cartoons Zone

**Morning Cartoons zone for weekday programming:**

- Name: "Morning Cartoons"
- Start time: `06:00:00`
- End time: `12:00:00`
- SchedulableAssets: `["Tom & Jerry", "Looney Tunes", "Kids Interstitial Block"]`
- Day filters: `["MON", "TUE", "WED", "THU", "FRI"]` (active weekdays only)
- Result: Zone organizes morning content for weekdays, 06:00–12:00

### Example 2: Prime Time Zone

**Prime Time zone for evening programming:**

- Name: "Prime Time"
- Start time: `19:00:00`
- End time: `22:00:00`
- SchedulableAssets: `["Cheers", "The Big Bang Theory", "Movie Block"]`
- Day filters: `null` (active every day)
- Result: Zone organizes prime time content, 19:00–22:00

### Example 3: Overnight Zone (Spanning Midnight)

**Overnight zone spanning midnight:**

- Name: "Overnight"
- Start time: `22:00:00`
- End time: `05:00:00`
- SchedulableAssets: `["Classic Movies", "Test Pattern"]`
- Day filters: `null` (active every day)
- Result: Zone spans from 22:00 on one calendar day to 05:00 the next, but both times are within the same broadcast day. The "Test Pattern" is a system placeholder that may not appear in human-facing EPGs.

### Example 4: Base Zone with Test Pattern

**Base zone covering full programming day with test pattern:**

- Name: "Base"
- Start time: `00:00:00`
- End time: `24:00:00`
- SchedulableAssets: `["Test Pattern"]`
- Day filters: `null` (active every day)
- Result: Zone provides full 24-hour coverage with test pattern. The test pattern is a system placeholder that ensures coverage but doesn't need to appear in human-facing EPGs.

## Failure / Fallback Behavior

If Zones are missing or invalid:

- **Missing Zones**: Result in gaps in the schedule (allowed but should generate warnings). Under-filled time becomes avails.
- **Invalid time windows**: System validates Zone time windows against Grid boundaries and reports errors
- **Invalid SchedulableAsset references**: System validates that SchedulableAsset IDs reference valid entities. Invalid references are rejected at Zone creation/update time.
- **Overlapping Zones**: Priority resolution determines which Zone applies (higher priority wins)
- **Grid divisibility violations**: Zone duration must be divisible by `grid_block_minutes`. Violations are rejected at Zone creation/update time (domain-level validation), unless policy allows rounding.
- **DST transition conflicts**: On DST transition dates, Zone duration is validated per `dst_policy`. If policy is "reject" and duration cannot be accommodated, validation fails at Zone creation/update time.

## Naming Rules

The canonical name for this concept in code and documentation is Zone.

Zones are often referred to as "dayparts" or "time windows" in operator workflows, but the full name should be used in technical documentation and code.

## Validation & Invariants

- **Valid time window**: start_time and end_time must be valid times in broadcast day format (00:00:00 to 24:00:00)
- **Valid time range**: start_time must be less than end_time (unless spanning midnight, in which case end_time < start_time is allowed)
- **Valid SchedulableAsset references**: All SchedulableAsset IDs in `schedulable_assets` must reference valid entities (Programs, Assets, VirtualAssets, or SyntheticAssets)
- **Grid alignment**: Zone start and end times must align with the Channel's Grid boundaries (`block_start_offsets_minutes`). Validation occurs at Zone creation/update time (domain-level validation).
- **Grid divisibility**: Zone duration in minutes must be divisible by the Channel's `grid_block_minutes`. If not divisible, the system rejects the configuration unless a policy allows rounding to nearest boundary. Validation occurs at Zone creation/update time (domain-level validation).
- **Name uniqueness**: name must be unique within the SchedulePlan (enforced as invariant)
- **Day filter validity**: day_filters must be a valid JSON array of day abbreviations if provided
- **Effective date range**: effective_start and effective_end must form a valid date range (effective_start <= effective_end) if both are provided
- **DST policy**: On DST transition dates, Zone duration is validated per `dst_policy`: "reject" (fail validation), "shrink_one_block" (reduce duration by one grid block), or "expand_one_block" (increase duration by one grid block)
- **Enable/disable**: enabled defaults to true; disabled Zones are ignored during resolution

## Validation Notes

This section defines critical validation requirements that apply when Zones are used within SchedulePlan sessions or other planning/compilation contexts. **Note:** Zones are NOT a runtime construct — they are only used during planning and compilation.

### Single Source of Truth

**All Zone validation is performed by the domain validator.** Higher layers (CLI, Planning Session, APIs) MUST call the same validator and MUST NOT re-implement rules.

- Zone validation logic is centralized in the domain layer
- CLI commands, Planning Session workflows, and API endpoints must delegate to the domain validator
- Re-implementing validation rules in higher layers violates the single source of truth principle and risks inconsistencies
- The domain validator enforces all invariants defined in the Validation & Invariants section
- Validation failures must propagate from the domain layer with consistent error messages

### Clock & Timezone

**All time math uses `MasterClock.now()` and the Channel's timezone.** Tests may inject a fake clock.

- Zone activation evaluation uses `MasterClock.now()` for current time queries
- All time calculations respect the Channel's timezone configuration
- Broadcast day calculations use `Channel.programming_day_start` relative to the Channel's timezone
- Tests must use a test clock (fake clock) for deterministic behavior
- Production code must never use system time directly; always use `MasterClock.now()`
- Timezone-aware datetime operations ensure correct handling of DST transitions and time offsets

### Time Normalization

**24:00 is stored as 23:59:59.999999 and normalized back to 24:00:00 in the domain layer.** Seconds/microseconds MUST be 00 for start/end (except normalized end-of-day).

- PostgreSQL TIME type cannot store 24:00:00, so end-of-day Zones are stored as 23:59:59.999999
- Domain layer normalizes stored values back to conceptual 24:00:00 for all operations
- Zone start_time and end_time must have seconds and microseconds set to 00 (except for normalized end-of-day)
- Round-trip persistence (write → read → domain) must preserve the conceptual 24:00:00 value
- Duration calculations and time comparisons use normalized values internally
- External interfaces (CLI, API) display and accept 24:00:00 as the canonical representation

### Activation Order

**Activation is evaluated strictly in this order:** enabled → effective date range → day_filters → time window.

- Zone activation checks must be evaluated in the specified sequence (fail-fast)
- If `enabled=false`, Zone is skipped immediately (no further checks)
- If date falls outside `effective_start`/`effective_end` range, Zone is skipped
- If `day_filters` is provided and date's day doesn't match, Zone is skipped
- If time window doesn't match the current time, Zone is inactive
- All checks must pass for Zone to be active
- Order is critical for performance optimization (disabled Zones fail fast)

### Determinism

**Given the same inputs (plan, channel grid, clock), Zone selection and resolution are deterministic.**

- Zone activation results must be identical for identical inputs
- Zone resolution (SchedulableAsset placement) must produce the same schedule for the same inputs
- Deterministic behavior enables reproducible testing and predictable schedule generation
- Non-deterministic behavior (random selection, race conditions) must be explicitly avoided
- Test fixtures must provide deterministic inputs (fixed clock, fixed plan state, fixed grid configuration)
- ScheduleDay generation must be idempotent for the same inputs

## See Also

- [Scheduling Policies](SchedulingPolicies.md) - Scheduling policy behaviors
- [SchedulePlan](SchedulePlan.md) - Top-level operator-created plans that define channel programming (contain Zones)
- [ScheduleDay](ScheduleDay.md) - Resolved schedules for specific channel and date (generated from Zones and SchedulableAssets)
- [Program](Program.md) - SchedulableAsset type that can be placed in Zones
- [VirtualAsset](VirtualAsset.md) - SchedulableAsset type that expands to physical Assets at playlist generation
- [Channel](Channel.md) - Channel configuration and timing policy (owns Grid: `grid_block_minutes`, `block_start_offsets_minutes`, `programming_day_start`)
- [Scheduling](Scheduling.md) - High-level scheduling system
- [Operator CLI](../cli/README.md) - Operational procedures

Zone is a **scheduling abstraction** — a named time window within the programming day that organizes the broadcast schedule into logical areas. Zones divide the broadcast day into meaningful segments (e.g., "Morning Cartoons," "Prime Time," "Overnight") and contain one or more SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets). 

**Zones are NOT a runtime construct.** They are never executed, never seen by ChannelManager, and never sent to Air. Once a schedule is compiled (Zone → SchedulePlan → ScheduleItems → PlaylogSegments), Zones disappear. They exist only to help humans and the scheduler reason about dayparts, express constraints, and choose appropriate content during planning.

Zones use broadcast day time (00:00–24:00 relative to `programming_day_start`), not calendar day time. Zones can span midnight (e.g., `22:00–05:00`) within the same broadcast day and support optional day-of-week filters for recurring patterns. Test pattern or idle zones exist internally for system use but don't need to appear in human-facing EPGs.
