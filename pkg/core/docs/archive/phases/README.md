# Core phased contracts (historical)

These documents describe **phased delivery** of Core behaviour (Phases 0–5 and 7): clock, grid, SchedulePlan, active item resolver, PlayoutPipeline, ChannelManager, and E2E mock channel acceptance. They are kept for narrative and audit.

**Current normative contracts** live under:

- [../contracts/](../contracts/) — CLI and usecase contracts
- [../scheduling/](../scheduling/) — Scheduling and EPG
- [../runtime/](../runtime/) — ChannelManager, ProgramDirector, AsRun

| Document | Content |
|----------|---------|
| [Phase0-PlayoutRules.md](Phase0-PlayoutRules.md) | Phase 0 playout rules (grid, filler, playlog) |
| [Phase0-ClockContract.md](Phase0-ClockContract.md) | MasterClock, injectable time |
| [Phase1-GridContract.md](Phase1-GridContract.md) | Grid math (30‑min boundaries) |
| [Phase2-SchedulePlanContract.md](Phase2-SchedulePlanContract.md) | Mock SchedulePlan |
| [Phase2.5-AssetMetadataContract.md](Phase2.5-AssetMetadataContract.md) | Asset metadata boundary |
| [Phase3-ActiveItemResolverContract.md](Phase3-ActiveItemResolverContract.md) | Active schedule item resolver |
| [Phase4-PlayoutPipelineContract.md](Phase4-PlayoutPipelineContract.md) | PlayoutPipeline, gRPC mapping |
| [Phase5-ChannelManagerContract.md](Phase5-ChannelManagerContract.md) | ChannelManager timing, prefeed |
| [Phase7-E2EAcceptanceContract.md](Phase7-E2EAcceptanceContract.md) | E2E mock channel acceptance |
