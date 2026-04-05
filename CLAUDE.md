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

**Canonical conceptual model:** Source → Container → Locator → Asset → Processor Jobs → Processor Runtime. (Container = subdivision of a Source for discovery; do not use “Collection” in code or docs.)

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
- docs/contracts/    → Canonical behavioral contracts (system-wide)
- docs/contracts/INVARIANTS.md → Single authoritative invariant index
- **docs/KNOWLEDGE_GRAPH.md** → How AI agents must use **`.graph/`** (start at **`.graph/INDEX.md`**) for architecture, boundaries, and graph-first workflow before code

These documents define “what is allowed”.
Implementation must conform.

────────────────────────
DEVELOPMENT CONTRACT
────────────────────────

Truth Model:
- Canonical contracts are the ONLY source of truth.
- Each rule exists exactly once.
- Tests enforce contracts.

Required Workflow (strict order):
1. Update/create the canonical contract
2. Add/update contract tests
3. Then modify implementation code

Prohibited:
- No placeholder documents
- No temporary or “we'll clean later” docs
- No duplicate or alternate invariant IDs
- No parallel rule definitions outside contracts
- No storing rules in comments instead of contracts

Decision Handling:
- Do NOT create CON-* files or deferred-decision records
- Raise conflicts immediately for resolution
- Apply decisions directly to contracts

Documentation Rules:
- Contracts define behavior
- History goes ONLY in docs/contracts/audit/CANONICALIZATION_HISTORY.md
- READMEs are for navigation only (no rules)

Simplicity Rule:
If a change increases the number of places truth can live, it is wrong.

────────────────────────
ACKNOWLEDGEMENT
────────────────────────
Confirm understanding of RetroVue as a multi-component broadcast simulation platform with strict separation between editorial orchestration (Core) and runtime playout execution (AIR).
Do not proceed until this model is accepted.

────────────────────────
GHOST METHOD PROHIBITION (INV-NO-GHOST-METHODS-001)
────────────────────────
No production module may contain unimplemented method stubs.

Forbidden patterns:
- def some_method(self, ...): pass
- def some_method(self, ...): raise NotImplementedError("TODO")
- def some_method(self, ...):  # TODO: implement
- Any method whose entire body is a no-op, pass, or deferred TODO

Rule: If a method is not implemented, do not create it.
Ghost scaffolding creates false API surface, misleads future readers,
and violates INV-NO-GHOST-METHODS-001.

If you need a stub for future work: write the contract test first (RED),
leave it failing, and do not create a method placeholder in production code.

Violating this rule is a contract violation — not a style issue.
Reference invariant: INV-NO-GHOST-METHODS-001 in docs/contracts/INVARIANTS.md

────────────────────────
HLS DELIVERY STACK (INV-HLS-NO-DISK-IO-001)
────────────────────────
There is exactly ONE HLS delivery stack in RetroVue:
  SegmentRing + HlsSegmenter, served at /channels/<id>/live.m3u8

Rules:
- All HLS segment production goes through SegmentRing.
- All HLS manifest generation goes through HlsSegmenter.
- No disk-based HLS (.ts files written to filesystem for serving) is permitted.
- No parallel or alternate HLS delivery path may exist.
- INV-HLS-NO-DISK-IO-001 is a hard constraint: HLS delivery must be in-memory, never disk.

Do NOT re-introduce:
- A second HLS manager or HLS route namespace (e.g. /hls/).
- Disk-based segment caching for HLS delivery.
- Any class named HLSSegmenter, HlsManager, HlsWriter, or similar that duplicates
  SegmentRing + HlsSegmenter responsibilities.

If a change requires a second HLS code path, stop and redesign using the existing stack.

Reference invariant: INV-HLS-NO-DISK-IO-001 in docs/contracts/INVARIANTS.md

────────────────────────
PRODUCTION BOUNDARY RULE (INV-PRODUCTION-BOUNDARY-001)
────────────────────────
Production modules contain only production code.

Rules:
- Mocks, test fixtures, and test harnesses belong in tests/fixtures/, never in runtime/.
- Protocols (abstract interface definitions) belong in retrovue/runtime/protocols.py.
- If a class is only instantiated in tests or behind mock_* flags, it belongs in tests/fixtures/.
- No class named Mock*, Fake*, Stub*, or Test* may live in a production module.

Forbidden patterns:
- class MockXxx in pkg/core/src/retrovue/runtime/*.py
- class MockXxx in pkg/core/src/retrovue/scheduling/*.py
- Any test harness or fixture in a non-test directory

If you need a mock or fake for testing: place it in tests/fixtures/<domain>_fixtures.py.
If you need an abstract interface: place it in retrovue/runtime/protocols.py.

Violating this rule blurs the boundary between production behavior and test behavior,
makes production modules harder to audit, and can cause mocks to silently run in production.

Reference invariant: INV-PRODUCTION-BOUNDARY-001 in docs/contracts/INVARIANTS.md

────────────────────────
CONSUMPTION ADAPTER MODEL (INV-SINGLE-ACTIVATION-PATH-001)
────────────────────────
Channel lifecycle is owned exclusively by ProgramDirector.

Rules:
- There is ONE channel activation entry point: ProgramDirector.start_channel().
- HLS and TS are consumption adapters over the PD-owned lifecycle.
- Consumption adapters add consumption-model behavior (phantom session tracking,
  fanout wiring) but do NOT own or duplicate lifecycle logic.
- Adapters call start_channel() to activate; they do not maintain their own
  activation path, active-channel registry, or teardown path.

Consumption adapters:
- HlsConsumptionAdapter — manages phantom sessions, activity tracking, expiry
- TsConsumptionAdapter — manages raw TS fanout wiring

Forbidden patterns:
- A second activation entry point (e.g. _ensure_channel_active_for_hls() that
  bypasses start_channel())
- An adapter that directly instantiates a ChannelManager or owns its lifecycle
- Duplicate active-channel state in an adapter that diverges from PD's registry
- Any class that re-implements PD.start_channel() logic

If a new consumption model is added (e.g. DASH, HLS-LL): create a new
ConsumptionAdapter subclass. Do not add lifecycle logic to ProgramDirector —
add consumption behavior to the adapter.

Reference invariant: INV-SINGLE-ACTIVATION-PATH-001 in docs/contracts/INVARIANTS.md

────────────────────────
OBSERVABILITY RULE (INV-LIFECYCLE-OBSERVABILITY-001)
────────────────────────
Runtime lifecycle transitions must emit structured log events at DEBUG level.

Rules:
- Every state transition in the channel lifecycle must log a structured event.
  Required transitions: channel activation, first segment produced, viewer join,
  viewer leave, linger start, linger expire, teardown.
- Every viewer session must carry a correlation ID (session_id) that flows end-to-end:
  PD activation → ChannelManager lifecycle → HLS phantom tracking → segments.
- All log lines for a viewer session must include the session_id for traceability.
- Log events must use structured fields (not free-form strings) so they are
  parseable by log aggregators.

Forbidden patterns:
- Lifecycle transitions with no log event (silent state changes are untraceable).
- Viewer session handling that does not propagate a correlation ID.
- Free-form log strings for lifecycle events (use key=value structured fields).
- Log events that omit the session_id when one exists in scope.

Why: Without structured, correlation-ID-tagged events, it is impossible to trace a
viewer session end-to-end through the logs. Debugging production issues becomes
guesswork. Every refactor that touches lifecycle must preserve or extend this
observability, never remove it.

Reference invariant: INV-LIFECYCLE-OBSERVABILITY-001 in docs/contracts/INVARIANTS.md

────────────────────────
AUTHORITY RULE (INV-AUTHORITY-SINGLE-OWNER-001)
────────────────────────
For any change touching runtime behavior, exactly one component must own each concern.

The four authority domains in Retrovue Core:
- Clock/timebase authority → MasterClock (runtime/clock.py)
- Segment window authority → SegmentRing (runtime/hls/segment_ring.py)
- Channel lifecycle authority → ProgramDirector (runtime/program_director.py)
- Diagnostics authority → HlsDiagnosticsState (per-channel, held by PD)

Rules:
- Before making any change, name the authority domain it touches.
- If a change introduces a second decision-maker for any domain, stop and redesign.
- Components may READ from an authority domain. Only the designated owner may WRITE.
- Cross-domain changes must be staged: one domain per PR unless explicitly coordinated.

Forbidden patterns:
- A component other than MasterClock inventing or bypassing wall-clock time for playout decisions.
- A component other than SegmentRing owning the HLS sliding window state.
- A component other than ProgramDirector making teardown decisions.
- Diagnostics state scattered across multiple methods in PD rather than delegated to HlsDiagnosticsState.

Why: Authority overlap is the root cause of "fix one, break three" regression cycles.
When two components can both make the same decision, their state diverges silently.

────────────────────────
COMPLEXITY BUDGET RULE
────────────────────────
Every non-trivial change must justify its net effect on moving parts.

Before implementing any feature or fix, state:
1. What logic is being REMOVED (files, classes, methods, lines)
2. What logic is being ADDED (same)
3. Net moving parts: is the system simpler or more complex after this change?

Rules:
- Net-new abstractions require explicit justification. "We might need this later" is not justification.
- Prefer deletion over layering. If fixing a problem requires adding a new layer, first ask whether an existing layer can be removed.
- If a change touches more than one authority domain, split it into staged changes.
- If a fix requires changes in 3+ components, treat it as an architecture problem first — not a patch.

Forbidden patterns:
- Adding a new class without removing an equivalent amount of complexity elsewhere.
- Creating parallel implementations "just in case" (dual stacks, dual paths, dual authorities).
- Defensive coding that silently handles misconfiguration instead of asserting loudly.

────────────────────────
REQUIRED CHANGE HEADER
────────────────────────
Every non-trivial PR or change set must include this header in its commit message or PR description:

Authority domain touched: [clock | segment-window | lifecycle | diagnostics | http | scheduling | producer | none]
Complexity budget: removed=[X lines/classes] added=[Y lines/classes] net=[simpler/same/more complex]
Contracts affected: [list invariant IDs or "none"]
Rollback unit: [why this change can be reverted independently]

Changes that cannot answer these four questions are not ready to merge.
