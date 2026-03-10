# INV-POOL-TAGS-FILTER-001 — Pool match evaluates tags as AND-combined filter

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`

## Purpose

Protects `LAW-DERIVATION` by ensuring pool match criteria can filter assets by their normalized tags. Without tag filtering, operators cannot define pools for non-episode asset classes (bumpers, rating cards, presentation assets) that lack structured editorial metadata.

## Guarantee

The pool `tags` filter MUST accept a single string or a list of strings. An asset matches only if it possesses every specified tag. Tags are compared case-insensitively.

## Preconditions

- The pool match dict contains a `tags` key with a non-null value.
- Assets have been tagged by the ingest pipeline (`INV-INGEST-PATH-SEGMENT-TAG-001`) or by operator/enricher assignment (`INV-ASSET-TAG-PERSISTENCE-001`).

## Observability

A pool with `tags: [hbo, presentation, intros]` returns only assets that have all three tags.

## Deterministic Testability

Construct a catalog with assets carrying known tag sets. Evaluate a pool with a multi-tag filter. Assert that only assets possessing every specified tag appear in the result. Assert that assets missing any one tag are excluded.

## Failure Semantics

**Planning fault.** A pool that cannot filter by tags forces operators to use fragile filename-based workarounds or over-broad pools.

## Required Tests

- `pkg/core/tests/contracts/test_pool_tags_filter.py`

## Enforcement Evidence

TODO
