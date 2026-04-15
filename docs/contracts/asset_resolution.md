## Overview

Every scheduled block MUST resolve to playable media before playout.
A block that cannot resolve required assets is not safely playable unless it is
explicitly marked degraded.

Asset resolution is a playout-safety boundary. Runtime MUST make resolution
outcomes explicit so operators and downstream systems can distinguish:
- fully playable blocks
- degraded blocks
- hard failures

## Invariants

### 1) Playable block invariant

- A block is valid for playout only if all required assets resolve to playable
  URIs.
- "Playable" means runtime can map each required asset reference to a concrete
  media URI/path suitable for segment execution.

### 2) Strict mode enforcement

- In strict mode, unknown or unresolvable asset IDs MUST fail resolution.
- A block with unresolved required assets MUST NOT be treated as valid.
- Resolution failure MUST propagate as an explicit error.

### 3) Tolerant mode behavior

- In tolerant mode, unknown assets MAY be skipped to keep timeline continuity.
- Any block containing skipped/unresolved required assets MUST be marked as
  degraded/incomplete.
- Degraded state MUST be machine-readable by runtime consumers.

### 4) No silent degradation

- Runtime MUST NOT silently drop unknown/unresolvable assets.
- At least one explicit signal is required:
  - structured log event describing skipped/unresolved assets, and/or
  - degraded marker persisted/returned with the block.

### 5) Playout safety

- A block returned by `get_block_at(...)` MUST be either:
  - fully playable, or
  - explicitly flagged degraded.
- Runtime MUST NOT return a block with unresolved media and no degradation
  indication.

## Failure Conditions

- A block is returned with missing media and no degraded indication.
- Unknown asset IDs are silently skipped in production behavior.
- Strict mode does not fail on unresolved required assets.
- Playout attempts to run unresolved media without explicit degraded state.

## Required Tests

- `tests/contracts/test_asset_resolution.py::test_strict_mode_rejects_unknown_asset`
  - Invariants: Strict mode enforcement; No silent degradation.
- `tests/contracts/test_asset_resolution.py::test_tolerant_mode_allows_unknown_asset`
  - Invariants: Tolerant mode behavior.
- `tests/contracts/test_asset_resolution.py::test_degraded_block_is_flagged`
  - Invariants: Tolerant mode behavior; Playout safety.
- `tests/contracts/test_asset_resolution.py::test_no_silent_skip_emits_degradation_signal`
  - Invariants: No silent degradation; Playout safety.
- `tests/contracts/test_asset_resolution.py::test_playable_block_passes_without_degraded_flag`
  - Invariants: Playable block invariant; Playout safety.
