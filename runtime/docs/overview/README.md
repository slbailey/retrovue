# Air documentation

## What is Air?

**Air** is the RetroVue playout engine: a **single-channel** native C++ backend that executes segment-based playout instructions from the ChannelManager. It runs one playout session at a time. Channel identity and multi-channel coordination live in Core (Python). Air receives control via gRPC, decodes video/audio (e.g. via FileProducer), stages frames in a lock-free ring buffer, and delivers program output (e.g. via OutputBus to OutputSink). It does not interpret schedules or plans; ChannelManager computes segments and sends exact execution instructions.

## How docs are organized

| Directory | Purpose |
|-----------|---------|
| **overview/** | What Air is and how it fits in RetroVue (this folder). |
| **contracts/** | Authoritative, normative behavior (source of truth). |
| **architecture/** | Signal flow and component relationships (reserved for future content). |
| **runtime/** | How the engine runs (loops, timing, lifecycle). |
| **developer/** | How to build, debug, and extend Air. |
| **operations/** | Integration, telemetry, usage. |
| **archive/** | Historical phases, milestones, and superseded docs. |

## Entry points

- **[Architecture overview](ArchitectureOverview.md)** — How Air fits into RetroVue, design drivers, and system context.
- **[Contracts index](../contracts/architecture/README.md)** — Standing architecture contracts (PlayoutEngine, OutputBus, ProgramFormat, Renderer, FileProducer, timing, metrics). Phase contracts: [Phase 8 index](../contracts/phases/README.md). Reference contract: [Air Architecture Reference](../contracts/AirArchitectureReference.md).
- **[Runtime](../runtime/PlayoutRuntime.md)** — Execution model, threading, timing rules, and failure handling.
- **[Archive](../archive/)** — Historical reference only (see warning below).

## Archive (historical reference only)

**Warning:** Documents under [archive/](../archive/) are kept for historical context only. They describe completed phases, superseded designs, or older naming. Do not use them as authority for current behavior. For current architecture and contracts, use the links above.

Archive contains: AIR_COMPONENT_AUDIT (superseded by Air Architecture Reference), domain narratives (overlapped by contracts), Phase 2/3 milestones, Phase 6A phase contracts, and the roadmap snapshot.

## Other links

- [Project overview](PROJECT_OVERVIEW.md) — Program-level goals and phase summaries.
- [Glossary](GLOSSARY.md) — Canonical terms.
- [Quick Start](../developer/QuickStart.md) — Build and run.
- [Build invariants](../contracts/build.md) — Codec and FFmpeg rules.
- [Integration](../operations/Integration.md) — Deployment and dependencies.
