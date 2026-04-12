# INV-MIDROLL-INTERLEAVE-001 — Midroll filler preserved in compiled segment order

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

`expand_program_block()` produces interleaved content acts and midroll filler segments for network channels. The compile-time segment serializer (`_expand_to_compiled_segments`) MUST preserve this interleaving in `compiled_segments`. Destroying the interleaving collapses all content acts into a single continuous playback with no midroll commercial breaks — a direct violation of `LAW-CONTENT-AUTHORITY` (editorial intent for break placement is lost).

## Guarantee

For network-type channels, `compiled_segments` MUST preserve the relative ordering of content and filler segments produced by `expand_program_block()`. Midroll filler segments (those appearing between content acts) MUST NOT be reordered to trail all content segments.

## Preconditions

- Channel type is `network`.
- `expand_program_block()` produces two or more content segments with interleaved filler.

## Observability

A block whose `compiled_segments` contains all content segments followed by all filler segments when `expand_program_block()` produced interleaved ordering.

## Deterministic Testability

Call `_expand_to_compiled_segments` with a network-type channel and an asset that produces multiple content acts (via chapter markers or algorithmic breaks). Verify that `compiled_segments` contains filler between content entries, not only after.

## Failure Semantics

Planning fault. Midroll breaks are editorially intended; collapsing them into postroll is a scheduling error that propagates to runtime.

## Required Tests

- `server/tests/contracts/test_inv_midroll_interleave.py`

## Enforcement Evidence

TODO
