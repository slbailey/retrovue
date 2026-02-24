# ⚠️ RETIRED — Superseded by BlockPlan Architecture

**See:** [Phase8DecommissionContract.md](../../../../docs/contracts/architecture/Phase8DecommissionContract.md)

This document describes legacy playlist/Phase8 execution and is no longer active.

---

# Phase 6A — Air Execution Contracts

**This contract has been refactored into focused sub-documents under `pkg/air/docs/archive/phases/` (historical).**

| Document | Content |
|----------|---------|
| [Phase6A-Overview.md](../../archive/phases/Phase6A-Overview.md) | Purpose, scope, deferrals, cross-phase invariants, phase summary, "After Phase 6A" |
| [Phase6A-0-ControlSurface.md](../../archive/phases/Phase6A-0-ControlSurface.md) | gRPC control surface (StartChannel, LoadPreview, SwitchToLive, StopChannel) |
| [Phase6A-1-ExecutionProducer.md](../../archive/phases/Phase6A-1-ExecutionProducer.md) | ExecutionProducer interface, preview/live slots, stop semantics |
| [Phase6A-2-FileBackedProducer.md](../../archive/phases/Phase6A-2-FileBackedProducer.md) | Minimal FileBackedProducer (ffmpeg, start_offset_ms, hard_stop_time_ms) |
| [Phase6A-3-ProgrammaticProducer.md](../../archive/phases/Phase6A-3-ProgrammaticProducer.md) | ProgrammaticProducer (synthetic frames, heterogeneous producers) |

All technical requirements, semantics, and exit criteria are defined in the linked documents. No content was removed in the refactor.
