> **Replaced:** The authoritative repository layout lives in [`../standards/repository-conventions.md`](../standards/repository-conventions.md). This document remains as historical background.

# 📁 Project Structure & Allowed Patterns

**Purpose**  
Keep Cursor (and your future self) from inventing unnecessary new layers each time a feature is added.

---

## 1. `src/retrovue/domain/`

<details>
<summary><strong>What lives here</strong></summary>

- Domain models that map to actual persistence (SQLAlchemy models)
- Domain enums and shared types
- Domain-level relationships (e.g. `Source`, `Collection`, `Asset`, `Episode`, etc.)
</details>

<details>
<summary><strong>Pattern</strong></summary>

- Anemic domain with SQLAlchemy—models are mostly data, plus a few invariants/checks
- No business orchestration
- No CLI logic
</details>

**Why it exists:**  
This is the source of truth for DB shape. Everything else should import from here when dealing with entities.

---

## 2. `src/retrovue/usecases/`

<details>
<summary><strong>What lives here</strong></summary>

- Thin, contract-driven application functions:  
  e.g. `add_source(...)`, `list_sources(...)`, `discover_collections(...)`, `ingest_collection(...)` *(future)*
- These are functions tests patch.
</details>

<details>
<summary><strong>Pattern</strong></summary>

- Function-first application layer (not classes, not services)
- Each usecase takes a DB session (or UoW) and explicit args
- No framework coupling  
</details>

**Why it exists:**  
Tests in `tests/contracts/...` need a stable import target to mock—this is that target.

---

## 3. `src/retrovue/cli/commands/`

<details>
<summary><strong>What lives here</strong></summary>

- CLI wiring (Typer/click):
  - Parses args
  - Opens a DB session/UoW
  - Calls usecase
  - Formats output exactly as the contract specifies
</details>

<details>
<summary><strong>Pattern</strong></summary>

- Orchestration only—no core logic, query composition, or random SQL here
- Strictly follows contract → test → implement
- Must not invent features silently  
</details>

**Why it exists:**  
The CLI is the user-facing contract. It must remain simple and predictable.

---

## 4. `src/retrovue/infra/`

<details>
<summary><strong>What lives here</strong></summary>

- DB engine/session factory
- Settings/config
- Logging
- Cross-cutting utilities (exceptions, base classes)
</details>

<details>
<summary><strong>Pattern</strong></summary>

- Infrastructure layer—other layers depend on this; it does **not** depend on `cli/`
- DB/UoW is managed here  
</details>

**Why it exists:**  
Keeps environment/runtime concerns out of domain/usecases.

---

## 5. `src/retrovue/runtime/`

<details>
<summary><strong>What lives here</strong></summary>

- Playout / channel / ffmpeg / "station is running" components
- Runtime infrastructure services: MasterClock, ScheduleService, ChannelManager, ProgramDirector, AsRunLogger
</details>

<details>
<summary><strong>Pattern</strong></summary>

- Runtime orchestration—not the same as CLI, not the same as ingest
- Can consume domain data, but isn't where we define domain
- Services that execute during broadcast, not persisted entities
</details>

**Why it exists:**  
This is the "TV side" of your project (database of assets + playout/orchestration logic).

---

## Domain Entities vs Runtime Infrastructure

### Domain Entities (`domain/`)

**What they are**: Business concepts that operators manage and configure. Persisted in the database with CRUD operations.

**Examples**: Channel, Source, Collection, Asset, Enricher, Producer

**Characteristics**:
- Have persistent state in database tables
- Operators create, configure, update, delete through CLI
- CLI commands: `retrovue channel add`, `retrovue source list`, etc.
- Contracts: `{Entity}{Verb}Contract.md` (e.g., `ChannelAddContract.md`)
- Have both CLI and Data contract tests

### Runtime Infrastructure (`runtime/`)

**What they are**: System services that execute during broadcast operation. Not persisted entities—they are infrastructure components.

**Examples**: MasterClock (time authority), ScheduleService (scheduling logic), ChannelManager (playout execution), ProgramDirector (global coordination), AsRunLogger (compliance logging)

**Characteristics**:
- No database persistence—they are services that run
- Operators diagnose and validate, not configure
- CLI commands: `retrovue runtime masterclock` (validation), not `retrovue masterclock add`
- Contracts: `{Component}Contract.md` (e.g., `MasterClockContract.md`)
- Usually have CLI contract tests only (validation/diagnostics, not CRUD)

**Why this distinction matters**:
- **Domain entities** = "What operators configure" (channels, sources, assets)
- **Runtime infrastructure** = "What makes the system run" (time services, schedulers, playout managers)
- CLI reflects this: domain entities get CRUD commands; runtime infrastructure gets diagnostic commands under `retrovue runtime`

---

## 6. `src/retrovue/adapters/` (and friends like `importers/`, `enrichers/`)

<details>
<summary><strong>What lives here</strong></summary>

- Plug-in-like components that interact with Plex, filesystems, enrichers, etc.
</details>

<details>
<summary><strong>Pattern</strong></summary>

- Adapter pattern—stable interface with swappable implementations
- No DB writes originate here  
</details>

**Why it exists:**  
Keeps source-specific logic out of usecases.

---

## 7. `src_legacy/` (or `src/retrovue/_legacy/` if you prefer)

<details>
<summary><strong>What lives here</strong></summary>

- Old `app/`, `content_manager/`, `schedule_manager/`, legacy orchestrators
</details>

<details>
<summary><strong>Pattern</strong></summary>

- Quarantine for legacy code
- New code **must not** depend on it
- Code may be salvaged from here if needed  
</details>

**Why it exists:**  
Ensures no accidental reuse of legacy service patterns.

---

## ❌ What does *not* exist

- No `src/retrovue/repositories/`
- No generic `src/retrovue/services/`
- No random top-level `src/retrovue/app/` reintroduction
- No new top-level directories without explicit approval
