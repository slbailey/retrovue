_Related: [Architecture](../architecture/ArchitectureOverview.md) • [Asset](Asset.md) • [SchedulePlan](SchedulePlan.md) • [Program](Program.md) • [ScheduleDay](ScheduleDay.md) • [PlaylogEvent](PlaylogEvent.md)_

# Domain — VirtualAsset

**⚠️ FUTURE FEATURE — NOT MVP-CRITICAL**

This document describes a planned feature that is not part of the initial MVP release. This feature may be implemented in a future version of RetroVue.

## Purpose

VirtualAsset is a **SchedulableAsset** subclass that acts as a template or composite wrapper referencing other assets. Unlike physical Assets (which are files), VirtualAssets are design-time constructs that dynamically resolve to real assets when instantiated in a Playlist.

**What a VirtualAsset is:**

- A **SchedulableAsset** subclass (concrete implementation of the abstract base)
- A **template or composite wrapper** that references other assets, not a file itself
- A **design/planning-time entity** that exists only during schedule planning, not in the runtime layer
- A **dynamic selector** that resolves to concrete Assets when a Playlist is generated from a ScheduleDay

**What a VirtualAsset is not:**

- A physical file or media asset (VirtualAssets have no `canonical_uri`, `source_uri`, or file size)
- A runtime entity (VirtualAssets do not exist in PlaylogEvent or the playout stream)
- A Producer (VirtualAssets expand to physical Assets which then feed standard Producers)

**Examples:**

- **"Movie of the Day"** — A VirtualAsset that selects one movie from a pool of eligible films each day, dynamically resolving to a specific movie asset when the Playlist is generated
- **"Cartoon Marathon"** — A VirtualAsset that selects multiple cartoon episodes from a collection, creating a themed block that varies each time it's scheduled

**Critical Rule:** VirtualAssets exist only at **design/planning time**. They are SchedulableAssets that can be placed in Zones or referenced in Program asset chains during schedule planning. When a Playlist is generated from a ScheduleDay, VirtualAssets expand into one or more physical Assets (files) which then feed the appropriate Producer (usually AssetProducer). There is no "VirtualProducer" — Producers are output-oriented runtime components that operate on physical Assets.

**Key Characteristics:**

- **SchedulableAsset subclass**: VirtualAsset is a concrete SchedulableAsset implementation
- **Template/composite wrapper**: VirtualAsset references other assets but is not itself a file
- **Design/planning-time only**: VirtualAssets exist only during schedule planning, not in runtime
- **Dynamic resolution**: VirtualAssets resolve to concrete Assets when Playlists are generated
- **Scheduling-time equivalence**: At scheduling time, VirtualAssets are treated identically to regular Assets

VirtualAssets provide a way to:

- **Package asset sequences**: Create reusable bundles of assets (e.g., intro → clip → clip)
- **Define rule-based collections**: Specify dynamic asset selections (e.g., "Movie of the Day" selects from a movie pool)
- **Enable modular programming**: Reference complex asset combinations as a single unit in Zones or Program asset chains
- **Support content reuse**: Define once, use many times across different plans and ScheduleDay entries

## Core Model / Scope

VirtualAsset is a **SchedulableAsset** subclass that enables:

- **Template/composite wrappers**: Act as templates that reference other assets but are not files themselves
- **Fixed sequences**: Predefined ordered lists of assets (e.g., branded intro → episode clip → outro bumper)
- **Rule-based definitions**: Dynamic asset selections based on rules (e.g., "Movie of the Day" selects from a movie pool)
- **Modular packaging**: Group related assets into reusable bundles
- **Design/planning-time existence**: Exist only during schedule planning, not in the runtime layer
- **Dynamic resolution**: Resolve to concrete Assets when Playlists are generated from ScheduleDays

**Key Points:**

- VirtualAsset is a **SchedulableAsset** subclass (concrete implementation of the abstract base)
- VirtualAsset is a **template or composite wrapper** that references other assets, not a file itself
- VirtualAsset exists only at **design/planning time** — not in PlaylogEvent or the playout stream
- VirtualAssets can be placed directly in Zones or referenced in Program asset chains during schedule planning
- At **playlist generation**, VirtualAssets expand into one or more physical Assets (files)
- Expanded physical Assets feed appropriate Producers (usually AssetProducer)
- There is no "VirtualProducer" — Producers are output-oriented runtime components that operate on physical Assets

## Types of VirtualAssets

VirtualAssets come in two fundamental types, distinguished by how they expand to concrete assets:

### Fixed Sequence VirtualAsset

A **predefined ordered list of assets** that always plays in the same sequence. The expansion is deterministic — the same VirtualAsset always expands to the same sequence of assets in the same order.

**Expansion Behavior:**

- Fixed sequences expand to a predetermined list of Asset UUIDs
- The order is always preserved: first asset in sequence → second asset → third asset, etc.
- Each asset reference in the sequence must resolve to a valid Asset in the catalog
- Expansion happens at playlist generation, not at ScheduleDay time

**Example:** Branded intro → Episode clip → Outro bumper

- Intro asset: `branded-intro-2024.mp4` (fixed Asset UUID)
- Episode clip: Selected from series based on episode policy (may vary per expansion)
- Outro bumper: `station-outro.mp4` (fixed Asset UUID)

**Use Case:** Consistent branding and packaging for episodic content where the intro/outro remain constant but the main content varies. The structure is fixed, but some components may be selected dynamically.

### Rule-Based VirtualAsset

A **dynamic asset selection based on rules and constraints**. The expansion is non-deterministic — the same VirtualAsset may expand to different assets each time, based on current rules and available catalog content.

**Expansion Behavior:**

- Rule-based VirtualAssets evaluate their rules against the current asset catalog at expansion time
- Rules can specify selection criteria (genre, duration, series, freshness, etc.)
- Rules can specify ordering (random, chronological, least-recently-used, etc.)
- Rules can specify constraints (minimum/maximum duration, count limits, etc.)
- Expansion happens at ScheduleDay time (preferred) or Playlog time (fallback)
- Each expansion may produce different asset selections based on current catalog state

**Example:** "3 random SpongeBob 11-min segments + branded intro"

- Rule: Select 3 random assets from SpongeBob series
- Constraint: Each segment must be approximately 11 minutes (10-12 minute range)
- Fixed component: Branded intro plays first (always the same Asset UUID)
- Order: Intro → Random segment 1 → Random segment 2 → Random segment 3
- **Expansion Result (Day 1):** Intro → SpongeBob S03E12 → SpongeBob S02E08 → SpongeBob S04E05
- **Expansion Result (Day 2):** Intro → SpongeBob S01E15 → SpongeBob S05E03 → SpongeBob S02E20 (different selection)

**Use Case:** Flexible programming blocks where content selection varies but structure remains consistent. The structure and rules are fixed, but the actual asset selections change with each expansion.

## Contract / Interface

VirtualAsset defines:

- **Virtual asset identity**: Unique identifier for the virtual asset container
- **Type**: Fixed sequence or rule-based definition
- **Asset references**: For fixed sequences, ordered list of Asset UUIDs or selection rules
- **Rules**: For rule-based definitions, JSON rules specifying asset selection criteria
- **Playout hints**: Optional playout directives that control how assets are played:
  - `shuffle`: Randomize the order of assets in the container
  - `sequential`: Play assets in the defined order
  - `conditional_inserts`: Conditionally insert assets based on criteria (e.g., rating slates inserted before content based on rating)
- **Expansion behavior**: How the virtual asset expands to concrete assets during resolution
- **Reusability**: Can be referenced across multiple schedule plans

VirtualAssets are referenced in [Program](Program.md) asset chains as nodes in the linked list. Programs are placed in Zones within SchedulePlans. The same VirtualAsset can be referenced in multiple Programs and Plans, enabling cross-plan reuse.

## Execution Model

VirtualAssets are **SchedulableAsset** subclasses that exist only at **design/planning time**. They are treated identically to regular Assets during schedule planning but **expand to physical Assets at playlist generation**. The expansion process converts VirtualAssets into concrete Asset references that can be played. VirtualAssets do not exist in the runtime layer (PlaylogEvent or playout stream).

### Design/Planning-Time Behavior

VirtualAssets exist only during schedule planning:

1. **Zone Placement**: VirtualAssets can be placed directly in Zones, just like regular Assets or Programs
2. **Program Asset Chains**: VirtualAssets can be referenced in Program asset chains
3. **Planning-Time Equivalence**: VirtualAssets are indistinguishable from regular Assets during scheduling — they are treated as single units
4. **Template/Composite Wrapper**: VirtualAssets act as templates that reference other assets but are not files themselves

### Playlist Generation (Expansion Point)

When [Playlist](../architecture/Playlist.md) is generated from ScheduleDay:

1. **VirtualAsset Expansion**: VirtualAssets expand into one or more physical Assets
   - **Fixed sequences**: Expand to the predetermined ordered list of Asset UUIDs
   - **Rule-based definitions**: Evaluate rules against the current asset catalog and expand to selected Asset UUIDs
2. **Physical Asset Resolution**: Expanded physical Assets are included in the Playlist with absolute timecodes
3. **Producer Assignment**: Physical Assets feed appropriate Producers (usually AssetProducer)
   - There is no "VirtualProducer" — Producers are output-oriented runtime components
   - VirtualAssets expand to physical Assets which then render through standard Producers

**Critical Rule:** After expansion, VirtualAssets no longer exist. Only the concrete physical Assets remain in the Playlist and subsequent runtime layers (PlaylogEvent, playout stream).

### Expansion Timing

**Playlist Generation (Primary Expansion Point)**

- VirtualAssets expand when [Playlist](../architecture/Playlist.md) is generated from ScheduleDay
- This happens before playout execution, providing resolved physical assets with absolute timecodes
- Fixed sequences expand deterministically to their predefined asset lists
- Rule-based VirtualAssets evaluate rules against the catalog state at playlist generation time
- The expanded Asset references are stored in the Playlist, ready for playout
- **VirtualAssets do not exist in PlaylogEvent or the playout stream** — only physical Assets remain

**Why Playlist Generation:**

- Provides resolved physical assets with absolute timecodes for playout
- Allows VirtualAssets to remain as SchedulableAssets in ScheduleDay (immutable planning layer)
- Enables expansion logic to access current catalog state at playout time
- Supports both fixed sequences and dynamic rule-based selections
- Ensures VirtualAssets exist only at design/planning time, not in runtime

## Relationship to Programs

VirtualAssets can be referenced in Program asset chains. Programs are SchedulableAssets that contain an `asset_chain` (linked list of SchedulableAsset IDs), and VirtualAssets can be included in those chains.

**Key Points:**

- Programs contain VirtualAsset references in their `asset_chain`, not the expanded assets
- The VirtualAsset is a SchedulableAsset that will be expanded later during playlist generation
- Programs define what content should play, but not when (that's determined by Zones)
- **Reusability**: The same VirtualAsset can be referenced in multiple Programs and Zones, allowing operators to define once and use many times

## Relationship to ScheduleDay

When [ScheduleDay](ScheduleDay.md) is generated from a plan containing VirtualAssets, **VirtualAssets remain as SchedulableAssets** in the ScheduleDay. They are not expanded at ScheduleDay time — expansion occurs later at playlist generation.

**ScheduleDay Process:**

- VirtualAssets are placed in ScheduleDay as SchedulableAssets (just like regular Assets or Programs)
- ScheduleDay contains VirtualAsset references, not expanded assets
- VirtualAssets are treated identically to regular Assets during scheduling
- Expansion to physical Assets occurs at playlist generation time

See [ScheduleDay](ScheduleDay.md) for details on how schedule days are generated and how VirtualAssets fit into the scheduling process.

## Relationship to Playlist and PlaylogEvent

When [Playlist](../architecture/Playlist.md) is generated from ScheduleDay, **VirtualAssets expand to physical Assets**. The Playlist contains resolved physical assets with absolute timecodes, ready for playout. **VirtualAssets do not exist in PlaylogEvent or the playout stream** — only physical Assets remain after expansion.

**Playlist Generation:**

- VirtualAssets in ScheduleDay expand into one or more physical Assets
- Each expanded asset becomes a separate entry in the Playlist with absolute timecodes
- Timing and sequencing from the VirtualAsset expansion are preserved in the Playlist
- **Playlist contains concrete Asset UUIDs, not VirtualAsset references**
- **VirtualAssets no longer exist after expansion** — they are design/planning-time entities only

**PlaylogEvent and Runtime:**

- PlaylogEvents are generated from Playlists and contain only physical Asset references
- **VirtualAssets do not exist in PlaylogEvent or the playout stream**
- Only the concrete physical Assets that resulted from VirtualAsset expansion are present in runtime layers
- VirtualAssets exist only at design/planning time, not in the runtime layer

**Producer Assignment:**

- Physical Assets from VirtualAsset expansion feed appropriate Producers (usually AssetProducer)
- There is no "VirtualProducer" — Producers are output-oriented runtime components
- VirtualAssets expand to physical Assets which then render through standard Producers

See [Playlist](../architecture/Playlist.md) for details on how playlists are generated and how VirtualAsset expansion fits into the playout process.

## Examples

### Example 1: "Movie of the Day" - Rule-Based Selection from Pool

**VirtualAsset Definition:**

A VirtualAsset that acts as a template selecting one movie from a pool of eligible films each day. This demonstrates how a VirtualAsset references other assets but is not itself a file.

```yaml
name: "Movie of the Day"
type: "rule_based"
description: "Selects one movie from the classic movies pool each day"
rules:
  selection:
    pool: "classic-movies-collection-uuid"
    count: 1
    method: "random"
  constraints:
    duration_min_ms: 5400000 # 90 minutes
    duration_max_ms: 7200000 # 120 minutes
    exclude_recent_days: 30 # Avoid movies aired in last 30 days
    tags:
      - "classic"
      - "feature-film"
  fixed_components:
    - position: "before"
      asset_uuid: "branded-intro-uuid"
    - position: "after"
      asset_uuid: "station-outro-uuid"
```

**JSON representation:**

```json
{
  "id": "880e8400-e29b-41d4-a716-446655440003",
  "name": "Movie of the Day",
  "type": "rule_based",
  "description": "Selects one movie from the classic movies pool each day",
  "rules": {
    "selection": {
      "pool": "classic-movies-collection-uuid",
      "count": 1,
      "method": "random"
    },
    "constraints": {
      "duration_min_ms": 5400000,
      "duration_max_ms": 7200000,
      "exclude_recent_days": 30,
      "tags": ["classic", "feature-film"]
    },
    "fixed_components": [
      {
        "position": "before",
        "asset_uuid": "branded-intro-uuid"
      },
      {
        "position": "after",
        "asset_uuid": "station-outro-uuid"
      }
    ]
  }
}
```

**Usage in SchedulePlan:**

The VirtualAsset is placed in a Zone or referenced in a Program asset chain:

```json
{
  "zone_name": "Late Night",
  "start_time": "22:00",
  "end_time": "24:00",
  "schedulable_assets": ["880e8400-e29b-41d4-a716-446655440003"]
}
```

**Expansion at Playlist Generation:**

When the Playlist is generated from ScheduleDay, the VirtualAsset dynamically resolves to concrete Assets:

- **Day 1**: Intro → `asset-uuid-500` (Casablanca, 102 min) → Outro
- **Day 2**: Intro → `asset-uuid-523` (The Maltese Falcon, 100 min) → Outro
- **Day 3**: Intro → `asset-uuid-487` (Citizen Kane, 119 min) → Outro

**Key Point:** The VirtualAsset is a template that exists only at design/planning time. It references a pool of assets and rules for selection, but is not itself a file. When instantiated in a Playlist, it resolves to specific physical Assets.

### Example 2: "Cartoon Marathon" - Multi-Asset Selection from Pool

**VirtualAsset Definition:**

A VirtualAsset that selects multiple cartoon episodes from a collection, creating a themed block that varies each time it's scheduled.

```yaml
name: "Cartoon Marathon"
type: "rule_based"
description: "Selects 3-4 cartoon episodes for a themed marathon block"
rules:
  selection:
    pool: "cartoon-collection-uuid"
    count: 4
    method: "random"
  constraints:
    duration_min_ms: 1320000 # 22 minutes
    duration_max_ms: 1440000 # 24 minutes
    exclude_recent_days: 7
    tags:
      - "cartoon"
      - "animated"
  fixed_components:
    - position: "before"
      asset_uuid: "cartoon-intro-uuid"
    - position: "after"
      asset_uuid: "cartoon-outro-uuid"
  playout_hints:
    shuffle: true
```

**Expansion at Playlist Generation:**

- **Day 1**: Intro → 4 randomly selected cartoon episodes (shuffled) → Outro
- **Day 2**: Intro → 4 different randomly selected cartoon episodes (shuffled) → Outro

**Key Point:** This VirtualAsset demonstrates how a composite wrapper can select multiple assets from a pool, apply constraints, and include fixed components (intro/outro) while varying the main content.

### Example 3: Fixed Sequence - Branded Episode Block

**VirtualAsset Definition:**

- Name: `branded-episode-block`
- Type: **Fixed sequence** (deterministic expansion)
- Sequence:
  1. Branded intro (`branded-intro-2024.mp4`) — fixed Asset UUID
  2. Episode (selected from series based on episode policy) — may vary per expansion
  3. Station bumper (`station-bumper.mp4`) — fixed Asset UUID

**Usage in Program asset chain:**

```json
{
  "name": "Branded Episode Block",
  "play_mode": "sequential",
  "asset_chain": ["branded-episode-block-virtual-asset-uuid"]
}
```

**Expansion at Playlist Generation:**
When the [Playlist](../architecture/Playlist.md) is generated from ScheduleDay, the VirtualAsset expands:

- **Intro**: `asset-uuid-1` (branded-intro-2024.mp4) — always the same
- **Episode**: `asset-uuid-2` (Cheers S01E05, selected based on episode policy for this date)
- **Bumper**: `asset-uuid-3` (station-bumper.mp4) — always the same

The expanded assets are stored in the Playlist with absolute timecodes. Physical Assets feed AssetProducer for playout.

**Key Point:** The VirtualAsset expands to physical Assets at playlist generation. Only the concrete Asset references remain in the Playlist.

### Example 2: Rule-Based - Morning Cartoon Block (Intro + 2 Random SpongeBob Shorts)

**VirtualAsset Definition:**

- Name: `morning-cartoon-block`
- Type: **Rule-based** (non-deterministic expansion)
- Description: **Reusable container** of asset references and logic — "intro + 2 random SpongeBob shorts"
- Rules:
  - Add branded intro at start (fixed Asset UUID)
  - Select 2 random SpongeBob segments from catalog
  - Each segment must be 10-12 minutes duration
  - Total duration: ~25 minutes
  - Avoid segments that aired in the last 7 days
- **Playout hints**: `shuffle` (randomize SpongeBob segment order)
- **Reusability**: Can be reused across multiple schedule plans (e.g., weekday morning plan, weekend morning plan)

**Usage in Zone or Program asset chain:**
VirtualAsset can be placed directly in a Zone or referenced in a Program asset chain.

**Expansion at Playlist Generation (Day 1):**
When the [Playlist](../architecture/Playlist.md) is generated for Monday, the VirtualAsset expands:

- **Intro**: `asset-uuid-1` (branded-intro-2024.mp4) — always the same
- **Segment 1**: `asset-uuid-10` (SpongeBob S03E12, randomly selected, 11 min)
- **Segment 2**: `asset-uuid-15` (SpongeBob S02E08, randomly selected, 10 min)
- **Segment 3**: `asset-uuid-22` (SpongeBob S04E05, randomly selected, 12 min)

**Expansion at Playlist Generation (Day 2):**
When the [Playlist](../architecture/Playlist.md) is generated for Tuesday, the VirtualAsset expands differently:

- **Intro**: `asset-uuid-1` (branded-intro-2024.mp4) — always the same
- **Segment 1**: `asset-uuid-18` (SpongeBob S01E15, randomly selected, 11 min) — different from Day 1
- **Segment 2**: `asset-uuid-25` (SpongeBob S05E03, randomly selected, 10 min) — different from Day 1
- **Segment 3**: `asset-uuid-31` (SpongeBob S02E20, randomly selected, 12 min) — different from Day 1

**Key Point:** The same VirtualAsset expands to different assets each day because it's rule-based. The rules are evaluated fresh against the catalog state at playlist generation time.

### Example 3: Fixed Sequence - Commercial Pod Structure

**VirtualAsset Definition:**

- Name: `prime-time-commercial-pod`
- Type: **Fixed sequence** (deterministic expansion)
- Sequence:
  1. Station ID bumper (`station-id-2024.mp4`) — fixed Asset UUID
  2. Commercial slot 1 (selected from ad library based on rotation policy)
  3. Commercial slot 2 (selected from ad library based on rotation policy)
  4. Commercial slot 3 (selected from ad library based on rotation policy)
  5. Return bumper (`return-bumper.mp4`) — fixed Asset UUID

**Usage in [Program](Program.md) placed in Zone:**
The Program's asset_chain includes the VirtualAsset as a node:

```json
{
  "asset_chain": [
    {
      "schedulable_asset_id": "770e8400-e29b-41d4-a716-446655440002",
      "asset_type": "virtual_asset",
      "next_id": null
    }
  ]
}
```

The Zone controls timing and duration (e.g., Zone 20:00-23:00). The VirtualAsset expands at playlist generation.

**Expansion at Playlist Generation:**
The VirtualAsset expands to a fixed structure with some dynamic components:

- **Station ID**: `asset-uuid-100` (station-id-2024.mp4) — always the same
- **Commercial 1**: `asset-uuid-201` (selected from ad library rotation)
- **Commercial 2**: `asset-uuid-205` (selected from ad library rotation)
- **Commercial 3**: `asset-uuid-198` (selected from ad library rotation)
- **Return Bumper**: `asset-uuid-101` (return-bumper.mp4) — always the same

**Key Point:** Even though commercials are selected dynamically, the structure (bumper → 3 ads → bumper) is fixed. This is a fixed sequence with dynamic components.

### Example 4: Rule-Based - Late Night Movie Block

**VirtualAsset Definition:**

- Name: `late-night-movie-block`
- Type: **Rule-based** (non-deterministic expansion)
- Rules:
  - Select 1 random movie from "Classic Movies" collection
  - Duration must be 90-120 minutes
  - Add branded intro at start (fixed Asset UUID)
  - Add station outro at end (fixed Asset UUID)
  - Avoid movies that aired in the last 30 days
  - Prefer movies with "classic" genre tag

**Usage in [Program](Program.md) placed in Zone:**
The Program's asset_chain includes the VirtualAsset as a node:

```json
{
  "asset_chain": [
    {
      "schedulable_asset_id": "880e8400-e29b-41d4-a716-446655440003",
      "asset_type": "virtual_asset",
      "next_id": null
    }
  ]
}
```

The Zone controls timing and duration (e.g., Zone 22:00-24:00). The VirtualAsset expands at playlist generation.

**Expansion at Playlist Generation (Day 1):**

- **Intro**: `asset-uuid-1` (branded-intro-2024.mp4) — always the same
- **Movie**: `asset-uuid-500` (Casablanca, 102 min, randomly selected from eligible movies)
- **Outro**: `asset-uuid-2` (station-outro.mp4) — always the same

**Expansion at Playlist Generation (Day 2):**

- **Intro**: `asset-uuid-1` (branded-intro-2024.mp4) — always the same
- **Movie**: `asset-uuid-523` (The Maltese Falcon, 100 min, randomly selected, different from Day 1)
- **Outro**: `asset-uuid-2` (station-outro.mp4) — always the same

**Key Point:** The structure (intro → movie → outro) is consistent, but the movie selection varies based on rules evaluated at expansion time.

### Example 5: Conditional Inserts - Rating Slates

**VirtualAsset Definition:**

- Name: `prime-time-block-with-rating-slates`
- Type: **Rule-based** (with conditional inserts)
- Description: **Reusable container** of asset references and logic with conditional inserts
- Rules:
  - Select 1 prime-time episode from eligible series
  - Duration must be 42-44 minutes
  - Add branded intro at start (fixed Asset UUID)
  - Add station outro at end (fixed Asset UUID)
- **Playout hints**:
  - `sequential`: Play in defined order (intro → episode → outro)
  - `conditional_inserts`: Insert rating slate before episode if content rating is PG-13 or R
    - Rating slate asset: `pg13-rating-slate.mp4` (inserted if rating is PG-13)
    - Rating slate asset: `r-rating-slate.mp4` (inserted if rating is R)
- **Reusability**: Can be reused across multiple schedule plans (e.g., weekday prime-time plan, weekend prime-time plan)

**Usage in [Program](Program.md) placed in Zone:**
The Program's asset_chain includes the VirtualAsset as a node:

```json
{
  "asset_chain": [
    {
      "schedulable_asset_id": "990e8400-e29b-41d4-a716-446655440004",
      "asset_type": "virtual_asset",
      "next_id": null
    }
  ]
}
```

The Zone controls timing and duration (e.g., Zone 20:00-20:45). The VirtualAsset expands at playlist generation.

**Expansion at Playlist Generation (Episode with PG-13 rating):**

- **Intro**: `asset-uuid-1` (branded-intro-2024.mp4) — always the same
- **Rating Slate**: `asset-uuid-300` (pg13-rating-slate.mp4) — conditionally inserted based on content rating
- **Episode**: `asset-uuid-600` (Drama Series S02E05, PG-13 rated, 43 min)
- **Outro**: `asset-uuid-2` (station-outro.mp4) — always the same

**Expansion at Playlist Generation (Episode with TV-PG rating):**

- **Intro**: `asset-uuid-1` (branded-intro-2024.mp4) — always the same
- **Episode**: `asset-uuid-605` (Comedy Series S01E12, TV-PG rated, 42 min) — no rating slate inserted
- **Outro**: `asset-uuid-2` (station-outro.mp4) — always the same

**Key Point:** Conditional inserts allow VirtualAssets to dynamically insert assets (like rating slates) based on content metadata or other criteria, while maintaining the reusable container structure across multiple schedule plans.

## Benefits

VirtualAssets provide several benefits:

1. **Reusability**: Define once, use many times across multiple schedule plans and ScheduleDay entries
2. **Modularity**: Package related assets into reusable bundles of asset references and logic
3. **Consistency**: Ensure consistent branding and packaging across programming
4. **Flexibility**: Support both fixed sequences and dynamic rule-based selections
5. **Playout control**: Support playout hints like shuffle, sequential, and conditional inserts (e.g., rating slates)
6. **Abstraction**: Reference complex asset combinations as a single unit in schedule plans
7. **Maintainability**: Update VirtualAsset definitions to affect all references across all plans

## Implementation Considerations

**Future Implementation Notes:**

- VirtualAssets will require a persistence model (table or JSON storage)
- Expansion logic will need to handle both fixed sequences and rule-based definitions
- Rule evaluation will need access to asset catalog for selection
- Timing calculations must account for variable-duration rule-based selections
- Validation must ensure VirtualAssets expand to valid Asset references
- **Playout hints support**: Implementation must support playout directives like shuffle, sequential, and conditional inserts (e.g., rating slates inserted based on content rating)
- **Cross-plan reuse**: VirtualAssets must be designed to be reusable across multiple schedule plans without duplication

## Out of Scope (MVP)

VirtualAssets are not part of the initial MVP release. The following are deferred:

- VirtualAsset persistence and management
- Fixed sequence VirtualAsset support
- Rule-based VirtualAsset support
- VirtualAsset expansion during ScheduleDay resolution
- VirtualAsset expansion during PlaylogEvent generation
- VirtualAsset CLI commands and operator workflows

## See Also

- [Asset](Asset.md) - Atomic unit of broadcastable content (what VirtualAssets contain)
- [SchedulePlan](SchedulePlan.md) - Top-level operator-created plans that define channel programming
- [Program](Program.md) - SchedulableAsset type that is a linked list of SchedulableAssets (can reference VirtualAssets in asset chains)
- [ScheduleDay](ScheduleDay.md) - Resolved schedules for specific channel and date (VirtualAssets remain as SchedulableAssets in ScheduleDay)
- [Playlist](../architecture/Playlist.md) - Resolved pre–AsRun list of physical assets (VirtualAssets expand here)
- [PlaylogEvent](PlaylogEvent.md) - Runtime execution plan aligned to MasterClock (derived from Playlist containing resolved assets from VirtualAssets)
- [Scheduling](Scheduling.md) - High-level scheduling system

**Note:** VirtualAsset is a future feature that enables packaging and re-use of modular asset bundles. A VirtualAsset is a **SchedulableAsset** subclass that acts as a template or composite wrapper referencing other assets, but is not itself a file. VirtualAssets are reusable containers of asset references and logic (e.g., "Movie of the Day" or "Cartoon Marathon") that can be reused across multiple schedule plans. VirtualAssets support playout hints like shuffle, sequential, and conditional inserts (e.g., rating slates). **VirtualAssets exist only at design/planning time** — they are used during schedule planning and expand to actual physical Assets when Playlists are generated from ScheduleDays. After expansion, only the concrete Asset references remain in Playlists and PlaylogEvent records. VirtualAssets do not exist in the runtime layer (PlaylogEvent or playout stream).
