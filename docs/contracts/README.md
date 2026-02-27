# Contracts (Authoritative)

This directory is the **only canonical source of runtime guarantees** for playout.

## Canonical taxonomy
- **Laws**: non-negotiable “physics” of the system. If a law conflicts with anything else, the law wins.
- **Invariants**: testable, enforceable runtime guarantees. Every invariant MUST list required contract tests.
- **Diagnostics**: observability-only rules (logs/metrics), not correctness by themselves.
- **Legacy**: archived docs kept for archaeology only. Not authoritative.

## Navigation
- Laws: `docs/contracts/laws/`
- Invariants:
  - AIR: `docs/contracts/invariants/air/`
  - Core: `docs/contracts/invariants/core/`
  - Sink: `docs/contracts/invariants/sink/`
  - Shared: `docs/contracts/invariants/shared/`
- Component contracts (interface and behavior specifications):
  - `docs/contracts/core/` — Core subsystem contracts (execution interface, horizon management, runway, transmission log, etc.)
- Domain authority documents (glossary, pipeline model, authority vocabulary):
  - `docs/domains/` — Domain-level reference documents (HorizonManager, ScheduleManager, PlaylistEventExecution, etc.)
## Test labels: contract (CI) vs soak (nightly)

- **contract** — Default in CI. All contract tests have this label; long-running tests are excluded by also being marked **soak**.
- **soak** — Long-running tests (real media, long timeouts). Run nightly only; excluded from CI. Every soak test MUST have a **fast deterministic counterpart** that validates the same invariant(s) via simulated time (fake clock, tick/fence advancement, no wall-clock sleep).

**Core (pytest):** Tests under `pkg/core/tests/contracts/` are auto-marked `contract`. Mark long-running tests with `@pytest.mark.soak`. CI runs: `pytest tests/contracts -m "contract and not soak"`.

**AIR (ctest):** Tests have CTest label `contract`; soak tests have label `soak` only. CI runs: `ctest --test-dir pkg/air/build -L contract`. Soak tests (when built with `-DRETROVUE_SOAK_TESTS=1`) run nightly: `ctest -L soak`.

## Rules of the road
1) A contract is **outcomes, not procedures**.  
2) Every invariant MUST list required tests under `tests/contracts/` (or `pkg/*/tests/contracts/`).  
3) Legacy docs are **not** allowed to be referenced by new work.
