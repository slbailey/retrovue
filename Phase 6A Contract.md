# Phase 6A — Air Execution Contracts

**This contract has been refactored into focused sub-documents under `docs/air/contracts/`.**

| Document | Content |
|----------|---------|
| [Phase6A-Overview.md](docs/air/contracts/Phase6A-Overview.md) | Purpose, scope, deferrals, cross-phase invariants, phase summary, “After Phase 6A” |
| [Phase6A-0-ControlSurface.md](docs/air/contracts/Phase6A-0-ControlSurface.md) | gRPC control surface (StartChannel, LoadPreview, SwitchToLive, StopChannel) |
| [Phase6A-1-ExecutionProducer.md](docs/air/contracts/Phase6A-1-ExecutionProducer.md) | ExecutionProducer interface, preview/live slots, stop semantics |
| [Phase6A-2-FileBackedProducer.md](docs/air/contracts/Phase6A-2-FileBackedProducer.md) | Minimal FileBackedProducer (ffmpeg, start_offset_ms, hard_stop_time_ms) |
| [Phase6A-3-ProgrammaticProducer.md](docs/air/contracts/Phase6A-3-ProgrammaticProducer.md) | ProgrammaticProducer (synthetic frames, heterogeneous producers) |

All technical requirements, semantics, and exit criteria are defined in the linked documents. No content was removed in the refactor.
