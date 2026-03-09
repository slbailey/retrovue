# INV-BREAK-V2-SINGLE-CHAPTER-001 — V2 single-content blocks honor chapter markers

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Chapter markers are editorial metadata extracted at ingest and stored in the catalog. `LAW-CONTENT-AUTHORITY` requires that editorial metadata drive scheduling decisions. `LAW-DERIVATION` requires that PlaylistEvent be a faithful derivation of ScheduleItem. When the V2 compiled_segments path bypasses chapter-based break detection, PlaylistEvent contains a monolithic content block with all ad fill appended post-content — editorially reinterpreting the program as a movie when it is a network show with act breaks.

## Guarantee

When a V2 `compiled_segments` block contains exactly one content segment and no intro/outro wrapper segments, hydration MUST resolve chapter markers from the `CatalogAssetResolver` and route expansion through `expand_program_block()`. The dedicated break detection stage (`detect_breaks()`) MUST determine break positions. `_hydrate_compiled_segments()` MUST NOT be used for single-content blocks without wrapper segments.

## Preconditions

1. The ScheduleItem carries `compiled_segments` in its metadata.
2. The `compiled_segments` list contains exactly one entry with `segment_type == "content"`.
3. No entries with `segment_type in ("intro", "outro")` are present.

## Observability

A V2 single-content block for a network-type channel whose asset has chapter markers produces a ScheduledBlock with multiple content segments interleaved with filler placeholders. A violation is observable as a single monolithic content segment followed by a single post-content filler.

## Deterministic Testability

Construct a `compiled_segments` list with one content segment. Configure a fake `CatalogAssetResolver` that returns chapter markers for the asset. Call the hydration routing logic. Assert the resulting ScheduledBlock contains multiple content segments split at chapter positions with filler segments between them.

## Failure Semantics

Planning fault. The Tier-2 block is generated without mid-content breaks, causing all ad fill to be appended post-content. The viewer sees the entire episode uninterrupted followed by a long commercial block — violating broadcast simulation fidelity.

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_break_v2_single_chapter.py`

## Enforcement Evidence

TODO
