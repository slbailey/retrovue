# BlockPlan Layer

This directory contains the **blockplan playout subsystem** for AIR.

## Authoritative Object Model

```
playout_service.cpp
  └─ PipelineManager : IPlayoutExecutionEngine
       ├── OutputClock           (frame-indexed session clock)
       ├── PipelineMetrics       (passive observability)
       ├── live_  : IProducer    (Input Bus A — active producer)
       ├── preview_ : IProducer  (Input Bus B — preloaded next block)
       │        └── TickProducer : IProducer + ITickProducer
       │              └── RealAssetSource (asset probe / duration)
       └── ProducerPreloader     (background A/B swap preparation)
```

## Shared Infrastructure

- **BlockPlanTypes** — `BlockPlan`, `Segment`, `ValidatedBlockPlan`, `FedBlock`
- **BlockPlanValidator** — input validation and CT boundary computation
- **BlockPlanSessionTypes** — `BlockPlanSessionContext`, `FedBlock`

## Contract Tests

All contracts have corresponding tests in:
- `pkg/air/tests/contracts/BlockPlan/`

Run with: `pkg/air/build/blockplan_contract_tests`
