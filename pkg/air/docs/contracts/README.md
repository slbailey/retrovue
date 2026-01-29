# Contracts index

This directory holds the **normative** contracts for the Air playout engine. Contracts define intended behavior, interfaces, and invariants. **If code disagrees with a contract, the code is wrong** — fix the code or change the contract explicitly; do not treat the contract as advisory.

## Normative rule

Contracts in this directory are **authoritative**. They specify what the system must guarantee. Implementation must conform. When implementation and contract conflict, the contract wins until the contract is updated through the normal change process.

---

## Root-level contracts

| Contract | Purpose |
|----------|---------|
| [AirArchitectureReference.md](AirArchitectureReference.md) | Canonical reference for first-class components, gRPC surface, ownership, and directory layout. |
| [build.md](build.md) | Non-negotiable build and codec rules (paths, static FFmpeg, no LD_LIBRARY_PATH). |

---

## Architecture contracts

Index: [architecture/README.md](architecture/README.md)

| Contract | Purpose |
|----------|---------|
| [architecture/PlayoutEngineContract.md](architecture/PlayoutEngineContract.md) | gRPC control plane, rule IDs, and metrics guarantees. |
| [architecture/PlayoutControlContract.md](architecture/PlayoutControlContract.md) | RuntimePhase, bus switching, and valid sequencing. |
| [architecture/PlayoutInstanceAndProgramFormatContract.md](architecture/PlayoutInstanceAndProgramFormatContract.md) | One instance per channel and ProgramFormat lifecycle. |
| [architecture/OutputBusAndOutputSinkContract.md](architecture/OutputBusAndOutputSinkContract.md) | Output signal path, attach/detach, and sink lifecycle. |
| [architecture/RendererContract.md](architecture/RendererContract.md) | ProgramOutput expectations and frame consumption. |
| [architecture/FileProducerContract.md](architecture/FileProducerContract.md) | FileProducer segment params, decode, and frame contract. |
| [architecture/MasterClockContract.md](architecture/MasterClockContract.md) | Timing authority and deadlines. |
| [architecture/MetricsAndTimingContract.md](architecture/MetricsAndTimingContract.md) | Metrics schema and timing enforcement. |
| [architecture/MetricsExportContract.md](architecture/MetricsExportContract.md) | Telemetry export contract. |

---

## Phase contracts (Phase 8)

Index: [phases/README.md](phases/README.md)

| Contract | Purpose |
|----------|---------|
| [phases/Phase8-Overview.md](phases/Phase8-Overview.md) | Phase 8 scope, dependencies, and sub-phases (transport → TS → segment control → switch). |
| [phases/Phase8-0-Transport.md](phases/Phase8-0-Transport.md) | Stream transport (UDS, AttachStream/DetachStream). |
| [phases/Phase8-1-AirOwnsMpegTs.md](phases/Phase8-1-AirOwnsMpegTs.md) | Air owns MPEG-TS output. |
| [phases/Phase8-1-5-FileProducerInternalRefactor.md](phases/Phase8-1-5-FileProducerInternalRefactor.md) | FileProducer internal refactor. |
| [phases/Phase8-2-SegmentControl.md](phases/Phase8-2-SegmentControl.md) | Segment control (seek/stop). |
| [phases/Phase8-3-PreviewSwitchToLive.md](phases/Phase8-3-PreviewSwitchToLive.md) | Preview and SwitchToLive in the TS path. |
| [phases/Phase8-4-PersistentMpegTsMux.md](phases/Phase8-4-PersistentMpegTsMux.md) | Persistent mux and PIDs. |
| [phases/Phase8-5-FanoutTeardown.md](phases/Phase8-5-FanoutTeardown.md) | Fan-out and teardown. |
| [phases/Phase8-6-RealMpegTsE2E.md](phases/Phase8-6-RealMpegTsE2E.md) | Real MPEG-TS end-to-end. |
| [phases/Phase8-7-ImmediateTeardown.md](phases/Phase8-7-ImmediateTeardown.md) | Immediate teardown on last viewer. |
| [phases/Phase8-8-FrameLifecycleAndPlayoutCompletion.md](phases/Phase8-8-FrameLifecycleAndPlayoutCompletion.md) | Frame lifecycle and playout completion. |
| [phases/Phase8-9-AudioVideoUnifiedProducer.md](phases/Phase8-9-AudioVideoUnifiedProducer.md) | Unified audio/video producer. |

---

## See also

- [Overview / doc entry point](../overview/README.md)
- Phase 6A contracts (historical) are in [archive/phases/](../archive/phases/).
