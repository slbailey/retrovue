# INV-TIER3-NEXT-BLOCK-IDENTITY-001 — "Coming up next" uses compiled block identity

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring "coming up next" promos reference the actual next program as determined by the compiled block sequence, not an assumed or stale identity. `LAW-DERIVATION` requires that the next-block reference traces to the same compilation that produced the promo segment.

## Guarantee

"Coming up next" MUST reference the next block's program identity as determined by the compiled, compacted block sequence. The identity MUST be resolved during a second pass over `all_blocks` in `compile_schedule()`, after all blocks are compiled and compacted. The last block of a broadcast day MUST NOT produce a "coming up next" segment; this omission is not an error.

## Preconditions

- All blocks in the broadcast day are compiled and compacted.
- The current block is not the last block of the broadcast day.
- The block's template declares a `coming_up_next` entry in `continuity.optional`.

## Observability

A "coming up next" segment references a program identity that does not match `all_blocks[i+1].title`. A "coming up next" segment appears on the last block of a broadcast day.

## Deterministic Testability

Compile a broadcast day with multiple blocks. Inspect the "coming up next" segment on each non-last block. Assert the referenced program identity matches `all_blocks[i+1].title`. Assert the last block has no "coming up next" segment and no compilation error.

## Failure Semantics

**Planning fault.** An incorrect next-block reference misleads the viewer and indicates a compilation ordering error.

## Required Tests

- `pkg/core/tests/contracts/test_block_assembly_tiers.py`

## Enforcement Evidence

TODO
