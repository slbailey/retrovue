# Architecture contracts

**Purpose:** Standing contracts that define the **architecture** of the Air playout engine: first-class components, interfaces, ownership, and invariants. These are the canonical specifications for how the system is structured; the codebase is the source of truth, and these docs define the intended design.

**Use when:** Designing, reviewing, or implementing changes that touch PlayoutEngine, OutputBus, ProgramFormat, ProgramOutput, producers, or control flow. Start with [Air Architecture Reference](../../architecture/AirArchitectureReference.md) for the component list, then drill into the contract that applies.

## Contents

| Contract | Scope |
|----------|--------|
| [PlayoutEngineContract](PlayoutEngineContract.md) | gRPC control plane, rule IDs, metrics guarantees. |
| [PlayoutControlDomainContract](PlayoutControlDomainContract.md) | RuntimePhase, bus switching, valid sequencing. |
| [PlayoutInstanceAndProgramFormatContract](PlayoutInstanceAndProgramFormatContract.md) | One instance per channel, ProgramFormat lifecycle. |
| [OutputBusAndOutputSinkContract](OutputBusAndOutputSinkContract.md) | Output signal path, attach/detach, sink lifecycle. |
| [RendererContract](RendererContract.md) | ProgramOutput (headless/preview), frame consumption. |
| [FileProducerDomainContract](FileProducerDomainContract.md) | FileProducer segment params, decode, frame contract. |
| [MasterClockDomainContract](MasterClockDomainContract.md) | Timing authority, deadlines. |
| [MetricsAndTimingContract](MetricsAndTimingContract.md) | Metrics schema, timing enforcement. |
| [MetricsExportDomainContract](MetricsExportDomainContract.md) | Telemetry export contract. |

## See also

- [Air Architecture Reference](../../architecture/AirArchitectureReference.md) — First-class components and boundaries (reference contract).
- [Development phase contracts](../phases/README.md) — Phase 6A, Phase 8 (milestone-specific).
