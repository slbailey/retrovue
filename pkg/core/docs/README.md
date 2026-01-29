# Core documentation

Entry point for RetroVue **Core** (Python) documentation. Core is the control plane: it handles orchestration, scheduling, and operator-facing behavior. It does not run the playout engine (that is Air); it configures channels, builds schedules, and coordinates when and what to play.

---

## What Core is

- **Control plane** — Core owns channel configuration, schedule plans, and the decision of what should be airing at any moment. The internal playout engine (Air) executes the resulting playout plan.
- **Orchestration** — Core starts and stops playout per channel (e.g. first viewer in → build plan and launch; last viewer out → tear down). It coordinates MasterClock, ScheduleService, ChannelManager, and AsRun logging.
- **Scheduling** — Core builds and maintains the schedule: plans, zones, resolved schedule days, playlist, and playlog. EPG and horizon logic live here.

Operators use the `retrovue` CLI to manage sources, collections, channels, and plans. Nothing runs automatically without operator intent (e.g. ingest is explicit).

---

## How docs are organized

| Directory | Purpose |
|-----------|---------|
| **overview/** | What Core is and how it fits in RetroVue; repo boundaries, roadmap. |
| **contracts/** | Authoritative system contracts: CLI/usecase behavior, guarantees, policies. |
| **architecture/** | System topology, service boundaries, data flow. |
| **scheduling/** | EPG, schedule generation, horizon logic. |
| **runtime/** | Orchestration: daemons, managers, clocks (ChannelManager, ScheduleService, etc.). |
| **data/** | Persistence models, schema, migrations, domain entities, metadata. |
| **developer/** | Build, test, local dev, plugin authoring, contributing. |
| **operations/** | Deployment, operator workflows, configuration. |
| **archive/** | Historical phases, abandoned models, old audits — reference only. |

---

## Entry points

### Architecture overview

High-level system mental model: channels, scheduling, playout, operator surface, and how the layers fit together.

→ [architecture/ArchitectureOverview.md](architecture/ArchitectureOverview.md)

### Contracts index

Authoritative contracts for CLI commands and data behavior. Contract-first reference for implementation and tests.

→ [contracts/resources/README.md](contracts/resources/README.md)

CLI command reference (syntax and routing):

→ [contracts/cli/README.md](contracts/cli/README.md)

### Scheduling docs

Schedule pipeline (plans → days → playlist → playlog), EPG, broadcast-day and horizon logic.

→ [scheduling/SchedulingSystem.md](scheduling/SchedulingSystem.md)  
→ [scheduling/](scheduling/) — Playlist, EPGGeneration, SchedulingRoadmap, scheduling-tags, broadcast_day_alignment.

### Runtime / orchestration docs

ChannelManager, ScheduleService, ProgramDirector, AsRun logging, Producer lifecycle, MasterClock, rule parsers.

→ [runtime/ChannelManager.md](runtime/ChannelManager.md)  
→ [runtime/](runtime/) — AsRunLogging, schedule_service, ProducerLifecycle, Renderer, RunningProgramDirector, rule-parsers.

### Archive

Historical and superseded material only. Not current behavior or design.

→ [archive/](archive/) — Legacy layout, deprecated scheduling models, old schema and CLI docs, phased plans.

---

## Other indexes

- **Data model and domain** — [data/README.md](data/README.md), [data/domain/README.md](data/domain/README.md)
- **Refactoring / mapping** — [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md), [MAPPING_PLAN.md](MAPPING_PLAN.md), [TARGET_STRUCTURE.md](TARGET_STRUCTURE.md)
