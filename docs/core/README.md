# RetroVue documentation index

RetroVue simulates a 24/7 linear TV network using scheduled content, playout logic, branding, and live ffmpeg output — but only spins real video when someone is actually watching.

This directory is organized by audience and layer.

## Start here (after time away)

- [System component map](../ComponentMap.md) — key components + responsibilities + interfaces (Core + Air).
- [Repo review and roadmap](overview/RepoReviewAndRoadmap.md) — component map + priorities (“what’s next”).
- [Architecture overview](architecture/ArchitectureOverview.md) — system mental model (layers and flow).
- [Contracts index](contracts/resources/README.md) — what the CLI/usecase system guarantees today.
- [Scheduling roadmap](architecture/SchedulingRoadmap.md) — concrete phases for the scheduling pipeline work.

## Status snapshot

- **Done / reliable to build on**:
  - Documentation indexes, architecture model, and the contract/test framework are established.
  - The CLI is treated as a **development/test harness**; contracts should prefer `--json` semantics.
- **In progress / evolving**:
  - Scheduling pipeline implementation follows the documented roadmap; not all phases are complete.
  - Core ↔ Air integration hardening is tracked in the roadmap (versioning, timing alignment, telemetry).
- **Not started (by design)**:
  - Web UI. The plan is for the UI to call the same usecases the CLI calls.

## Architecture

High-level mental model of the system.

- [Architecture overview](architecture/ArchitectureOverview.md)
- [Data flow](architecture/DataFlow.md)
- [System boundaries](architecture/SystemBoundaries.md)
- [Repo review and roadmap](overview/RepoReviewAndRoadmap.md)

## Domain models

Core concepts RetroVue is built on. These define what the system is, not how it runs.

- [Source](domain/Source.md)
- [Enricher](domain/Enricher.md)
- [Playout pipeline](domain/PlayoutPipeline.md)
- [Channel](domain/Channel.md)
- [Scheduling](domain/Scheduling.md) - Scheduling system architecture
- [SchedulePlan](domain/SchedulePlan.md) - Schedule plan domain model
- [Program](domain/Program.md) - Program domain model (linked list of SchedulableAssets)
- [Zone](domain/Zone.md) - Zone domain model (time windows)
- [ScheduleDay](domain/ScheduleDay.md) - Resolved daily schedules
- [Playlist](architecture/Playlist.md) - Resolved pre-AsRun list of physical assets
- [PlaylogEvent](domain/PlaylogEvent.md) - Runtime execution plan

## Runtime

How RetroVue behaves at runtime. ChannelManager, ffmpeg lifecycle, timing.

- [Running the Program Director](runtime/RunningProgramDirector.md) — how to run `program-director start` (Phase 0 A/B, Phase 8.8 note)
- [Channel manager](runtime/channel_manager.md)
- [Producer lifecycle](runtime/ProducerLifecycle.md)
- [MasterClock](domain/MasterClock.md)
- [As-run logging](runtime/asrun_logger.md)

## Operator

How an operator configures and runs the system.

- [Contracts index](contracts/resources/README.md)
- [Operator workflows](operator/OperatorWorkflows.md)

## Developer

How to extend RetroVue safely by adding plugins.

- [Plugin authoring](developer/PluginAuthoring.md)
- [Registry API](developer/RegistryAPI.md)
- [Testing plugins](developer/TestingPlugins.md)

## Methodology

House writing style, collaboration, and testing standards.

- [AI assistant methodology](../standards/ai-assistant-methodology.md)
- [Documentation standards](../standards/documentation-standards.md)
- [Repository conventions](../standards/repository-conventions.md)
- [Test methodology](../standards/test-methodology.md)
- [Glossary](GLOSSARY.md)
