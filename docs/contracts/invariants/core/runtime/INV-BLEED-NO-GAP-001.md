# INV-BLEED-NO-GAP-001 — Bleed compaction produces contiguous grid-aligned output

Status: Invariant
Authority Level: Planning
Derived From: `LAW-LIVENESS`, `LAW-GRID`

## Purpose

When `allow_bleed` causes a program block to extend past its declared window, the compiler MUST resolve the overlap by compacting — pushing subsequent blocks forward to the bleed block's grid-aligned end. Without compaction, consecutive marathon blocks with bleed create time gaps that violate `LAW-LIVENESS` (continuous emission) and produce padded dead air.

## Guarantee

The schedule compiler MUST emit a strictly contiguous, non-overlapping, grid-aligned sequence of `ProgramBlockOutput` blocks covering the full compilation horizon `[range_start, range_end)`. Bleed overlaps MUST be resolved by compaction (pushing subsequent blocks forward), not by pruning (dropping overlapped blocks).

## Preconditions

- Input blocks are produced by DSL compilation (`_compile_episode_block`, `_compile_movie_marathon`, etc.).
- All `start_at` values MUST be timezone-aware with zero UTC offset (`utcoffset() == timedelta(0)`). Non-UTC or naive timestamps are architectural violations.
- All `start_at` values MUST be grid-aligned: `int(start_at.timestamp()) % (grid_minutes * 60) == 0`.
- All `slot_duration_sec` values MUST be multiples of `grid_minutes * 60`.

## Observability

- A validation pass MUST run before and after compaction asserting grid alignment.
- Fully enclosed blocks (`block.end_at() <= prev.end_at()`) MUST raise `CompileError`.
- Gaps between consecutive blocks MUST raise `CompileError`.
- Non-UTC or naive `start_at` MUST raise `CompileError`.
- Blocks not covering `[range_start, range_end)` MUST raise `CompileError`.

## Deterministic Testability

Construct two consecutive `movie_marathon` blocks with `allow_bleed: true` where marathon 1 bleeds past its boundary. Verify: (1) no gaps between blocks, (2) marathon 2's first block starts at marathon 1's last block end, (3) all blocks are grid-aligned, (4) fully enclosed overlaps raise, (5) gaps raise, (6) non-UTC timestamps raise, (7) blocks spanning broadcast-day boundaries are not split.

## Failure Semantics

Planning fault. `CompileError` raised at compile time. No schedule emitted.

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_bleed_no_gap.py`

## Enforcement Evidence

TODO
