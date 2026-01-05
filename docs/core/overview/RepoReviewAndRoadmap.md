_Related: [Architecture overview](../architecture/ArchitectureOverview.md) • [Contracts index](../contracts/resources/README.md) • [Scheduling roadmap](../architecture/SchedulingRoadmap.md)_

# Repo review and roadmap (contract-first)

## Purpose

Create a shared, durable understanding of RetroVue’s components, boundaries, and integration points, then
turn that understanding into a contract-first roadmap that avoids brittle coupling.

This document focuses on **outcomes and intent** (what the system guarantees) rather than prescribing
implementation details (how the code must be written).

## Scope

- `retrovue_core/` (Python): CLI, contracts, domain models, scheduling/runtime orchestration.
- `retrovue_air/` (C++): playout engine, renderer pipeline, control plane, and telemetry.
- Cross-repo integrations between the two (proto/API versioning, MasterClock/timing alignment).

## Audience

- Maintainers defining contracts and architecture direction.
- Contributors implementing features without breaking contracts.
- Test authors enforcing contracts without over-constraining implementations.

## Current architecture (high-level)

### Core (Python)

- **Operator surface (CLI)**: `retrovue <noun> <verb>` commands define operator intent and stable outputs.
- **Usecases**: function-first application layer (stable seams for contract tests).
- **Domain**: persistence models + invariants (what exists).
- **Adapters/plugins**: external system integration (importers/enrichers/producers) behind registries.
- **Runtime**: ChannelManager/Producer lifecycle, MasterClock time authority, scheduling services.

Authoritative boundaries are described in:
- [System boundaries](../architecture/SystemBoundaries.md)
- [`ARCHITECTURE.md` layer boundaries](../../ARCHITECTURE.md)

### Air (C++)

- **Control plane**: gRPC surface (`proto/retrovue/playout.proto`) for channel lifecycle operations.
- **Playout pipeline**: decode → frame staging/ring buffer → renderer → MPEG-TS output.
- **Telemetry**: Prometheus metrics surface for state/timing/health.

Authoritative contract: [Playout engine contract](../../../retrovue_air/docs/contracts/PlayoutEngineContract.md).

## Contract philosophy (to reduce brittleness)

### CLI is a test harness, not the product surface

The CLI exists primarily to:
- exercise end-to-end functionality before the web UI exists, and
- provide a convenient manual/contract-test harness during development.

The long-term expectation is that the web UI will call the **same underlying usecases** as the CLI.
Therefore, we avoid treating human-readable CLI text as a stable interface.

### What contracts are for

Contracts exist to define **observable guarantees**:
- CLI command shape and input validation behavior
- Exit codes
- JSON response structure and field semantics
- Operator-facing side effects (e.g., what rows may be written)
- Forbidden side effects (e.g., “no external calls”)
- Cross-component behaviors (e.g., timing alignment rules)

### What contracts should avoid

To keep implementations flexible, contracts should generally avoid:
- Internal function/class names (`get_config_schema()`, “must call function X”)
- Transaction implementation mechanics (“runs in a single transaction”) unless the operator-observable
  behavior depends on it (e.g., atomicity, rollback)
- Exact human-readable formatting guarantees (spacing, line wraps, punctuation). Human output is
  intentionally allowed to evolve as “presentation”.
- Code snippets that look like required implementations (keep as non-normative examples if needed)

### A practical taxonomy

Use this to decide “where a statement belongs”:

- **Operator contract (normative)**: what the CLI guarantees to operators and automation (`--json`).
- **Data contract (normative)**: what persistence side effects occur (and what must not occur).
- **Protocol contract (normative)**: gRPC/proto, metrics names/types, and timing semantics.
- **Architecture guidance (informative)**: recommended seams/layers and non-binding implementation notes.

If a contract contains “how”, either:
- move it to architecture/docs, or
- keep it as an explicitly **non-normative** note (rationale, example, suggested approach).

## Findings (initial)

### Strengths

- **Clear layered architecture exists** (core boundaries + scheduling pipeline docs).
- **Contracts + contract tests are a first-class system** in both repos.
- **Air has strong protocol-level contracts** (gRPC + metrics + state/timing rules) with dedicated tests.

### Brittleness risks (where “how” leaks in)

- **Contracts sometimes encode implementation mechanisms**, not just outcomes:
  - Example: `SourceAddContract.md` references importer interface compliance and schema validation methods.
  - Example: `ProductionSafety.md` includes concrete implementation patterns/code snippets.
- **Tests sometimes over-assert on human-readable output**, which raises churn cost for harmless refactors.
  - Prefer JSON-mode assertions as the canonical surface when available.

### Gaps that block confident evolution

- **Contract taxonomy is not consistently enforced** (operator/data/protocol vs. design notes).
- **Human-output stability policy is mixed** (some contracts imply exact strings; test hardening guidance
  recommends looser assertions).

## Roadmap (contract-first)

### Phase 0: Contract hygiene (short, high leverage)

- **Define and adopt the contract taxonomy** above across core and air.
- **Prefer JSON as the canonical operator contract**:
  - Contracts: mark JSON as “stable; canonical for automation”.
  - Tests: assert structure/semantics in JSON; keep human-output assertions token-based unless explicitly
    frozen.
- **Add a lightweight “contract review checklist”** to contracts (or to a single `CONTRACT_TEST_GUIDELINES.md`)
  and use it in PRs.

Deliverable: a small set of updated “golden” contracts (e.g., SourceList/SourceAdd/PlanBuild) that
demonstrate the pattern and reduce brittleness.

### Phase 1: Scheduling POC (end-to-end outcomes)

Goal: prove the critical broadcast loop works using the documented scheduling pipeline:

SchedulableAsset → ScheduleDay → Playlist → PlaylogEvent → Producer → AsRun

Use the existing plan in:
- [Scheduling system implementation roadmap](../architecture/SchedulingRoadmap.md)

Key outcome contracts to anchor:
- MasterClock semantics (monotonicity, timezone/DST expectations).
- Playlog horizon guarantees (minimum lookahead).
- Viewer join behavior (mid-program offsets derived from MasterClock).

### Phase 2: Core ↔ Air integration hardening

Goal: make the integration contract explicit and resilient:

- gRPC lifecycle rules (idempotency, error recovery, retry/backoff).
- API version bump process and compatibility policy.
- Metrics schema ownership (names/types are stable; values have defined meaning/ranges).

### Phase 3: Production readiness and operator workflows

Goal: tighten operator outcomes and safety:

- Destructive operations follow ProductionSafety consistently (resource-specific rules documented where they
  belong).
- Observability runbooks (what to look at, what “healthy” means).
- Performance and soak testing gates for multi-channel operation.

## Open questions (to resolve early)

- **Which surfaces are “presentation-stable”** (human output) vs “semantically stable” (JSON)?
- **Where should timing authority live** across repos (single source of truth rules, drift tolerances)?
- **What is the minimal end-to-end demo** (one channel, one plan, synthetic assets) that proves the system
  without pulling in external dependencies?

## See also

- [Architecture overview](../architecture/ArchitectureOverview.md) — the system mental model
- [System boundaries](../architecture/SystemBoundaries.md) — “what RetroVue is / is not”
- [Scheduling roadmap](../architecture/SchedulingRoadmap.md) — concrete implementation phases
- [Playout engine contract](../../../retrovue_air/docs/contracts/PlayoutEngineContract.md) — protocol/telemetry guarantees

