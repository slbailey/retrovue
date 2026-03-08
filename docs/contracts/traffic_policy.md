# Traffic Policy — Domain Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`, `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

---

## Overview

Traffic policy is a pure domain layer that evaluates candidate interstitial assets against channel rules before selection. The traffic manager requests candidates from the asset library, filters them through the traffic policy, chooses the best eligible candidate, and updates play history.

Traffic policy does not query databases. Traffic policy does not resolve assets. Traffic policy does not modify break plans or content segments. It accepts a candidate list and play history, and returns the subset of candidates that are eligible for selection.

The policy layer is testable with no database, no filesystem, no scheduler dependencies.

---

## Domain Objects

### TrafficPolicy

Configuration object declaring channel-level traffic rules.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `allowed_types` | list[str] | `["commercial", "promo", "station_id", "psa", "stinger", "bumper", "filler"]` | Interstitial types permitted on this channel. |
| `default_cooldown_ms` | int | `3_600_000` | Minimum ms between re-plays of the same asset on this channel. |
| `type_cooldowns_ms` | dict[str, int] | `{}` | Per-type cooldown overrides in ms. |
| `max_plays_per_day` | int | `0` | Max plays per asset per channel per channel traffic day. `0` = unlimited. |

### PlayRecord

A single historical play event used for cooldown and cap evaluation.

| Field | Type | Description |
|-------|------|-------------|
| `asset_id` | str | Asset identifier. |
| `asset_type` | str | Interstitial type of the played asset. |
| `played_at_ms` | int | UTC ms timestamp when the asset was played. |

### TrafficCandidate

A candidate interstitial asset offered for selection.

| Field | Type | Description |
|-------|------|-------------|
| `asset_id` | str | Asset identifier. |
| `asset_type` | str | Interstitial type (`"commercial"`, `"promo"`, etc.). |
| `duration_ms` | int | Duration in ms. |

---

## Public API

### `evaluate_candidates`

```
evaluate_candidates(
    candidates: list[TrafficCandidate],
    policy: TrafficPolicy,
    play_history: list[PlayRecord],
    now_ms: int,
    day_start_ms: int,
) -> list[TrafficCandidate]
```

Returns the ordered subset of candidates that pass all policy filters. The returned list is sorted by rotation priority: least-recently-played first, ties broken by `asset_id` lexical order.

### `select_next`

```
select_next(
    candidates: list[TrafficCandidate],
    policy: TrafficPolicy,
    play_history: list[PlayRecord],
    now_ms: int,
    day_start_ms: int,
) -> TrafficCandidate | None
```

Convenience function: calls `evaluate_candidates` and returns the first eligible candidate, or `None` if none pass.

---

## Invariants

### INV-TRAFFIC-ALLOWED-TYPE-001 — Allowed type filtering

A candidate MUST be excluded if its `asset_type` is not in `policy.allowed_types`. If `allowed_types` is empty, all candidates MUST be excluded.

### INV-TRAFFIC-COOLDOWN-001 — Asset cooldown enforcement

A candidate MUST be excluded if a `PlayRecord` exists for the same `asset_id` where `now_ms - played_at_ms < applicable_cooldown_ms`. The applicable cooldown is `policy.type_cooldowns_ms[asset_type]` if present, otherwise `policy.default_cooldown_ms`. If `default_cooldown_ms` is `0` and no type-specific cooldown exists, no cooldown applies.

### INV-TRAFFIC-DAILY-CAP-001 — Daily play cap enforcement

A candidate MUST be excluded if the count of `PlayRecord` entries for the same `asset_id` with `played_at_ms >= day_start_ms` equals or exceeds `policy.max_plays_per_day`. The `day_start_ms` parameter represents the channel traffic day boundary, which may differ from UTC midnight. If `max_plays_per_day` is `0`, no cap is applied.

### INV-TRAFFIC-ROTATION-001 — Deterministic round-robin rotation

Among eligible candidates, selection MUST prefer the candidate whose most recent `PlayRecord.played_at_ms` is oldest (least-recently-played). Candidates with no play history MUST be preferred over candidates with history. Ties MUST be broken by `asset_id` lexical ascending order. Rotation MUST be deterministic regardless of candidate input ordering.

### INV-TRAFFIC-FILTER-ORDER-001 — Filter evaluation order

Filters MUST be applied in this order: (1) allowed type, (2) cooldown, (3) daily cap, (4) rotation sort. A candidate excluded by an earlier filter MUST NOT be evaluated by later filters.

### INV-TRAFFIC-PURE-001 — Policy evaluation is pure

`evaluate_candidates` and `select_next` MUST NOT mutate any input. They MUST NOT perform I/O, database queries, or filesystem access. All state needed for evaluation is passed as arguments.

### INV-TRAFFIC-EMPTY-001 — Empty inputs

If `candidates` is empty, `evaluate_candidates` MUST return `[]` and `select_next` MUST return `None`. If `play_history` is empty, all candidates pass cooldown and cap filters.

### INV-TRAFFIC-NONE-001 — No eligible asset

If no candidate passes all filters, `select_next` MUST return `None`. The traffic manager MUST handle a `None` result without error. A `None` result MUST NOT cause the break to be skipped; the caller falls back to its default fill strategy.

---

## Filter Details

### Allowed Type Filter

For each candidate:
- Read `candidate.asset_type`.
- If `candidate.asset_type` not in `policy.allowed_types`, exclude.

### Cooldown Filter

For each candidate that passed the type filter:
- Find all `PlayRecord` entries where `record.asset_id == candidate.asset_id`.
- Determine `cooldown_ms`: use `policy.type_cooldowns_ms[candidate.asset_type]` if the key exists, otherwise `policy.default_cooldown_ms`.
- If `cooldown_ms > 0` and any matching record has `now_ms - record.played_at_ms < cooldown_ms`, exclude.

### Daily Cap Filter

For each candidate that passed the cooldown filter:
- Count `PlayRecord` entries where `record.asset_id == candidate.asset_id` and `record.played_at_ms >= day_start_ms`.
- If `policy.max_plays_per_day > 0` and `count >= policy.max_plays_per_day`, exclude.

### Rotation Sort

Sort surviving candidates deterministically by least-recent play:
- For each candidate, find `max(record.played_at_ms)` across matching records, or `-1` if no records exist.
- Sort ascending by `(last_play_time, asset_id)`.
- Never-played candidates sort first (`-1`). Among never-played, `asset_id` lexical order determines position.

---

## Edge Cases

| Condition | Result |
|-----------|--------|
| No candidates | Empty result. |
| No play history | All candidates pass cooldown and cap; rotation sorts by `asset_id`. |
| All candidates excluded by type | Empty result. |
| All candidates in cooldown | Empty result. `select_next` returns `None`. |
| All candidates at daily cap | Empty result. `select_next` returns `None`. |
| `max_plays_per_day = 0` | Cap filter is skipped entirely. |
| `default_cooldown_ms = 0`, no type cooldowns | Cooldown filter is skipped entirely. |
| Single candidate | Returns that candidate if it passes all filters. |
| Multiple candidates, identical history | Sorted by `asset_id` lexical order. |
| Candidate list in different order | Same result — rotation is deterministic. |

---

## Required Tests

- `pkg/core/tests/contracts/test_traffic_policy.py`

---

## Enforcement Evidence

TODO
