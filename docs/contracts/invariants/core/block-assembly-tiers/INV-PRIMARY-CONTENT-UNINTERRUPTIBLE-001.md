# INV-PRIMARY-CONTENT-UNINTERRUPTIBLE-001 — Primary content cannot be interrupted by any compilation pass

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by making the atomicity of primary content (Tier 0) an explicit, independently testable guarantee. Previously this protection existed only as the negative space of `INV-MOVIE-PRIMARY-ATOMIC` and the Tier Displacement Rule. Without an explicit invariant, new compilation passes (obligations, fill, structural resolution) risk introducing breaks into or around primary content in ways that violate editorial intent.

## Guarantee

Primary content (Tier 0) MUST NOT be interrupted, split, truncated, or have breaks injected into it by any compilation pass. This applies to all passes: obligation evaluation, break detection, traffic fill, structural resolution, and any future compilation stage.

A primary content segment's start time, duration, and continuity MUST be preserved from first-pass placement through final compiled output.

## Preconditions

- A block contains at least one segment marked `is_primary=True`.
- The block has completed first-pass compilation (Tier 0 content placed).

## Observability

A compiled schedule day where any primary content segment has been split into multiple segments, had its duration reduced, or has a non-primary segment inserted between its logical start and end. Observable via audit of `compiled_segments` for blocks containing primary content.

## Deterministic Testability

Given a block with a single primary content segment of known duration, run all compilation passes (obligation evaluation, break detection, traffic fill). Verify: primary segment count is unchanged (exactly one), primary segment duration is unchanged, no non-primary segment appears between primary content boundaries. Repeat with obligation triggers that fall within the primary content time range and confirm obligation placement defers to safe points outside primary content per `INV-CLOCK-OBLIGATIONS-OVERRIDE-001`.

## Failure Semantics

**Planning fault.** A compilation pass modified, split, or interrupted primary content. The compiled schedule violates editorial intent established by the DSL schedule definition.

## Required Tests

- `pkg/core/tests/contracts/test_block_assembly_tiers.py`

## Enforcement Evidence

TODO
