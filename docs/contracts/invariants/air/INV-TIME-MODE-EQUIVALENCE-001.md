# INV-TIME-MODE-EQUIVALENCE-001

## Behavioral Guarantee

All playout timing logic MUST be mode-agnostic with respect to clock implementation.

Real-time and deterministic timing modes MUST produce identical behavioral outcomes for:

- Deadline arithmetic
- Frame index progression
- Seam decisions
- Switch boundary enforcement

Timing mode MUST NOT alter contract semantics.

## Authority Model

`LAW-CLOCK` defines single time authority. This invariant guarantees that multiple timing modes (e.g., real-time and deterministic) are interchangeable implementations of that authority and do not affect playout behavior.

## Boundary / Constraint

Playout timing decisions MUST derive exclusively from the session time authority.

Clock implementation details MUST NOT influence:

- Deadline computation
- Frame index mapping
- Seam timing
- Switch enforcement

Timing mode is an execution detail, not a behavioral variable.

## Violation

Any of the following violates this invariant:

- Behavioral differences between real-time and deterministic timing modes.
- Timing decisions that vary depending on clock implementation.
- Independent time sources influencing playout decisions.

## Derives From

`LAW-CLOCK` — No subsystem may invent, reset, or locally reinterpret time.

## Required Tests

- At least one contract test per timing-sensitive component executed under deterministic timing mode.
- The same playout logic must execute under both timing modes without semantic divergence.

## Enforcement Evidence

- **Interface-level enforcement:** `MasterClock` abstract base (`MasterClock.h`) with `TestMasterClock` and `SystemMasterClock` concrete implementations — all timing-sensitive code depends on the abstract interface, never a concrete clock type.
- **Asset source equivalence:** `IAssetSource` interface shared by `FakeAssetSource` (deterministic) and `RealAssetSource` (real-time) — asset decode paths are mode-agnostic.
- **No mode-conditional branches:** `TimelineController`, `PipelineManager`, and `EncoderPipeline` accept injected clock and asset source; no `if (real_time)` branching exists in timing-sensitive paths.
- Contract tests: `TimelineControllerContractTests.cpp` exercises deadline arithmetic, frame index progression, and seam decisions under deterministic timing. Standalone vs gRPC parity verification (`verify_blockplan_execution.py`) confirms identical per-block execution (152 frames, CT=5016ms for 5s block) across both modes.
