# Phase Model (Air Contract Taxonomy)

_Related: [Phase 6A Contract](../../pkg/air/docs/contracts/phases/Phase6A-Contract.md) · [Phase 6A Overview](../../pkg/air/docs/archive/phases/Phase6A-Overview.md) · [Playout Engine Contract](../../pkg/air/docs/contracts/architecture/PlayoutEngineContract.md)_

## Purpose

This page defines the phase taxonomy used across Air (C++ playout engine) contracts. Each contract section that is deferred or phased references a phase by name here, so future readers have a single place to answer “why is this deferred?” and “which phase does this belong to?”

---

## Phase Definitions

| Phase | Focus | Scope |
|-------|--------|--------|
| **Phase 6A** | Correctness, control, lifecycle | gRPC control surface (6A.0); ExecutionProducer + preview/live slots (6A.1); minimal FileBackedProducer (6A.2); ProgrammaticProducer (6A.3). No MPEG-TS serving, no Renderer placement, no performance SLAs. |
| **Phase 7** | Media output, TS, renderer, continuity | Real media output path; MPEG-TS serving; Renderer placement; PTS/output continuity; switch seamlessness; metrics pipeline and latency validation. |
| **Phase 8** | Performance SLAs, scale, monitoring | Latency targets (e.g. 2s start, 100ms switch); throughput and scale; formal monitoring and alerting. |
| **Phase 9** | Advanced features | ABR, redundancy, failover, and other advanced broadcast features. |

---

## Summary

- **Phase 6A** = Correctness, control, lifecycle (segment-based legacy preload RPC + legacy switch RPC; no TS/Renderer).
- **Phase 7** = Media output, TS, Renderer, continuity.
- **Phase 8** = Performance SLAs, scale, monitoring.
- **Phase 9** = Advanced features (ABR, redundancy, etc.).

Contracts use the label **Deferred (Applies Phase 7+)** (or the specific phase) when a guarantee is not enforced in 6A but is preserved as future intent.

---

## See Also

- [Phase 6A Contract](../../pkg/air/docs/contracts/phases/Phase6A-Contract.md)
- [Phase 6A Overview](../../pkg/air/docs/archive/phases/Phase6A-Overview.md)
- [Phase 6A.0 Control Surface](../../pkg/air/docs/archive/phases/Phase6A-0-ControlSurface.md)
- [Playout Engine Contract](../../pkg/air/docs/contracts/architecture/PlayoutEngineContract.md)
