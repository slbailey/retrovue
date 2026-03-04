# INV-PLAYLIST-HORIZON-DETERMINISM-007 — PlaylistEvent generation must be deterministic

Status: Invariant
Authority Level: Execution Intent
Derived From: PlayoutExecutionModel — Horizon Interaction

## Purpose

Ensures that PlaylistEvent generation is a pure function of its inputs. Given the same ScheduleItem, channel policy, and resolver state, the resulting PlaylistEvents must be identical. This guarantees rebuild safety (regenerating a horizon window produces the same events), cache correctness (cached events match regenerated events), and horizon regeneration safety (atomic replacement produces equivalent results).

## Guarantee

For the same inputs:

- ScheduleItem (identity, asset, timing)
- Channel policy (ad break rules, promo insertion rules)
- Resolver state (asset metadata, availability)

The resulting PlaylistEvents must be byte-for-byte identical in all fields: `id`, `start_utc_ms`, `duration_ms`, `kind`, `schedule_item_id`, `asset_id`, `offset_ms`, and `metadata`.

## Preconditions

- The input triple (ScheduleItem, channel policy, resolver state) is unchanged between generations.
- No external randomness or wall-clock sampling influences generation.

## Observability

Generate PlaylistEvents twice from identical inputs. Compare all fields. Any divergence is a violation.

## Deterministic Testability

Generate PlaylistEvents from a fixed ScheduleItem, fixed channel policy, and fixed resolver state. Generate again with the same inputs. Assert field-by-field equality across all events.

## Failure Semantics

**Generation fault.** The PlaylistEvent generator introduced non-determinism — likely sampling wall-clock time, using unseeded randomness, or depending on mutable external state during generation.

## Required Tests

- `pkg/core/tests/contracts/playout/test_playlist_determinism.py::test_playlist_generation_is_deterministic`
