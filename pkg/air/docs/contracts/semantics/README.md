# Architecture contracts

**Purpose:** Standing contracts that define the **architecture** of the Air playout engine: first-class components, interfaces, ownership, and invariants. These are the canonical specifications for how the system is structured; the codebase is the source of truth, and these docs define the intended design.

**Use when:** Designing, reviewing, or implementing changes that touch PlayoutEngine, OutputBus, ProgramFormat, ProgramOutput, producers, or control flow. Start with [Air Architecture Reference](AirArchitectureReference.md) for the component list, then drill into the contract that applies.

**Naming:** Contract filenames are `{Subject}Contract.md` (no "Domain" suffix).

## Contents

| Contract | Scope |
|----------|--------|
| [PlayoutEngineContract](PlayoutEngineContract.md) | gRPC control plane, rule IDs, metrics guarantees. |
| [PlayoutControlContract](../architecture/PlayoutControlContract.md) | RuntimePhase, bus switching, valid sequencing. |
| [PlayoutInstanceAndProgramFormatContract](PlayoutInstanceAndProgramFormatContract.md) | One instance per channel, ProgramFormat lifecycle. |
| [ProducerBusContract](../architecture/ProducerBusContract.md) | Input path: ProducerBus (preview + live), producers feed FrameRingBuffer. |
| [BlackFrameProducerContract](../architecture/BlackFrameProducerContract.md) | BlackFrameProducer fallback; sink always receives valid output when live producer runs out. |
| [OutputBusAndOutputSinkContract](../architecture/OutputBusAndOutputSinkContract.md) | Output signal path, attach/detach, sink lifecycle. |
| [OutputContinuityContract](OutputContinuityContract.md) | Output-layer timestamp legality; monotonic PTS/DTS per stream, no regression. |
| [OutputTimingContract](OutputTimingContract.md) | Output-layer real-time delivery discipline; pacing anchor, no early delivery. |
| [RendererContract](RendererContract.md) | ProgramOutput (headless/preview), frame consumption. |
| [FileProducerContract](FileProducerContract.md) | FileProducer segment params, decode, frame contract. |
| [MasterClockContract](MasterClockContract.md) | Timing authority, deadlines. |
| [MetricsAndTimingContract](MetricsAndTimingContract.md) | Metrics schema, timing enforcement. |
| [MetricsExportContract](MetricsExportContract.md) | Telemetry export contract. |

## See also

- [Air Architecture Reference](AirArchitectureReference.md) — First-class components and boundaries (reference contract).
- [Development phase contracts](../phases/README.md) — Phase 6A, Phase 8 (milestone-specific).
