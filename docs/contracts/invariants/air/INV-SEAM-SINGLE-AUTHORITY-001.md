# INV-SEAM-SINGLE-AUTHORITY-001 (Seam decisions have one authority)

## Behavioral Guarantee

Seam decisions — arming, firing, disposition selection, commit — MUST originate in SeamController and nowhere else. No other component MUST emit a seam command. Enforcement surfaces execute seam commands SeamController issues; they MUST NOT synthesise alternate seam decisions from contributing signals.

## Authority Model

SeamController is the sole owner of seam-decision state for every declared boundary in the active block plan. Contributing signals — readiness verdicts, per-segment prefill state, buffer-depth predicates, A/V phase, cadence state — inform SeamController's decision; they do not issue commands. The tick-loop enforcement surface (today `PipelineManager`) executes SeamController's commands on the emission path.

## Boundary / Constraint

- Seam commands (swap, pad-bridge engagement, JIP commit) MUST originate in SeamController.
- Contributing signal producers MUST remain non-authoritative with respect to seam decisions — they provide inputs, not commands.
- Enforcement surfaces MUST consume SeamController-issued commands and MUST NOT compute an alternate decision from the same inputs.

## Violation

A seam command emitted from a module other than SeamController; an enforcement surface that computes a seam decision from contributing signals rather than consuming one from SeamController; a contributing signal producer that issues a seam command under any fallback path.

## Derives From

`LAW-SWITCHING`, `LAW-LIVENESS`

## Required Tests

- `runtime/tests/contracts/seam/SeamAuthorityInvariantTests.cpp`

## Enforcement Evidence

TODO
