# INV-EPG-READS-CANONICAL-SCHEDULE-001 — EPG reads canonical compiled schedule

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

EPG data MUST be derived from the canonical compiled schedule — the same DB-cached `CompiledProgramLog` that playout uses. If EPG endpoints call `compile_schedule()` directly, they may produce different output than playout (different seeds, different process state), violating `LAW-CONTENT-AUTHORITY` and `LAW-DERIVATION`.

## Guarantee

EPG endpoints MUST read from `CompiledProgramLog` (the DB-cached canonical schedule). EPG endpoints MUST NOT call `compile_schedule()` directly. EPG and playout MUST always agree because they read from the same source.

## Preconditions

- `CompiledProgramLog` MUST store `range_start` and `range_end` columns representing the compilation's actual time coverage.
- A schedule is considered cached for a broadcast day if the canonical store provides a complete overlap-covering set of `ProgramBlockOutput` for that day window.

## Observability

- `get_canonical_epg()` retrieves `ProgramBlockOutput` whose time range overlaps the broadcast-day window via range-based overlap query.
- If no cached schedule covers the requested window, the endpoint MUST return 503 (not recompile).
- No `compile_schedule` call exists in EPG handler code paths.

## Deterministic Testability

Mock `CompiledProgramLog` query. Call `get_canonical_epg(channel_id, window_start, window_end)`. Assert it returns cached `program_blocks` without calling `compile_schedule()`. Verify carry-in blocks from previous days are included via range overlap. Use AST inspection to verify no `compile_schedule` import in EPG handler.

## Failure Semantics

Planning fault. EPG/playout disagreement when EPG recompiles independently.

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_epg_reads_canonical.py`

## Enforcement Evidence

TODO
