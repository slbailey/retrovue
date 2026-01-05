_Related: [Architecture](../architecture/ArchitectureOverview.md) • [SchedulePlan](SchedulePlan.md) • [ScheduleDay](ScheduleDay.md) • [Playlist](../architecture/Playlist.md) • [VirtualAsset](VirtualAsset.md) • [Zone](Zone.md) • [Operator CLI](../cli/README.md)_

# Domain — Program

> **Note:** This document reflects the modern scheduling architecture. Active chain: **SchedulePlan (Zones + SchedulableAssets) → ScheduleDay (resolved) → Playlist → PlaylogEvent (runtime) → AsRunLog.**

## Purpose

Program is a **linked list of SchedulableAssets** that defines ordering and sequencing of content, not playback duration. Each node in the linked list points to a specific SchedulableAsset (Catalog Asset, another Program, or VirtualAsset) and optionally to the next node, enabling composite or recursive program structures. Programs carry metadata that defines scheduling behavior (e.g., random vs serial playback, intro/outro inclusion rules, shuffle weight, etc.) but do not define duration — duration is determined by the Zone or Schedule context in which the program runs.

**What a Program is:**

- A **linked list of SchedulableAssets** — each node contains a `schedulable_asset_id`, `asset_type`, and optional `next_id` pointer
- Defines **ordering and sequencing** of content, not playback duration
- A reusable collection definition that carries metadata to distinguish variants (e.g., "Cheers (Syndicated)" vs "Cheers (Serial)")
- Contains nodes that can reference Programs (for nesting), Assets, VirtualAssets, or SyntheticAssets
- Defines playback policy via `play_mode` and other metadata (random, sequential, manual, shuffle weight, etc.)
- Defines composition rules and sequence, not actual airtime (timing comes from Zone placement)

**What a Program is not:**

- A per-day time-block assignment (that's Zone placement in ScheduleDay)
- A container with separate intro/outro fields (bumpers/idents/etc. are nodes in the linked list, not dedicated fields)
- A runtime object (Programs are scheduling-time entities that resolve to physical assets at playlist generation)
- An airtime or duration definition (Programs define what to play and in what order, not when or for how long; timing and duration come from Zones and Schedule context)
- A Producer container (Producers operate at playout time in the Playlist or runtime layer; Programs are abstract containers)

## Relationships

Program fits under the **SchedulableAsset layer** in the scheduling architecture:

```
SchedulePlan (Zones hold SchedulableAssets)
    ↓
ScheduleDay (SchedulableAssets placed in Zones with wall-clock times)
    ↓
Playlist (Programs expand to physical assets via asset_chain resolution)
    ↓
PlaylogEvent (runtime execution plan)
```

**Program relationships:**

- **SchedulePlan → Program**: Programs are placed in Zones within SchedulePlans. Zones declare when Programs should play (time windows), while Programs define what content plays.
- **Program → ScheduleDay**: When SchedulePlans are resolved into ScheduleDays (3-4 days in advance), Programs flow through with their asset chains intact. ScheduleDay preserves SchedulableAsset references.
- **Program → Playlist**: At playlist generation time, Programs expand their `asset_chain` to concrete physical assets based on `play_mode`. This is where Programs resolve to actual files.
- **Program → Program**: Programs can reference other Programs in their `asset_chain`, enabling nested collections and composite programming blocks.
- **Program → Asset/VirtualAsset/SyntheticAsset**: Programs reference these SchedulableAsset types in their `asset_chain` to compose content sequences.

**Key architectural position:**

- Programs are **SchedulableAssets** placed in Zones within SchedulePlans
- Programs flow through ScheduleDay (resolved 3-4 days in advance for EPG)
- Programs expand to physical assets at Playlist generation time
- Programs define reusable composition rules, ordering, and sequencing, not airtime or duration (timing and duration come from Zone placement and Schedule context)
- Producers operate at playout time in the Playlist or runtime layer; Programs are abstract containers and do not carry Producer references

## Attributes

Program is managed by SQLAlchemy with the following fields:

- **id** (UUID, primary key): Unique identifier for relational joins and foreign key references
- **name** (Text, required): Human-readable identifier (e.g., "Cheers (Syndicated)", "Morning Cartoon Block")
- **play_mode** (Text, required): Playback policy - one of: "random", "sequential", "manual"
- **asset_chain** (JSON, required): Linked list of nodes, where each node contains `schedulable_asset_id`, `asset_type`, and optional `next_id` pointer
- **metadata** (JSON, optional): Metadata to distinguish variants and control selection (e.g., series, season, parental_rating, tags, shuffle_weight, intro/outro inclusion rules)
- **active** (Boolean, required, default: true): Whether the Program is active and eligible for scheduling
- **created_at** (DateTime(timezone=True), required): Record creation timestamp
- **updated_at** (DateTime(timezone=True), required): Record last modification timestamp

**Critical attributes:**

- **`asset_chain`**: JSON array of linked list nodes, where each node contains:

  - `schedulable_asset_id` (UUID, required): Reference to a SchedulableAsset (Program, Asset, VirtualAsset, or SyntheticAsset)
  - `asset_type` (Text, required): Type of the referenced asset ("program", "asset", "virtual_asset", "synthetic_asset")
  - `next_id` (Integer, optional): Index (0-based) of the next node in the linked list within the `asset_chain` array, or `null` for the last node

  This linked list defines the content sequence and ordering. **Intro/outro bumpers, idents, and other elements are nodes in this linked list, not separate fields.** The chain can include Programs (for nesting), Assets, VirtualAssets, and SyntheticAssets. Programs define ordering and sequencing, not playback duration — duration is determined by the Zone or Schedule context.

- **`play_mode`**: Controls how the asset chain is played:
  - `"random"`: Assets in chain are selected randomly (useful for pools)
  - `"sequential"`: Assets are played in chain order (e.g., "Cheers (Serial)")
  - `"manual"`: Assets are selected manually by operators (e.g., "Cheers (Syndicated)")
- **`metadata`**: Contains scheduling behavior metadata:
  - `shuffle_weight`: Weight for random selection (if applicable)
  - `intro_inclusion_rule`: Rules for including intro bumpers
  - `outro_inclusion_rule`: Rules for including outro bumpers
  - `series`, `season`, `parental_rating`, `tags`: Content metadata for selection and filtering

### Table Name

The table is named `programs` (plural). Schema migration is handled through Alembic. Postgres is the authoritative backing store.

### Constraints

- `name` must be non-empty and unique within the channel
- `play_mode` must be one of: "random", "sequential", "manual"
- `asset_chain` must be a valid JSON array of linked list nodes (non-empty)
- Each node must contain `schedulable_asset_id` and `asset_type`
- All `schedulable_asset_id` values in `asset_chain` nodes must reference valid SchedulableAssets (Programs, Assets, VirtualAssets, or SyntheticAssets)
- `next_id` pointers must form a valid linked list (each `next_id` must either be `null` or a valid integer index within the `asset_chain` array bounds)
- No circular references: Programs in asset chains must not create circular dependencies

## Behavior

### Linked List Model

Programs reference other SchedulableAssets via a **linked list** stored in `asset_chain`. Each node in the linked list contains a `schedulable_asset_id`, `asset_type`, and optional `next_id` pointer to the next node. This structure enables composite or recursive program structures.

**Node structure:**

Each node in the `asset_chain` contains:

- `schedulable_asset_id` (UUID): Reference to a SchedulableAsset
- `asset_type` (Text): Type of the referenced asset ("program", "asset", "virtual_asset", "synthetic_asset")
- `next_id` (UUID, optional): Pointer to the next node in the linked list (null for the last node)

**Supported node types:**

- **Programs**: Other Programs (enables nested collections and composite blocks)
- **Assets**: Physical file assets (episodes, movies, bumpers, idents)
- **VirtualAssets**: Input-driven composites that expand at playlist generation
- **SyntheticAssets**: Generated content (e.g., test patterns, countdown clocks)

**Intro/outro bumpers are nodes in the linked list, not dedicated fields.** For example, a Program with an intro bumper, episode pool, and outro bumper would have an `asset_chain` like:

```json
[
  {
    "schedulable_asset_id": "intro-bumper-asset-id",
    "asset_type": "asset",
    "next_id": 1
  },
  {
    "schedulable_asset_id": "episode-pool-virtual-asset-id",
    "asset_type": "virtual_asset",
    "next_id": 2
  },
  {
    "schedulable_asset_id": "outro-bumper-asset-id",
    "asset_type": "asset",
    "next_id": null
  }
]
```

**Note:** `next_id` is an integer index (0-based) into the `asset_chain` array, or `null` for the last node in the list.

All elements are treated as regular nodes in the linked list. There are no separate `intro_asset_id` or `outro_asset_id` fields. The linked list defines **ordering and sequencing**, not playback duration — duration is determined by the Zone or Schedule context in which the program runs.

### Scheduling Behavior Metadata

Programs carry metadata that defines scheduling behavior, including playback modes and selection rules:

**Playback modes (`play_mode`):**

- `"random"`: Assets in chain are selected randomly (useful for pools)
- `"sequential"`: Assets are played in chain order (e.g., "Cheers (Serial)")
- `"manual"`: Assets are selected manually by operators (e.g., "Cheers (Syndicated)")

**Metadata fields:**

- `shuffle_weight`: Weight for random selection (if applicable)
- `intro_inclusion_rule`: Rules for including intro bumpers (e.g., "always", "never", "conditional")
- `outro_inclusion_rule`: Rules for including outro bumpers (e.g., "always", "never", "conditional")
- `series`, `season`, `parental_rating`, `tags`: Content metadata for selection and filtering
- `variant`: Distinguishes program variants (e.g., "syndicated", "serial")

**Examples:**

- **"Cheers (Syndicated)"**: `play_mode: "manual"` — operators manually select episodes from the pool. Metadata includes `series: "Cheers"`, `variant: "syndicated"`, `intro_inclusion_rule: "always"`, `outro_inclusion_rule: "always"`.
- **"Cheers (Serial)"**: `play_mode: "sequential"` — episodes play in order. Metadata includes `series: "Cheers"`, `variant: "serial"`, `shuffle_weight: 1.0`.

The same series can have multiple Program variants, each with different playback policies and metadata, enabling flexible scheduling behaviors.

### Schedule Resolution Flow

Programs flow through the scheduling pipeline:

1. **Plan Resolution**: ScheduleService identifies active SchedulePlans for a channel and date. Programs are placed in Zones within these plans.
2. **Zone Resolution**: Zones (time windows) contain SchedulableAssets including Programs. Zone time windows declare when Programs should play.
3. **ScheduleDay Generation**: Programs flow into ScheduleDay (resolved 3-4 days in advance) with their asset chains intact. Programs remain as SchedulableAsset references in ScheduleDay; expansion happens later.
4. **Playlist Generation**: At playlist generation time, Programs expand their `asset_chain` to concrete physical assets:
   - `play_mode: "random"` → randomly select from chain
   - `play_mode: "sequential"` → play in chain order
   - `play_mode: "manual"` → use operator-selected assets
   - VirtualAssets in chains expand into one or more physical Assets
5. **PlaylogEvent Generation**: Playlists are used to generate PlaylogEvent records for playout execution.

**Critical rule:** Programs define reusable composition rules, ordering, and sequencing, not airtime or duration. Timing comes from Zone placement, and duration is determined by the Zone or Schedule context. Programs placed in a Zone at 19:00-22:00 will play during that window, but the Program itself doesn't define the time — the Zone does. Similarly, playback duration is determined by the context in which the Program runs, not by the Program itself.

### Program Expansion at Playlist Generation

When a Program expands at playlist generation:

1. The `asset_chain` linked list is traversed starting from the first node (index 0), following `next_id` pointers until `null` is reached
2. Each node's `schedulable_asset_id` is resolved based on `asset_type`:
   - **Assets** → physical file entries
   - **VirtualAssets** → expand to one or more physical Assets
   - **SyntheticAssets** → generate content specifications
   - **Programs** → recursively expand their asset chains (following their linked list structure)
3. `play_mode` and metadata determine selection and behavior:
   - Random selection from pools (using `shuffle_weight` if specified)
   - Sequential progression through ordered lists
   - Manual operator selections
   - Intro/outro inclusion rules from metadata are applied
4. The expanded sequence becomes Playlist entries with absolute timecodes
5. **Producer assignment** happens at playout time in the Playlist or runtime layer — Programs are abstract containers and do not carry Producer references

## Example

### YAML Example: Program Definition

```yaml
# Cheers (Syndicated) Program
id: "550e8400-e29b-41d4-a716-446655440000"
name: "Cheers (Syndicated)"
play_mode: "manual"
asset_chain:
  - schedulable_asset_id: "intro-bumper-uuid"
    asset_type: "asset"
    next_id: 1
  - schedulable_asset_id: "cheers-episode-pool-uuid"
    asset_type: "virtual_asset"
    next_id: 2
  - schedulable_asset_id: "outro-bumper-uuid"
    asset_type: "asset"
    next_id: null
metadata:
  series: "Cheers"
  variant: "syndicated"
  parental_rating: "TV-PG"
  intro_inclusion_rule: "always"
  outro_inclusion_rule: "always"
active: true
```

**Key points:**

- Intro and outro bumpers are nodes in the linked list, not separate fields
- Each node contains `schedulable_asset_id`, `asset_type`, and optional `next_id` pointer
- Episode pool is a VirtualAsset node that expands at playlist generation
- `play_mode: "manual"` means operators select specific episodes
- Metadata includes scheduling behavior rules (intro/outro inclusion rules)
- The linked list defines ordering and sequencing, not playback duration

### Example: Cheers (Syndicated) vs Cheers (Serial)

**Cheers (Syndicated)** — Manual selection:

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Cheers (Syndicated)",
  "play_mode": "manual",
  "asset_chain": [
    {
      "schedulable_asset_id": "intro-bumper-uuid",
      "asset_type": "asset",
      "next_id": 1
    },
    {
      "schedulable_asset_id": "cheers-episode-pool-uuid",
      "asset_type": "virtual_asset",
      "next_id": 2
    },
    {
      "schedulable_asset_id": "outro-bumper-uuid",
      "asset_type": "asset",
      "next_id": null
    }
  ],
  "metadata": {
    "series": "Cheers",
    "variant": "syndicated",
    "parental_rating": "TV-PG",
    "intro_inclusion_rule": "always",
    "outro_inclusion_rule": "always"
  }
}
```

**Behavior:** Operators manually select which Cheers episode plays. The linked list includes intro bumper, episode pool (VirtualAsset), and outro bumper nodes. At playlist generation, the operator's selection replaces the pool reference. The linked list defines the ordering and sequence, not playback duration.

**Cheers (Serial)** — Sequential playback:

```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "name": "Cheers (Serial)",
  "play_mode": "sequential",
  "asset_chain": [
    {
      "schedulable_asset_id": "station-ident-uuid",
      "asset_type": "asset",
      "next_id": 1
    },
    {
      "schedulable_asset_id": "cheers-episode-sequence-uuid",
      "asset_type": "virtual_asset",
      "next_id": null
    }
  ],
  "metadata": {
    "series": "Cheers",
    "variant": "serial",
    "parental_rating": "TV-PG",
    "shuffle_weight": 1.0
  }
}
```

**Behavior:** Episodes play sequentially in order. The linked list includes station ident and an ordered sequence of Cheers episodes. At playlist generation, the next episode in sequence is selected automatically. The linked list defines the ordering, not playback duration.

**Difference:** The key difference is `play_mode` — "manual" vs "sequential". Both reference Cheers content, but playback behavior differs. Metadata distinguishes the variants for selection and reporting, and includes scheduling behavior rules.

### Example: Program with Nested Programs

```json
{
  "id": "770e8400-e29b-41d4-a716-446655440002",
  "name": "Morning Cartoon Block",
  "play_mode": "random",
  "asset_chain": [
    {
      "schedulable_asset_id": "morning-intro-uuid",
      "asset_type": "asset",
      "next_id": 1
    },
    {
      "schedulable_asset_id": "spongebob-program-uuid",
      "asset_type": "program",
      "next_id": 2
    },
    {
      "schedulable_asset_id": "tom-and-jerry-program-uuid",
      "asset_type": "program",
      "next_id": 3
    },
    {
      "schedulable_asset_id": "morning-outro-uuid",
      "asset_type": "asset",
      "next_id": null
    }
  ],
  "metadata": {
    "daypart": "morning",
    "target_audience": "children",
    "parental_rating": "TV-Y",
    "shuffle_weight": 1.0
  }
}
```

**Behavior:** This Program composes a morning cartoon block by referencing other Programs (SpongeBob and Tom & Jerry) in the linked list. At playlist generation, each nested Program expands its asset chain (following its linked list structure), and `play_mode: "random"` selects randomly from available content. The linked list defines the ordering and sequence of content, not playback duration.

### Example: Flow Through Schedule Pipeline

**SchedulePlan:**

- Zone: 19:00–22:00 (Prime Time)
- Program: "Cheers (Syndicated)" placed in Zone

**ScheduleDay (resolved 3-4 days in advance):**

- Program reference maintained with asset chain intact
- Zone time window: 19:00–22:00
- Wall-clock times calculated from Zone + Channel Grid

**Playlist Generation:**

- Program expands linked list (following `next_id` pointers):
  1. Intro bumper asset node → physical file entry
  2. Cheers episode pool (VirtualAsset) node → operator-selected episode → physical file entry
  3. Outro bumper asset node → physical file entry
- Playlist entries have absolute timecodes
- **Producer assignment** happens at playout time — Programs are abstract containers and do not carry Producer references

**PlaylogEvent:**

- Playlist entries become PlaylogEvent records
- Aligned to MasterClock for playout execution
- Producers operate at playout time in the Playlist or runtime layer

## Failure / Fallback Behavior

If Programs are missing or invalid:

- **Missing Programs**: Result in gaps in the schedule (allowed but should generate warnings)
- **Invalid asset chain references**: System falls back to default content or skips invalid entries in the chain
- **Unresolvable asset chain**: If assets in the chain cannot be resolved, system falls back to alternative content or leaves gap
- **Invalid play modes**: System falls back to default play mode (sequential) if specified mode is invalid
- **VirtualAsset expansion failures**: If VirtualAsset in chain cannot expand, system falls back to alternative content or leaves gap
- **Circular references**: System detects and prevents circular Program references in asset chains

## Naming Rules

The canonical name for this concept in code and documentation is Program.

Programs are often referred to as "block assignments" or simply "programs" in operator workflows, but the full name should be used in technical documentation and code.

## Validation & Invariants

- **Valid name**: name must be non-empty and unique within the channel
- **Valid play mode**: play_mode must be one of: "random", "sequential", "manual"
- **Valid asset chain**: asset_chain must be a non-empty JSON array of linked list nodes
- **Node structure**: Each node must contain `schedulable_asset_id` and `asset_type`
- **Linked list integrity**: `next_id` pointers must form a valid linked list (each `next_id` must either be null or reference a valid node in the same `asset_chain`)
- **Referential integrity**: All `schedulable_asset_id` values in asset_chain nodes must reference valid SchedulableAssets (Programs, Assets, VirtualAssets, or SyntheticAssets)
- **No circular references**: Programs in asset chains must not create circular dependencies

## See Also

- [SchedulePlan](SchedulePlan.md) - Top-level operator-created plans that define channel programming using Zones
- [ScheduleDay](ScheduleDay.md) - Resolved schedules for specific channel and date (Programs flow through ScheduleDay)
- [Playlist](../architecture/Playlist.md) - Resolved pre–AsRun list of physical assets (Programs expand here)
- [Zone](Zone.md) - Time windows that hold SchedulableAssets including Programs
- [VirtualAsset](VirtualAsset.md) - Input-driven composites that expand at playlist generation (can be referenced in asset chains)
- [PlaylogEvent](PlaylogEvent.md) - Runtime execution plan aligned to MasterClock
- [Scheduling](Scheduling.md) - High-level scheduling system
- [Channel](Channel.md) - Channel configuration and timing policy
- [Asset](Asset.md) - Approved content available for scheduling
- [Operator CLI](../cli/README.md) - Operational procedures

Program is a **linked list of SchedulableAssets** that defines ordering and sequencing of content, not playback duration. Each node in the linked list points to a specific SchedulableAsset (Catalog Asset, another Program, or VirtualAsset) and optionally to the next node, enabling composite or recursive program structures. Programs carry metadata that defines scheduling behavior (e.g., random vs serial playback, intro/outro inclusion rules, shuffle weight, etc.) but do not define duration — duration is determined by the Zone or Schedule context in which the program runs. Intro/outro bumpers are nodes in the linked list, not dedicated fields. Programs are placed in Zones within SchedulePlans and flow through ScheduleDay to Playlist generation, where they expand to concrete physical assets. Programs define what to play and in what order, not when or for how long — timing and duration come from Zone placement and Schedule context. Producers operate at playout time in the Playlist or runtime layer; Programs are abstract containers and do not carry Producer references.
