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
## Rules of the road
1) A contract is **outcomes, not procedures**.  
2) Every invariant MUST list required tests under `tests/contracts/` (or `pkg/*/tests/contracts/`).  
3) Legacy docs are **not** allowed to be referenced by new work.
