You are working in the RetroVue monorepo.

RetroVue is a retro linear television simulation platform.
It is architected as multiple cooperating components with strict boundaries.
No single component “is” RetroVue — RetroVue emerges from their interaction.

This repository contains:
- Core (Python): orchestration, persistence, scheduling, and runtime supervision
- AIR (C++): real-time single-channel playout engine

Do not collapse responsibilities between components.
Do not invent shared abstractions that bypass documented boundaries.

────────────────────────
HIGH-LEVEL PURPOSE
────────────────────────
RetroVue exists to simulate a believable, always-on, multi-channel linear TV network while minimizing wasted compute.

Key goals:
- Channels appear 24×7 to viewers
- Content follows real broadcast-style scheduling rules
- Viewers may join mid-program
- Compute is consumed only when viewers exist
- Runtime playout is deterministic and reproducible

RetroVue models how *real broadcast stations* operate, not how modern VOD apps behave.

────────────────────────
SYSTEM SHAPE
────────────────────────
RetroVue is intentionally split:

[ Operator / Scheduler / Orchestrator ]
              |
              v
          Core (Python)
              |
              v
     AIR (C++ Playout Engine)
              |
              v
        MPEG-TS Bytes → Viewers

Each layer has exclusive ownership of specific concerns.

────────────────────────
COMPONENT RESPONSIBILITIES
────────────────────────

Core (pkg/core):
- Persistent domain truth (Postgres)
- Ingest pipelines (Importer → Asset)
- Scheduling and grid logic
- EPG and playlog horizon generation
- Playout plan generation at “now”
- Runtime orchestration (ProgramDirector, ChannelManager)
- Operator CLI and contracts
- As-run logging
- HTTP serving of channel MPEG-TS streams
- Supervises and spawns AIR

AIR (pkg/air):
- Real-time execution correctness
- Frame timing and pacing
- Producer switching (preview ↔ live)
- Buffering and backpressure
- Encoding, muxing, and transport
- gRPC control surface
- Telemetry and metrics
- Exactly one active playout session at a time

AIR does NOT know about:
- Schedules
- EPG
- Zones
- Editorial intent
- Multi-channel orchestration

Core does NOT perform:
- Frame decoding
- Encoding
- Muxing
- Real-time pacing

────────────────────────
TRUTH OWNERSHIP (CRITICAL)
────────────────────────
- Editorial truth lives in Core.
- Runtime execution truth lives in AIR.
- Historical truth lives in Core.
- Time authority is explicit in each component’s contracts.

Never persist runtime-derived data back into Core unless explicitly documented.
Never infer editorial intent inside AIR.

────────────────────────
CHANNEL MODEL (SYSTEM-WIDE)
────────────────────────
- Channels are persistent logical entities owned by Core.
- Channels have schedules that advance with wall clock even when not viewed.
- When a viewer tunes in:
  - Core determines what should be airing *now*
  - Core generates a playout plan with offsets
  - Core starts AIR for that channel if needed
  - AIR begins emitting bytes at the correct offset
- Multiple viewers share the same playout instance per channel.
- When the last viewer leaves, playout stops — the channel timeline does not.

────────────────────────
TIME MODEL
────────────────────────
- Wall clock is authoritative for scheduling.
- Core advances schedules regardless of viewers.
- AIR enforces real-time pacing once started.
- No rewind, DVR, or catch-up unless explicitly designed.

────────────────────────
INTERFACES BETWEEN COMPONENTS
────────────────────────
Core → AIR:
- gRPC (internal only)
- Core controls lifecycle and playout plans.
- AIR enforces execution.

Core → Viewers:
- HTTP MPEG-TS streams
- M3U channel list

AIR → Viewers:
- Never directly exposed.

────────────────────────
REPOSITORY DISCIPLINE
────────────────────────
- pkg/core and pkg/air are separate subsystems.
- Changes must respect subsystem boundaries.
- Cross-cutting changes must be reasoned about at the system level first.

If a change affects:
- scheduling → Core
- runtime execution → AIR
- both → treat as a coordinated change with explicit contracts

────────────────────────
CODE CHANGE PROTOCOL (MANDATORY)
────────────────────────
NEVER make code changes without following this protocol. No exceptions.

1) Identify the violated invariant or the missing invariant.
   - If no existing invariant covers the behavior, draft a new one.
   - If an existing invariant is violated, cite it by ID.
2) Write a test that proves the violation (or proves the missing guarantee).
   - The test MUST fail before the code change.
   - The test validates the invariant, not the implementation.
3) Implement the code change to flip the test green.
   - Only after the test exists and the failure is proven.
4) Verify the test is green and no regressions exist.

This is contracts-first, test-driven development. Code changes that skip
steps 1–2 are not allowed — even if the fix is “obvious.” The test is the
proof that the invariant holds. Without the proof, the fix is unverified.

────────────────────────
HOW TO THINK ABOUT CHANGES
────────────────────────
When asked “add X to RetroVue”:

1) Decide which component owns the behavior:
   - Core (editorial, scheduling, orchestration)
   - AIR (runtime execution)
2) If both are involved:
   - Define the contract between them first
   - Do not leak concepts across the boundary
3) Update documentation/contracts before code
4) Preserve invariants of both systems
5) Avoid introducing shared state or shortcut APIs

If X does not clearly belong to either Core or AIR, stop and propose a new system-level contract instead of guessing.

────────────────────────
AUTHORITATIVE DOCUMENTS
────────────────────────
- pkg/core/CLAUDE.md → Core ontology and rules
- pkg/air/CLAUDE.md  → AIR ontology and rules
- each entity (core/air) contains a docs/contracts/    → Binding behavioral contracts

These documents define “what is allowed”.
Implementation must conform.

────────────────────────
ACKNOWLEDGEMENT
────────────────────────
Confirm understanding of RetroVue as a multi-component broadcast simulation platform with strict separation between editorial orchestration (Core) and runtime playout execution (AIR).
Do not proceed until this model is accepted.
