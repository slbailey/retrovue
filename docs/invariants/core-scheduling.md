# Core Scheduling Invariants

These invariants govern how the scheduling DSL, compiler, and runtime components (ScheduleService, ChannelManager, ProgramDirector) behave. Contracts and tests must enforce these rules before code ships.

1. **ProgramDirector owns lifecycle** – ChannelManagers exist only while referenced by ProgramDirector (no autonomous daemons).
2. **Authoritative time** – ScheduleService queries MasterClock; no component may inject its own notion of "now".
3. **Single playout pipeline** – One ChannelManager → one Air playout pipeline per channel, regardless of viewer count.
4. **DSL purity** – Compiled schedules are deterministic functions of DSL input + asset metadata; no side effects (DB writes, network calls) may occur during compilation.
5. **Explicit packaging** – Every non-program element (rating card, bumper, promo, ad) must be represented as a SchedulableAsset with duration and metadata.
6. **Gap/overlap rejection** – Compiler must fail fast if a broadcast day contains unscheduled time or overlapping segments after applying all decorators.
7. **Commercial policy enforcement** – Break templates define duration + adjacency rules; compiler/tests must ensure no slot violates these constraints before runtime.
8. **Versioned outputs** – Schedule compiler outputs carry schema/version metadata so ScheduleService can validate compatibility.
9. **Playlog transparency** – Each compiled plan must produce a machine-readable Playlog preview (JSON) for operators/tests.
10. **Phase-free runtime** – Invariants and contracts may reference roadmap phases, but runtime code must not include conditional logic keyed to phase numbers.

_Last updated: 2026-02-16_
