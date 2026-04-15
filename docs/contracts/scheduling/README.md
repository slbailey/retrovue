# Scheduling domain contracts

Authoritative specifications for the **time-splice** scheduling model (MasterClock-based immutability, single active revision per channel, suffix-only compiler output).

| Document | Role |
|----------|------|
| [SCHEDULING-CONTRACT-v1.1.md](SCHEDULING-CONTRACT-v1.1.md) | Editorial timeline, splice semantics, atomic publish, EPG/playlog/playout guarantees |
| [SCHEDULE-PERSISTENCE-DESIGN-v1.0.md](SCHEDULE-PERSISTENCE-DESIGN-v1.0.md) | Postgres tables, writer steps, constraints, transactions, migration from legacy active-per-day |
| [SCHEDULE-COMPILER-RUNTIME-INTEGRATION-v1.0.md](SCHEDULE-COMPILER-RUNTIME-INTEGRATION-v1.0.md) | Compiler `S_new`, `_compile_day` transition, playlog/playout invalidation |

**Invariant (cache / revision monotonicity):** [../invariants/core/scheduling/INV-SCHEDULE-REVISION-MONOTONICITY-001.md](../invariants/core/scheduling/INV-SCHEDULE-REVISION-MONOTONICITY-001.md)

**Related (constitutional scheduling layer, earlier version):** [../scheduling_contract.md](../scheduling_contract.md)
