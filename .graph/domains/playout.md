# Domain: playout

## Purpose

**Runtime orchestration** and **delivery**: turn already-planned execution artifacts into shared per-channel playout and HTTP streams, supervised in Core, executed in AIR.

## Truth chain (broadcast-accurate)

Authoritative order for **what ChannelManager executes**—do not invert or shorten:

**Schedule (editorial + derived days)** → **execution plan** (`execution-entry` / locked execution window) → **playlog / events** (ordered automation list ChannelManager walks) → **`channel-manager`** → **`air-playout-engine`**.

Structures named **playlist** (e.g. contract-shaped lists) are **convenience or transport shapes**, not a parallel source of truth. If present, they must **derive from** the execution plan → playlog spine.

## Responsibilities

- Activate and tear down channels based on viewers (and phantom/HLS rules as contracted).
- Hold **one** activation path into channel lifecycle (`ProgramDirector.start_channel` pattern).
- Supervise **AIR** (spawn, gRPC control, stream attachment): BlockPlan / plan feed as contracted.
- Expose consumption adapters (TS, HLS) without duplicating lifecycle ownership.
- Maintain in-memory HLS segment window + manifest generation (no disk HLS path).

## What this domain owns

- **Core:** lifecycle decisions, correlation IDs for sessions, fanout/adapters, segment ring window authority, manifest generation contract surface, HTTP routes for consumption.
- **AIR:** real-time execution correctness for **one** active session at a time—timing, decode/producer switching, mux, bytes to attached sink.

## What this domain does NOT own (critical)

- Editorial “what should air” truth (**scheduling** / SchedulePlan).
- Deriving ScheduleDay or EPG (**scheduling**).
- EPG-driven playback decisions (**forbidden**; execution plan is sole runtime schedule authority).
- Catalog discovery, probe, or approval (**ingest**).

## Execution boundary: Core vs AIR

| Concern | **Core (this domain, Python orchestration)** | **AIR (C++ engine)** |
|---------|-----------------------------------------------|----------------------|
| Schedule / EPG | Reads execution artifacts only; never uses EPG to choose segments | No schedules, zones, or editorial intent |
| Plan | Builds/feeds **BlockPlan** / plan messages over gRPC from **playlog-derived** execution context | Consumes plan; enforces frames, seams, pacing |
| Time | **MasterClock** (wall clock) for orchestration decisions | Real-time tick loop once session is live |
| Bytes | Owns HTTP sinks, TS fanout, HLS ring + manifest | Produces MPEG-TS into attached stream |
| Truth | Persistent **historical** and **editorial** truth | **Runtime execution** truth only; not persisted back as editorial fact unless explicitly contracted |

**Rule of thumb:** If it requires decoding, frame timing, or mux cadence, it is **AIR**. If it requires “what channel is on” or “start/stop because a viewer arrived,” it is **Core playout orchestration**.

## Boundaries vs other domains

| Adjacent domain | Boundary |
|-----------------|----------|
| **scheduling** | ChannelManager consumes **playlog / execution-window truth** prefetched from planning; it does not extend playlog reactively to compensate for planning gaps. |
| **ingest** | Runtime may require resolved asset paths **already** in the execution stream; no library planning calls from execution hot path. |
| **systems** | Authority and simplicity invariants govern how playout code is structured. |

## Key entities (slugs)

`playlog` (primary consumable for execution), `playlist` (convenience shape only), `segment-ring`, `block-plan`, `playout-instance`

## Key services (slugs)

`program-director`, `channel-manager`, `hls-consumption-adapter`, `ts-consumption-adapter`, `hls-segmenter`, `block-plan-producer`, `playout-session`, `air-playout-engine`

## Key invariants (IDs)

`INV-SINGLE-ACTIVATION-PATH-001`, `INV-CHANNELMANAGER-NO-PLANNING-001`, `INV-EPG-NONAUTHORITATIVE-FOR-PLAYOUT-001`, `INV-HLS-NO-DISK-IO-001`

See RetroVue `docs/contracts/INVARIANTS.md` for HLS segment/ring/manifest and runtime families.
