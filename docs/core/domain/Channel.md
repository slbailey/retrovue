_Related: [Architecture](../architecture/ArchitectureOverview.md) • [Runtime](../runtime/ChannelManager.md) • [Contracts](../contracts/resources/README.md) • [Operator CLI](../cli/README.md)_

# Domain — Channel

## Purpose

Define the canonical, persisted Channel entity. Channel is the time root for interpreting
schedule plans and building programming horizons in local time (inputs/outputs in
local time; timestamps stored in UTC). Channel defines a persistent broadcast entity with channel identity, configuration, and operational parameters for channels such as "RetroToons" or "MidnightMovies".

**Channel Grid:** Channel owns the **Grid** configuration that defines the temporal structure for all scheduling. The Grid consists of `grid_block_minutes`, `block_start_offsets_minutes`, and `programming_day_start`. All scheduling snaps to these boundaries — no content can be scheduled outside the grid constraints. The Grid is the foundation for all time-based scheduling operations.

## Persistence model

Scheduling-centric fields persisted on Channel:

- **id (UUID)** — primary key
- **slug (str, unique)** — lowercase kebab-case machine id; immutable post-create
- **title (str)** — operator-facing label
- **Grid configuration** (Channel owns the Grid):
  - **grid_block_minutes (int)** — base grid size; allowed: 15, 30, or 60
  - **block_start_offsets_minutes (json array[int])** — allowed minute offsets within the hour
    (e.g., `[0,30]`, `[5,35]`)
  - **programming_day_start (time)** — e.g., `06:00:00`; daypart anchor
- **kind (str)** — lightweight label; `network` | `premium` | `specialty` (non-functional in v0.1)
- **is_active (bool)** — included in horizon builders when true
- **created_at / updated_at (timestamps)** — audit fields (UTC)
- **version (int)** — optional optimistic-locking counter for concurrent updates

**Grid Ownership:** Channel owns the Grid configuration (`grid_block_minutes`, `block_start_offsets_minutes`, `programming_day_start`). All scheduling operations snap to these grid boundaries. The Grid defines when content can start and how time is structured for the channel.

The table is named `channels` (plural). Schema migration is handled through Alembic. Postgres is the authoritative backing store.

Constraints (guardrails):

- `title` max length ≤ 120 characters; `slug` max length ≤ 64 characters.

Naming rules:

- `slug` is lowercase, kebab-case (`a-z0-9-`), and never changes after creation.

## Contract / interface

- **Channel owns the Grid**: Channel provides the Grid configuration (`grid_block_minutes`, `block_start_offsets_minutes`, `programming_day_start`) that defines temporal boundaries for all scheduling. All scheduling snaps to these grid boundaries.
- Channel provides the temporal context for:
  - validating block alignment against `block_start_offsets_minutes`,
  - grid math using `grid_block_minutes`,
  - computing programming day boundaries anchored by `programming_day_start` (local time).
- Horizon builders and EPG generation consult only Channels where `is_active=true`.
- CLI/Usecases expose CRUD-like operations; deletions require no dependent references.
- A system-level `validateChannel(channelId)` use case recomputes and reports all invariant
  violations across dependent `SchedulePlan` and `ScheduleDay` assignments.
- ScheduleService consumes Channel records to determine current programming. It generates schedule data using the channel's grid configuration for accurate block-based scheduling.
- Channel provides the identity and context for scheduling operations. ScheduleService is authoritative for what to play.

## Scheduling model

- **Grid boundaries**: All scheduling snaps to the Channel's Grid boundaries (`grid_block_minutes`, `block_start_offsets_minutes`, `programming_day_start`). No content can be scheduled outside these constraints.
- All dayparts and plans are channel-scoped and interpreted in local time, anchored to
  `programming_day_start`.
- Block starts must align to the channel's allowed offsets; durations are expressed in grid
  blocks (not minutes).

## Grid & Boundaries

The Channel's Grid configuration defines the temporal structure for all scheduling operations. The Grid consists of three key components:

- **`grid_block_minutes`** defines the canonical grid; all placements snap to it. This is the base unit of time alignment (15, 30, or 60 minutes) that determines when content can start and how durations are measured.

- **`block_start_offsets_minutes`** constrain valid starts within each hour. This array specifies the minute offsets (e.g., `[0,30]` or `[5,35]`) where content blocks can begin, ensuring alignment with the grid while allowing flexibility within hourly boundaries.

- **`programming_day_start`** anchors the broadcast day, including DST; ScheduleDay is cut by this boundary. This time (e.g., `06:00:00`) defines when the programming day begins in local time, and all schedule days are cut at this boundary regardless of wall-clock midnight or DST transitions.

### Why grid?

The Grid system provides predictable, consistent scheduling behavior across the entire broadcast system. It enables:

- **Predictable EPG**: Electronic Program Guides can display consistent grid blocks that align with viewer expectations, with programs starting at predictable intervals (e.g., every 30 minutes on the half-hour).

- **Ad math**: Advertising placement and revenue calculations become straightforward when content aligns to standard grid boundaries, making it easy to calculate ad pod positions and fill rates.

- **Snap-at-boundary behavior**: All content placement automatically aligns to grid boundaries, eliminating fractional-minute scheduling and ensuring clean transitions between programs. This simplifies both operator workflows and system logic.

### Time and calendar semantics

- Programming days are anchored to `programming_day_start` in local time. A block belongs to
  the programming day whose anchor is the most recent at-or-before the block's start
  timestamp, even when the block crosses wall-clock midnight.
- On DST transitions, programming days may contain 23 or 25 wall-clock hours. Block math is
  derived from grid counts; do not assume 60-minute hours.

### Effective-dated changes

- (removed) Timezone edits are not configurable; all inputs are interpreted in local time.
- Programming-day anchor (`programming_day_start`) changes: MUST be effective-dated and trigger
  dependent rebuilds from that date forward; prevent silent reassignment of historical blocks.

## Execution model

**Channel (config, identity) → ProgramDirector**: Channel provides configuration and identity to ProgramDirector for system-wide coordination and policy enforcement.

**ChannelRuntime → ChannelManager**: ChannelManager uses Channel configuration to know how to interpret 'now' and how to cut the day (rollover). A Channel continues to exist even when nobody is watching and the playout engine is torn down.

Channel has relationships with schedule data through ScheduleDay, which links channels to plans for specific broadcast dates.

## Failure / fallback behavior

If channel configuration is invalid, the system falls back to default programming or the most recent valid configuration.

## Operator workflows

Operators manage Channels via standard workflows:

- Create, update, list, show, validate
- Archive via `is_active=false`
- Delete (only if no dependencies reference the channel)

### CLI command examples

**Create Channel**: Use `retrovue channel create` with required parameters:

```bash
retrovue channel create --slug "retrotoons" --title "RetroToons" \
  --grid-block-minutes 30 --programming-day-start "06:00:00" \
  --block-start-offsets-minutes "[0,30]" --active
```

**List channels**: Use `retrovue channel list` to see all channels in table format, or `retrovue channel list --json` for machine-readable output.

**Inspect channel**: Use `retrovue channel show --id <uuid>` or `retrovue channel show --slug <slug>` to see detailed channel information.

**Activate/deactivate**: Use `retrovue channel update --id <uuid> --active` or `--inactive` to toggle is_active status.

**Adjust scheduling**: Use `retrovue channel update --id <uuid>` with new grid parameters to modify schedule block alignment and day cutover behavior.

**Retire channel**: Use `retrovue channel update --id <uuid> --inactive` to remove from routing and scheduling, or `retrovue channel delete --id <uuid>` to permanently remove (only if no dependencies exist).

**Update channel**: Use `retrovue channel update --id <uuid>` with any combination of fields to modify channel properties.

All operations use UUID identifiers for channel identification. The CLI provides both human-readable and JSON output formats.

### Lifecycle and referential integrity

- `is_active=false` archives the channel for prospective operations: horizon builders and EPG
  generation exclude the channel going forward. Already-materialized horizons/EPG rows are not
  retroactively deleted; operators may trigger rebuilds if policy requires.
- Hard delete is only permitted when no dependent rows exist (e.g., `SchedulePlan`,
  `ScheduleDay`, EPG rows, playout configurations). When dependencies exist, prefer archival
  (`is_active=false`). The delete path MUST verify the absence of these references.
  The dependency preflight MUST cover: `SchedulePlan`, `ScheduleDay`, EPG rows, playout
  pipelines/configs, broadcast bindings, and ad/avail policies (when present).

## Validation & invariants

- **Slug immutability**: `slug` is unique and immutable post-creation.
- **Grid size**: `grid_block_minutes ∈ {15,30,60}`.
- **Offsets validity**: `block_start_offsets_minutes` is sorted, unique, values in `0–59`.
- **Grid alignment (chosen rule)**: every offset satisfies `offset % grid_block_minutes == 0`.
- **Programming day start alignment**: `programming_day_start.minute % grid_block_minutes == 0`
  and `programming_day_start.minute ∈ block_start_offsets_minutes`.
- **Second alignment**: All starts are minute-precision; seconds MUST equal `00`.
- **Activity filter**: horizon builders exclude channels where `is_active=false`.

Offset set shape:

- Require `1 ≤ len(block_start_offsets_minutes) ≤ 6`.
- Require monotone hourly repeatability: the same set of allowed offsets applies to every
  hour uniformly.

Validation guidelines:

- Reject plans or assignments that violate offset/grid rules for the channel.
- Changing `grid_block_minutes` or `block_start_offsets_minutes` requires revalidation of
  existing `SchedulePlan` and `ScheduleDay` assignments; consider a temporary
  "pending-change" state with migration aids (diffs and fix-up suggestions).

### Input validation surface

- (removed) IANA timezone validation is not applicable.
- `kind` is a forward-compatible enum; unknown values fail closed.
- Title and slug constraints: enforce lowercase kebab-case for `slug` at write-time, maximum
  lengths, reserved words, and normalization; reject on violation.
- Audit timestamps are stored as UTC; define whether DB triggers or application code sets
  `created_at`/`updated_at` consistently.

## Out of scope (v0.1)

Branding, overlays, content ratings, ad/avail policy, guide playout specifics.

## Scheduling policy clarifications

- Durations are specified in grid blocks. When mapping content to blocks:
  - If content runtime is shorter than allocated blocks, any underfill is handled per
    plan rules and finalized during playlog building.
  - Longform MAY consume multiple grid blocks per Program `slot_units` or plan policy. The scheduler never cuts longform mid-program; handoffs snap to the next grid boundary (soft-start).
- Horizon window: default look-ahead and look-behind windows are implementation-defined (e.g.,
  14 days ahead, 1 day behind). Rebuild triggers include channel field changes (grid, offsets,
  `programming_day_start`), plan edits, and content substitutions.

## Concurrency & operations

- Use optimistic locking for updates (e.g., `version` or `updated_at` precondition) to avoid
  last-write-wins overwrites.
- When flipping `is_active` from false to true, the system SHOULD backfill missing
  horizons/EPG for the standard window.

Version semantics:

- Updates MUST include the current `version` precondition and fail if it does not match the
  persisted value; on success increment `version` by 1 (never resets).
- Define the system of record for increments (DB trigger vs application layer) and apply it
  consistently.

## Validator entrypoint

- `validateChannel(channelId)` recomputes invariants and cross-validates dependent
  `SchedulePlan`/`ScheduleDay` for block alignment policies. If
  `grid_block_minutes`/offsets change, mark all dependents as `needs-review`.
  When validation flags `needs-review` or violations, emit a typed observability event such as
  `channel.validation.failed` for job runners/ops workflows.

## Lint rules (non-fatal warnings)

- Warn if `grid_block_minutes=60` but `block_start_offsets_minutes` contains non-zero values.
- Warn if offsets are "sparse" or unusual (e.g., only `[47]`).

## API guardrails (non-binding domain guidance)

- Channel list responses SHOULD support pagination to avoid large unbounded payloads.

## See also

- [SchedulePlan](SchedulePlan.md) — Top-level operator-created plans that define channel programming
- [ScheduleDay](ScheduleDay.md) — Resolved schedules for specific channel and date
- [Scheduling](Scheduling.md) — Planning-time logic for future air
- [EPGGeneration](EPGGeneration.md) — Electronic Program Guide generation
