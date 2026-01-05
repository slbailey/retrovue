# RetroVue Layer Boundaries & Architecture

> **The definitive guide to RetroVue's internal architecture**  
> Layer boundaries, import rules, and the separation of concerns that protect broadcast correctness.

---

## Overview

RetroVue simulates a **linear broadcast TV network** with strict architectural boundaries that enforce:

- **Operator Control**: Only approved content can air
- **Scheduling Discipline**: Time-based planning follows broadcast rules
- **Runtime Safety**: Playback cannot bypass approval gates

### Core Principle

> **Nothing crosses layer boundaries without permission.**

The system is intentionally layered so that:

1. **Operators** (via CLI) define what the station is allowed to air
2. **Scheduling logic** plans what will air and when
3. **Runtime logic** actually plays it out for viewers

## Domain Separation

RetroVue enforces a strict separation between two domains:

### Library Domain

- **Owns**: Media discovery, ingest, enrichment, QC, review
- **Tracks**: Episodes, seasons, titles, sources, provider_refs, file metadata, technical metadata, markers, duration, etc.
- **Operator Interface**: `retrovue assets ...`
- **Authority**: Can nominate media for air, but does not schedule anything
- **Forbidden**: Does NOT define channels, templates, schedules, or playlogs

### Broadcast Domain

- **Owns**: Channel policy, dayparting rules, broadcast-day assignment, airable catalog ("what the station is cleared to run"), and playlog_event
- **Operator Interface**:
  - `retrovue channel ...`
  - `retrovue template ...`
  - `retrovue schedule ...`
  - `retrovue catalog ...`
- **Authority**: ScheduleService and runtime consume this domain to generate and execute playout

**Critical Rule**: The Library Domain and Broadcast Domain are now physically separated in Postgres and enforced by Alembic. The Library Domain no longer owns scheduling or playout structures.

**Data Flow**: Library Domain → promotion → Broadcast Domain → ScheduleService → Runtime

---

## Layer Map

```
retrovue/
├── cli/              # Operator commands and tooling
├── infra/            # Write-path: configuration, DB session mgmt, admin services
├── schedule_manager/ # Scheduling brain: builds playout and EPG horizons
├── runtime/          # Playout execution, channel orchestration
└── domain/           # Content/ingest domain models and enrichment logic
```

Each layer has a specific job and strict limits.

## Layer Responsibilities

### 1. CLI Layer (`retrovue/cli/`)

**Purpose:** Operator interface and configuration management.

#### **WHAT**

- Typer commands exposed as `retrovue ...`
- Configuration and inspection tools
- Operator approval workflows

#### **Commands**

- `retrovue channel add` - Create channels
- `retrovue template add` - Create scheduling templates
- `retrovue template block add` - Define time blocks
- `retrovue schedule assign` - Assign templates to channels
- `retrovue asset add/update/list` - Manage content assets
- Existing ingest/review commands

#### **WHAT IT CAN DO**

- ✅ Collect user/operator intent
- ✅ Call `infra.admin_services` to mutate configuration
- ✅ Print status, dump tables, sanity checks
- ✅ Approve content for broadcast (`canonical=true`)

#### **WHAT IT CANNOT DO**

- ❌ Directly talk to database sessions
- ❌ Generate scheduling horizons or playout plans
- ❌ Spawn playback pipelines
- ❌ Run the station (CLI configures, doesn't operate)

> **CLI does not "run the station." CLI configures the station.**

### 2. Infrastructure Layer (`retrovue/infra/`)

**Purpose:** System configuration write-path and database management.

#### **WHAT**

- Database session/engine helpers (`infra/db.py`)
- Admin services for infrastructure table mutations (`infra/admin_services.py`)
- Configuration persistence and validation

#### **Admin Services**

- `ChannelAdminService.create_channel(...)`
- `TemplateAdminService.create_template(...)`
- `TemplateAdminService.add_block(...)`
- `ScheduleAdminService.assign_template_for_day(...)`
- `AssetAdminService.add_asset(...)`
- `AssetAdminService.update_asset(...)`
- `AssetAdminService.list_assets(...)`

#### **WHAT IT CAN DO**

- ✅ Open database sessions
- ✅ Insert/update rows in infrastructure tables:
  - `channel`
  - `template`
  - `template_block`
  - `schedule_day`
  - `asset`
- ✅ Enforce business rules (canonical gating)
- ✅ Validate configuration integrity

#### **WHAT IT CANNOT DO**

- ❌ Generate playlogs
- ❌ Decide what airs "right now"
- ❌ Start or control playout pipelines
- ❌ Bypass canonical approval
- ❌ Mark unreviewed media as airable

> **Infra is the only layer (besides CLI) allowed to write infrastructure tables. Everyone else treats those tables as read-only.**

### 3. Schedule Manager Layer (`retrovue/schedule_manager/`)

**Purpose:** Scheduling brain that builds playout and EPG horizons.

#### **WHAT**

- **`schedule_manager/models.py`** - ORM models for:
  - `Channel`
  - `Template`
  - `TemplateBlock`
  - `ScheduleDay`
  - `Asset` (broadcast-facing, canonical approval gating)
  - `PlaylogEvent` (what will air / what aired)
- **`schedule_manager/schedule_service.py`** - Content selection and timeline layout
- **`schedule_manager/schedule_orchestrator.py`** - Daemon that keeps horizons extended
- **`schedule_manager/rules.py`** - Interprets `rule_json` from TemplateBlock

#### **WHAT IT CAN DO**

- ✅ Read infrastructure tables (read-only)
- ✅ Compute broadcast day boundaries (e.g. 06:00 → 06:00 local)
- ✅ Handle grid slotting (30-minute blocks, optional offset)
- ✅ Generate per-channel playout/EPG horizons
- ✅ Create `playlog_event` rows (near-term playout horizon)
- ✅ Answer "what should be airing right now?" with offsets

#### **WHAT IT CANNOT DO**

- ❌ Change channel configuration
- ❌ Change template definitions
- ❌ Approve or reject assets
- ❌ Modify `asset.canonical`
- ❌ Touch ingest pipeline data
- ❌ Create channels, assets, templates, etc.

> **ScheduleService is read-only on infrastructure and writes only to runtime schedule tables (`playlog_event`).**

### 4. Runtime Layer (`retrovue/runtime/`)

**Purpose:** Execution and playout control.

#### **WHAT**

- **ChannelManager** - Per-channel runtime controller
- **ProgramDirector** - Global system coordinator
- **MasterClock** - Centralized time authority
- **AsRunLogger** - Playback logging
- **Producer orchestration** - FFmpeg pipeline setup, emergency mode, guide channel mode

#### **WHAT IT CAN DO**

- ✅ Ask ScheduleService "what's airing right now + offset?"
- ✅ Spin up Producer when first viewer tunes in
- ✅ Tear down Producer when last viewer leaves
- ✅ Log what actually aired (to AsRun)
- ✅ Handle emergency mode and guide channels

#### **WHAT IT CANNOT DO**

- ❌ Write to infrastructure tables (`channel`, `template`, `asset`, etc.)
- ❌ Approve new media for broadcast
- ❌ Change core scheduling math (grid size, rollover)
- ❌ Bypass canonical gating
- ❌ Air non-canonical content

> **Runtime's job is to make the station look live, not to invent programming.**

### 5. Library Domain (`retrovue/domain/`)

**Purpose:** Content ingestion, review, enrichment, and metadata management.

#### **WHAT**

- Media coming from Plex / filesystem / TMM
- Tag extraction and metadata normalization
- Duration, chapters → ad breaks
- Human or automated review before "safe to air"
- Content warehouse + QC

#### **WHAT IT CAN DO**

- ✅ Pull from external sources
- ✅ Normalize and enrich metadata
- ✅ Track review state
- ✅ Process content for broadcast readiness
- ✅ Nominate content for promotion to Broadcast Domain

#### **WHAT IT CANNOT DO**

- ❌ Mark something canonical for on-air use by itself
- ❌ Directly tell ScheduleService what to schedule
- ❌ Directly drive runtime playout
- ❌ Bypass operator approval
- ❌ Define channels, templates, schedules, or playlogs
- ❌ Own scheduling or playout structures

> **This layer feeds the Broadcast Domain through promotion, but does not become infrastructure automatically.**

## Promotion Workflow: Library → Broadcast Catalog

The Library Domain discovers, ingests, enriches, and reviews media. Once an operator decides "this can air," they run `retrovue assets promote`. Promotion writes a new row into `catalog_asset` in the Broadcast Domain. That row includes:

- title (guide-facing)
- duration_ms (used by scheduler math)
- tags (used to satisfy template_block rule_json)
- file_path (what ChannelManager will actually playout)
- canonical (if true, it's allowed on air)
- source_ingest_asset_id (for provenance / audit)

After promotion, ScheduleService may consider that CatalogAsset when filling a schedule block. If canonical=false, it's visible to operators but still forbidden to air.

**Critical Rules:**

- **ScheduleService is forbidden** to schedule any CatalogAsset with canonical=false.
- **Runtime / ChannelManager is forbidden** to playout any CatalogAsset with canonical=false.

---

## Import Rules & Dependencies

> **This is the contract that prevents architectural drift.**

### Allowed Imports

| Layer                | Can Import From                                                                   |
| -------------------- | --------------------------------------------------------------------------------- |
| **CLI**              | `infra`, `schedule_manager`, `domain`                                             |
| **Infra**            | `schedule_manager.models`, `domain`, `infra.db`                                   |
| **Schedule Manager** | `schedule_manager.models`, `infra.db` (read-only), `runtime.master_clock`         |
| **Runtime**          | `schedule_manager` (read-only), `schedule_manager.models`, `runtime.master_clock` |
| **Domain**           | None (stays clean; lowest layer, no upward dependencies)                          |

### Forbidden Imports

> **These violations break the architectural contract:**

- **Runtime** ❌ must NOT import `infra.admin_services`
- **Runtime** ❌ must NOT import `infra/db` for writes
- **Schedule Manager** ❌ must NOT call `infra.admin_services` to create/modify channels, templates, assets
- **Infra** ❌ must NOT import `runtime` (infra is configuration, not live playout)
- **CLI** ❌ must NOT import `runtime` to "start playback" (CLI is configuration, not on-air control)

> **If you violate these, you're letting the wrong layer mutate or shortcut authority.**

---

## Canonical Gating (Non-Negotiable Rule)

> **Only assets with `canonical=true` in the Broadcast Domain `catalog_asset` table are eligible for scheduling.**

### The Rule

- **ScheduleService** must refuse to schedule non-canonical assets
- **Runtime** must refuse to play non-canonical assets
- **Only operators** can approve content for broadcast

### The Only Path to Canonical

```
Library Domain: retrovue assets promote
    ↓
Promotion creates catalog_asset in Broadcast Domain
    ↓
Database write with canonical=true
```

### What's Forbidden

- **ScheduleService** ❌ forbidden from promoting content to canonical
- **Runtime** ❌ forbidden from promoting content to canonical
- **Library Domain** ❌ forbidden from promoting content to canonical automatically
- **Library Domain** ❌ forbidden from writing to Broadcast Domain tables directly

> **That separation is how we protect on-air quality.**

## Schema Migration Note (critical)

- The tables `channels`, `templates`, `template_blocks`, `schedule_days`, and `playlog_events` have been removed.
- Those tables used to live in the Library Domain.
- They have been replaced by the Broadcast Domain tables:
  `broadcast_channel`, `broadcast_template`, `broadcast_template_block`, `broadcast_schedule_day`, `catalog_asset`, and `broadcast_playlog_event`.
- This is enforced by Alembic migration `68fecbe0ea79`.
- Do not reintroduce scheduling tables into the Library Domain.

---

## Broadcast Discipline

### Time Math Authority

- **Schedule Manager** owns time math: grid size, grid offset, and 06:00→06:00 broadcast day rollover
- **Runtime** must obey that math and is forbidden from redefining "what day is it?" or "where does the block start?"
- **MasterClock** is the only approved source of "now"
- **ProgramDirector** can set global mode (normal/emergency/guide), but cannot rewrite scheduling policy

### Why This Matters

RetroVue is not "just play files in order."

We are simulating a **TV station**:

1. **Operators** approve what's allowed to air
2. **Schedulers** lay down a believable grid and future horizon
3. **Runtime** makes it look and feel like a live channel when you tune in

**Nobody is allowed to silently skip these steps.**

> **If we follow these boundaries in code, the illusion holds, the system scales, and you never wake up to something airing that you didn't sign off on.**

---

## Deferred Integrations

### Plex Path Mapping & Catalog File Resolution (Deferred Implementation)

> **Status:** Deferred  
> **Priority:** Medium – required before runtime playout reaches production  
> **Scope:** Cross-domain integration (Library → Broadcast)

RetroVue currently assumes that `catalog_asset.file_path` already points to a valid, locally playable file.  
Ingest assets sourced from Plex use Plex's virtual path structure (e.g., `/library/tvshows/...`).  
A future **Path Mapping Service** will translate these paths to RetroVue's local playout paths during promotion.

**Design intent:**

- Each Plex library defines a mapping pair (`root_path` → `local_path`).
- When `retrovue assets promote` runs, it must resolve the ingest asset's Plex path through this mapping to produce the local playout path.
- The resolved path is stored in `catalog_asset.file_path`.
- Validation must confirm that the resolved file exists before allowing promotion.

**Sync considerations:**

- Plex libraries marked `sync_enabled` are scanned nightly.
- When a Plex asset is deleted or moved:
  - The Library Domain marks it `soft_deleted=true`.
  - The Broadcast Catalog must be notified (via webhook or nightly reconciliation) to mark related `catalog_asset` records `available=false` and `canonical=false`.

**Deferred tasks:**

1. Introduce a `path_mapping` table or configuration per library.
2. Implement `PathResolver.resolve()` helper.
3. Add `available` boolean to `catalog_asset`.
4. Create ingest→catalog invalidation job or webhook listener.
5. Add unit test: promotion fails if resolved path does not exist.

---

_This document serves as the architectural foundation for RetroVue's development and maintenance._

_Last updated: 2025-01-24_
