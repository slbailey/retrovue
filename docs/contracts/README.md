# Contracts (Authoritative)

This directory is the **only canonical source of runtime guarantees** for playout.

## Canonical taxonomy
- **Laws**: non-negotiable “physics” of the system. If a law conflicts with anything else, the law wins.
- **Invariants**: testable, enforceable runtime guarantees. Every invariant MUST list required contract tests.
- **Diagnostics**: observability-only rules (logs/metrics), not correctness by themselves.
- **Legacy**: archived docs kept for archaeology only. Not authoritative.

## Navigation
- **Terminology (ingest/catalog):** The ingest entity is **Container** (Source → Container → Locator → Media/Asset). See [architecture/TERMINOLOGY_COLLECTION_TO_CONTAINER.md](architecture/TERMINOLOGY_COLLECTION_TO_CONTAINER.md). Only historical migrations and temporary CLI/API compatibility may still use "Collection" for this entity.
- Laws: `docs/contracts/laws/`
- Invariants:
  - AIR: `docs/contracts/invariants/air/`
  - Core: `docs/contracts/invariants/core/`
  - Sink: `docs/contracts/invariants/sink/`
  - Shared: `docs/contracts/invariants/shared/`
- Component contracts (interface and behavior specifications):
  - `docs/contracts/core/` — Core subsystem contracts (execution interface, horizon management, runway, transmission log; catalog: AssetMediaIdentity, CatalogReconciliation, ContainerDiscovery, ProcessorCapability, ProcessorExecution, ProcessorJobQueue, ProcessorMetadata)
  - `docs/contracts/plex/PLEX_COMPATIBILITY_INTERFACE.md` — Plex / HDHomeRun integration (tuner discovery, lineup, guide, artwork)
  - `docs/contracts/xmltv/XMLTV_EXPORT_CONTRACT.md` — XMLTV export (EPG → XMLTV, schedule correctness, lineup consistency)
  - `docs/contracts/epg/EPG_GENERATION_CONTRACT.md` — EPG generation (Schedule → EPG timeline, continuity, determinism)
- Domain authority documents (glossary, pipeline model, authority vocabulary):
  - `docs/domains/` — Domain-level reference documents (HorizonManager, ScheduleManager, PlaylistEventExecution, etc.)
## Test labels: contract (CI) vs soak (nightly)

- **contract** — Default in CI. All contract tests have this label; long-running tests are excluded by also being marked **soak**.
- **soak** — Long-running tests (real media, long timeouts). Run nightly only; excluded from CI. Every soak test MUST have a **fast deterministic counterpart** that validates the same invariant(s) via simulated time (fake clock, tick/fence advancement, no wall-clock sleep).

**Core (pytest):** Tests under `server/tests/contracts/` are auto-marked `contract`. Mark long-running tests with `@pytest.mark.soak`. CI runs: `pytest tests/contracts -m "contract and not soak"`.

**AIR (ctest):** Tests have CTest label `contract`; soak tests have label `soak` only. CI runs: `ctest --test-dir runtime/build -L contract`. Soak tests (when built with `-DRETROVUE_SOAK_TESTS=1`) run nightly: `ctest -L soak`.

## Rules of the road
1) A contract is **outcomes, not procedures**.  
2) Every invariant MUST list required tests under `tests/contracts/` (or `pkg/*/tests/contracts/`).  
3) Legacy docs are **not** allowed to be referenced by new work.

---

## Governance Status Reference (2025-07-14 Canonicalization Pass)

The following status labels appear in contracts and the ledger following the 2025-07-14 governance audit:

| Label | Meaning |
|-------|---------|
| **RETIRED** | Rule was valid but the system it governed has been decommissioned. See cross-reference for replacement. |
| **PARTIALLY-TESTED** | Rule is codified but the test asserting it is skipped or incomplete. |
| **LEGACY-SOURCE** | Rule text originates in a legacy doc; not yet fully migrated to canonical location. |

### Key Changes from the 2025-07-14 Pass

- **LAW-003** marked RETIRED — superseded by Phase 8 BlockPlan model (Phase8DecommissionContract).
- **AIR-012, AIR-015** migrated from legacy → `runtime/docs/contracts/coordination/OutputBusAndOutputSinkContract.md` §11–12.
- **AIR-016** migrated from legacy → `runtime/docs/contracts/coordination/OrchestrationLoopContract.md`.
- **CORE-002, CORE-003** migrated from archive → `server/docs/contracts/resources/ChannelManagerContract.md`.
- **CANONICAL_RULE_LEDGER.md** created at canonical location `docs/contracts/`; root-level file is now a redirect stub.
- **Test anchor backlog** created at `docs/contracts/audit/TEST_ANCHOR_BACKLOG.md`.

### Resolved Conflicts

- **CON-01** (Filler offset mode): LAW-005 RETIRED. Filler always starts at frame 0 (`INV-SCHED-GRID-FILLER-PADDING`).
- **CON-02** (Sink timing clock): AIR-013 RESOLVED. MasterClock governs CT/scheduling; OutputTiming governs delivery pacing independently.
- **CON-03** (LAW-003 retirement): Confirmed. LAW-003 RETIRED (superseded by Phase 8 BlockPlan).
- **CON-04** (LAW-002 test status): LAW-002 rewritten under BlockPlan semantics. `Law002HardStopContractTests.cpp` is canonical enforcement. Legacy test RETIRED.
