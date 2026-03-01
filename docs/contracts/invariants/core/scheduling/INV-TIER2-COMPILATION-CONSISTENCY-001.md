# INV-TIER2-COMPILATION-CONSISTENCY-001 — Time-to-block resolution uses current compilation exclusively

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-DERIVATION`, `LAW-RUNTIME-AUTHORITY`

## Purpose

Protects `LAW-DERIVATION` and `LAW-RUNTIME-AUTHORITY` by ensuring that time-to-block resolution always returns blocks from the current in-memory compilation. TransmissionLog MUST NOT participate in time resolution. Its sole role is to answer: "Do we have a filled version of block_id X?" When stale TransmissionLog entries from a prior compilation survive, time-range queries against TransmissionLog can return blocks from different compilations, breaking contiguity and causing seed-phase failures.

## Guarantee

`get_block_at(channel_id, utc_ms)` MUST resolve time to a block using the current in-memory compilation (`self._blocks`). TransmissionLog MUST be queried by `block_id` only, never by time range, during block resolution.

## Preconditions

- `DslScheduleService` has compiled at least one broadcast day into `self._blocks`.
- TransmissionLog may contain entries from prior compilations for the same channel and time range.

## Observability

Two consecutive `get_block_at()` calls return blocks where `block_a.end_utc_ms != block_b.start_utc_ms` despite `block_b` being requested at `block_a.end_utc_ms`. The contiguity violation is observable as a seed-phase exception in `ChannelManager`.

## Deterministic Testability

Compile schedule C1, persist TransmissionLog entries from C1. Recompile to C2 (different block timings). Load C2 blocks into in-memory list. Call `get_block_at(t)` then `get_block_at(block_a.end_utc_ms)`. Both blocks MUST come from C2. `block_a.end_utc_ms == block_b.start_utc_ms` MUST hold.

## Failure Semantics

**Runtime fault.** Stale TransmissionLog entries corrupt block resolution, producing non-contiguous blocks that fail the seed-phase contiguity check.

## Required Tests

- `pkg/core/tests/contracts/scheduling/test_inv_tier2_compilation_consistency.py`

## Enforcement Evidence

TODO
