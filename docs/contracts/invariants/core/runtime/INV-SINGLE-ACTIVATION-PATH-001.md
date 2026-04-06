# INV-SINGLE-ACTIVATION-PATH-001

## Behavioral Guarantee

There is exactly one channel activation entry point: `ProgramDirector.start_channel()`. All consumption adapters (HLS, TS, future protocols) MUST activate channels through this single path. No adapter MUST maintain its own activation registry, active-channel state, or teardown path.

## Authority Model

ProgramDirector owns channel lifecycle. Consumption adapters add viewer-model behavior (phantom session tracking, fanout wiring, activity expiry) but delegate activation and teardown to ProgramDirector exclusively.

## Boundary / Constraint

- HlsConsumptionAdapter and TsConsumptionAdapter MUST call `start_channel()` to activate a channel. They MUST NOT bypass it.
- No adapter MUST directly instantiate a ChannelManager or own its lifecycle.
- No adapter MUST maintain an active-channel registry that diverges from ProgramDirector's registry.
- No adapter MUST implement its own teardown path for channels.
- If a new consumption model is added (e.g. DASH, HLS-LL), it MUST be implemented as a new ConsumptionAdapter subclass. Lifecycle logic MUST NOT be added to ProgramDirector; consumption behavior MUST be added to the adapter.

## Violation

A second activation entry point that bypasses `start_channel()`. An adapter that directly instantiates a ChannelManager. Duplicate active-channel state in an adapter that can diverge from ProgramDirector's registry. Any class that re-implements `start_channel()` logic.

## Derives From

`LAW-RUNTIME-AUTHORITY`, `LAW-LIVENESS`

## Required Tests

- No dedicated contract tests yet. Activation path uniqueness is structurally enforced by the consumption adapter architecture.

## Enforcement Evidence

TODO
