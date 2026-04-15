## Purpose

Define launch-time schedule resolvability for runtime playout.
Runtime MUST be able to resolve the block that covers current time for any
channel with valid schedule coverage at `now`.

## Overview

Channel startup depends on resolving "what is airing now" from schedule
authority. If runtime cannot resolve the block covering `now`, playout fails
before AIR launch and stream requests return unavailable.

This contract defines the required behavior for current-block coverage across
forward-only generation, broadcast-day revision selection, and restart/reload
paths.

## Invariants

### Current-block coverage

- A block is valid for runtime resolution when `start_time <= now < end_time`.
- Runtime MUST NOT exclude a valid block solely because `start_time < now`.

### Forward-only generation with overlap preservation

- Forward-only generation MAY skip blocks fully in the past.
- Forward-only generation MUST preserve blocks that overlap `now`.
- Equivalent rule:
  - Drop only blocks where `end_time <= now`.
  - Preserve blocks where `end_time > now`.

### Launch-time schedule resolvability

- For any channel with schedule coverage at `now`,
  `get_block_at(channel_id, now)` MUST return a block.
- Channel startup MUST NOT fail due to omission of the currently airing block.

### Broadcast-day aware revision resolution

- Runtime schedule lookup MUST NOT assume one active revision per channel.
- Runtime revision selection MUST be compatible with active revisions scoped by
  `(channel_id, broadcast_day)`.

### Restart-safe current coverage

- Restart/preload/reload paths MUST preserve ability to resolve the block
  covering `now`.
- Restart MUST NOT introduce a gap at current time for an already scheduled
  channel.

## Failure conditions

- An in-progress block is omitted only because `start_time < now`.
- `get_block_at(...)` returns `None` while a schedule block overlaps `now`.
- Runtime resolves the wrong revision because it selects first active revision
  per channel without broadcast-day-aware selection.
- Channel startup cannot launch AIR despite valid schedule coverage at `now`.

## Required tests

- `tests/contracts/test_current_block_coverage.py::test_in_progress_block_is_preserved`
  - Invariants: Current-block coverage; Forward-only generation with overlap
    preservation.
- `tests/contracts/test_current_block_coverage.py::test_fully_past_block_is_excluded`
  - Invariants: Forward-only generation with overlap preservation.
- `tests/contracts/test_current_block_coverage.py::test_get_block_at_returns_current_block`
  - Invariants: Launch-time schedule resolvability.
- `tests/contracts/test_current_block_coverage.py::test_runtime_resolution_is_broadcast_day_aware`
  - Invariants: Broadcast-day aware revision resolution.
- `tests/contracts/test_current_block_coverage.py::test_restart_preserves_current_coverage`
  - Invariants: Restart-safe current coverage.
