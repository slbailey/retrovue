# INV-CHANNEL-TIMELINE-CONTINUITY-001

## Behavioral Guarantee

Channel timeline position is a **pure function** of exactly three inputs: `channel_epoch`, `TimeAuthority.now()`, and `schedule_definition`. The function `f(channel_epoch, T, schedule) -> (block_id, start_utc_ms, offset_within_block_ms)` MUST return identical output for identical inputs regardless of system history.

Restart events, viewer absence periods, AIR lifecycle events (start, stop, crash), or any other runtime state MUST NOT influence the result.

## Authority Model

Core owns channel timeline computation. The position function accepts no mutable state beyond its three declared inputs. AIR lifecycle, session counters, viewer counts, and decoder state are excluded by construction.

## Boundary / Constraint

The position function MUST NOT read or depend on:

- AIR session start time or session count.
- Viewer count or viewer presence history.
- AIR process lifetime, restart count, or crash state.
- Decoder state, buffer depth, or frame counters.
- Any accumulator, counter, or singleton that persists across invocations.

At any `T = TimeAuthority.now()`:

- `f(channel_epoch, T, schedule)` called before an AIR restart MUST equal `f(channel_epoch, T, schedule)` called after the restart.
- `f(channel_epoch, T, schedule)` called during viewer absence MUST equal `f(channel_epoch, T, schedule)` called during active viewing.
- Two independent instantiations of the position function with identical `(channel_epoch, T, schedule)` MUST return identical results.

## Violation

Any of the following:

- `f(channel_epoch, T, schedule)` returns different results at the same `T` after an AIR lifecycle event.
- `f(channel_epoch, T, schedule)` returns different results at the same `T` after a viewer absence period.
- Position computation reads AIR session state, viewer count, decoder state, or any input not in `{channel_epoch, T, schedule}`.
- Two independent computations with identical inputs produce different outputs.

MUST be logged with fields: `channel_id`, `T`, `channel_epoch`, `expected_position`, `observed_position`, `divergence_trigger` (restart | viewer_absence | session_state).

## Derives From

`LAW-CLOCK` — single authoritative time source. `LAW-TIMELINE` — schedule defines boundary timing, not runtime events.

## Required Tests

- `pkg/core/tests/contracts/test_inv_channel_timeline_continuity.py` (THTC-001: position identical before and after AIR restart at same T)
- `pkg/core/tests/contracts/test_inv_channel_timeline_continuity.py` (THTC-002: position after viewer absence equals f(T2, epoch, schedule) at T2)
- `pkg/core/tests/contracts/test_inv_channel_timeline_continuity.py` (THTC-003: two independent computations with identical inputs yield identical output)
- `pkg/core/tests/contracts/test_inv_channel_timeline_continuity.py` (THTC-004: five restart cycles produce zero cumulative drift)
- `pkg/core/tests/contracts/test_inv_channel_timeline_continuity.py` (THTC-005: restart at programming day boundary yields correct day-2 position)
- `pkg/core/tests/contracts/test_inv_channel_timeline_continuity.py` (THTC-006: 48-step interrupted path equals 48-step uninterrupted path)
- All tests use `DeterministicClock` via `contract_clock` fixture. No real-time waits. Position function is called with explicit `(channel_epoch, T, schedule)` tuples. Observable state: returned `(block_id, start_utc_ms, offset_within_block_ms)`.

## Enforcement Evidence

- **Pure function by construction:** `ChannelStream` (`channel_stream.py`) computes timeline position as `f(channel_epoch, T, schedule)` — the function accepts no mutable state beyond its three declared inputs. AIR lifecycle, session counters, viewer counts, and decoder state are excluded by construction.
- **No runtime state dependency:** `ChannelManager` has no import of AIR session modules; timeline computation is performed in Core without reference to AIR process lifetime, restart count, or crash state.
- **Clock injection:** All contract tests use `DeterministicClock` via `contract_clock` fixture — position computation is deterministic and reproducible with explicit `(channel_epoch, T, schedule)` tuples.
- Dedicated contract test (`test_inv_channel_timeline_continuity.py`) with 6 test cases (THTC-001 through THTC-006: restart invariance, viewer absence, independent computation, cumulative drift, day boundary, interrupted path) is referenced in `## Required Tests` but not yet implemented in the current tree.
