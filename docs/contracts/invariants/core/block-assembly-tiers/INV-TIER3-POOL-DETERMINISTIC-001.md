# INV-TIER3-POOL-DETERMINISTIC-001 — Tier 3 asset selection is deterministic

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-DERIVATION` by ensuring Tier 3 asset selection is reproducible. If pool selection uses uncontrolled RNG, recompilation of the same broadcast day produces different assets, violating the expectation that the same inputs yield the same output. `LAW-CONTENT-AUTHORITY` requires that asset choice is an editorial decision made by the compiler, not a runtime accident.

## Guarantee

Tier 3 asset selection from pools MUST be deterministic. The selection seed MUST be derived from `(channel_id, broadcast_day, block_index, element_type)` using the same hashlib-based approach as `INV-SCHEDULE-SEED-DETERMINISTIC-001`. Same inputs MUST produce the same selected asset across compilations. No uncontrolled RNG (`random.random()`, `random.choice()`) is permitted. Pool filtering by `max_duration_sec` occurs before seed-based selection.

## Preconditions

- The referenced asset pool exists and contains at least one eligible asset after `max_duration_sec` filtering.

## Observability

Two compilations of the same broadcast day with the same channel YAML and asset pools produce different Tier 3 asset selections.

## Deterministic Testability

Compile the same broadcast day twice with identical inputs. Assert every Tier 3 segment has the same `asset_id` in both compilations. Verify no calls to `random.random()` or `random.choice()` exist in the Tier 3 selection path.

## Failure Semantics

**Planning fault.** Non-deterministic asset selection makes compilation unreproducible and violates `LAW-DERIVATION`.

## Required Tests

- `pkg/core/tests/contracts/test_block_assembly_tiers.py`

## Enforcement Evidence

TODO
