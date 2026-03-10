# INV-PRESENTATION-BREAK-INVISIBLE-001 — Break detection ignores presentation boundaries

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring break detection does not place ad breaks between presentation segments and the primary content segment. A break between a feature presentation bumper and the movie it introduces violates editorial intent.

## Guarantee

Break detection MUST NOT place break opportunities at presentation-to-content boundaries. Presentation segments (`segment_type="presentation"`) MUST be invisible to chapter-marker extraction, boundary-seam detection, and algorithmic break placement. Only `segment_type="content"` segments participate in break detection.

## Preconditions

- The block contains presentation segments followed by a content segment.

## Observability

A BreakOpportunity is placed at the boundary between the last presentation segment and the primary content segment.

## Deterministic Testability

Construct an assembly with 2 presentation segments and 1 content segment. Run break detection. Assert zero break opportunities at the presentation-to-content boundary. Assert that content-to-content boundaries (if any exist within the content segment via chapter markers) are still detected.

## Failure Semantics

**Planning fault.** An ad break between a presentation bumper and its program corrupts the viewing experience and violates editorial intent.

## Required Tests

- `pkg/core/tests/contracts/test_program_presentation.py`

## Enforcement Evidence

TODO
