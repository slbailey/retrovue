# Domain: scheduling

## Purpose

Owns **editorial intent** and **derived schedule artifacts**: what could air, on which grid, with traceable derivation and immutability rules for published windows.

## Responsibilities

- Maintain SchedulePlan as editorial authority for schedulable structure.
- Derive and publish ScheduleDay, TransmissionLog, ExecutionEntry sequences, and EPG (as a **display** derivative).
- Materialize **ahead-of-air playlog plan** data (persisted playlist/playlog-plan rows) from the schedule/execution derivation chain—upstream of ChannelManager’s runtime playlog construction (see `entities/playout/playlog.md`).
- Enforce grid alignment, eligibility, gaps/coverage, and derivation traceability per contracts.
- Extend horizons proactively so execution never “runs out of plan” silently.

## What this domain owns

- Editorial scheduling truth (SchedulePlan and its evolution within allowed mutability rules).
- Immutable published daily truth (ScheduleDay) and the execution-facing plan (ExecutionEntry / playlog horizon as contracted).
- EPG **as a derived guide**, not as a runtime control input.

## What this domain does NOT own (critical)

- Frame-accurate playback, encoding, muxing, or real-time pacing (**AIR / playout execution**).
- Channel activation, viewer sessions, HTTP TS/HLS serving (**playout orchestration**).
- Whether a byte stream is continuous on the wire (**AIR + delivery**).
- Raw media files on disk or importer connectivity (**ingest**).

## Boundaries vs other domains

| Adjacent domain | Boundary |
|-----------------|----------|
| **playout** | Planning produces **execution plan + playlog/event horizon** (see truth chain in `domains/playout.md`). Playout **consumes** that spine; **playlist-shaped** artifacts are convenience only. Playout must not rebuild schedule math at runtime to “fix” gaps. |
| **ingest** | Scheduling reasons over **eligible** assets; it does not discover or probe files. |
| **systems** | Laws and cross-cutting INV-* constrain how scheduling and playout interact; scheduling does not redefine those rules. |

## Key entities (slugs)

`schedule-plan`, `schedule-day`, `zone`, `channel`, `program`, `execution-entry`, `transmission-log`, `epg`

## Key services (slugs)

`playlist-schedule-manager` (concrete playlist producer today; architectural “traffic / schedule manager” role is broader—see ambiguities).

## Key invariants (IDs)

`INV-SCHEDULEMANAGER-NO-AIR-ACCESS-001` (planning must not talk to AIR)

See RetroVue `docs/contracts/INVARIANTS.md` for the full scheduling family (grid, derivation, immutability, breaks, traffic, EPG, horizon).
