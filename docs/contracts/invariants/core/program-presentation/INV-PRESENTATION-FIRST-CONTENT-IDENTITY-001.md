# INV-PRESENTATION-FIRST-CONTENT-IDENTITY-001 — Editorial identity from first content segment

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` and `LAW-DERIVATION` by ensuring that presentation segments do not corrupt editorial identity resolution. The schedule compiler extracts editorial identity (asset_id, title, episode metadata) from the first `segment_type="content"` segment. If presentation segments used `segment_type="content"`, the compiler would extract branding metadata instead of program metadata.

## Guarantee

Editorial identity resolution MUST use the first segment with `segment_type="content"` as the identity source. Presentation segments MUST use `segment_type="presentation"`, not `"content"`. The primary content segment MUST be the first `segment_type="content"` segment in the block.

## Preconditions

- The block contains at least one segment with `segment_type="content"`.

## Observability

The schedule compiler extracts editorial identity from a presentation segment, or a presentation segment has `segment_type="content"`.

## Deterministic Testability

Assemble a program with 2 presentation segments and 1 content segment. Filter segments by `segment_type=="content"`. Assert the first match is the primary content segment. Assert no presentation segment appears in the filtered list.

## Failure Semantics

**Planning fault.** Wrong editorial identity propagates to EPG, as-run log, and derivation chain.

## Required Tests

- `pkg/core/tests/contracts/test_program_presentation.py`

## Enforcement Evidence

TODO
