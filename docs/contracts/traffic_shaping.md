# Traffic Shaping — Canonical Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`, `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

---

## Overview

Traffic shaping governs how the traffic system selects interstitial candidates from eligible assets at runtime. It defines the end-to-end behavior from candidate pool creation through policy-driven filtering to final candidate ordering.

This contract is the sole authority for the runtime selection pipeline: how eligible assets become candidates, how candidates are filtered and ordered, and how the selected candidates interact with the break filling process.

### Scope

This contract governs:
- Candidate pool construction from eligible assets
- Type filtering using channel policy
- Cooldown enforcement per asset
- Daily play cap enforcement per asset per channel
- Rotation enforcement and deterministic candidate ordering
- Traffic policy configuration resolution from channel YAML
- Interaction between traffic selection and break filling

This contract does NOT govern:
- Asset discovery, enrichment, or eligibility determination (`interstitial_enrichment.md`)
- Break opportunity identification or placement (`break_detection.md`)
- Break slot expansion or budget allocation (`break_structure.md`)
- Fill orchestration mechanics: pad distribution, filler fallback, exact duration accounting (`traffic_manager.md`)
- YAML schema structure, inventory declarations, or profile naming (`traffic_dsl.md`)

### Related Contracts

- `interstitial_enrichment.md` — Upstream: asset discovery through eligibility. Defines the `interstitial_type` field that traffic shaping queries.
- `traffic_policy.md` — Pure domain evaluation logic. This contract defines the runtime outcomes that the policy layer enforces.
- `traffic_dsl.md` — YAML configuration declarations. Defines profile and inventory schema; this contract defines how resolved configuration drives selection.
- `traffic_manager.md` — Downstream: break fill orchestration. Consumes selected candidates and packs them into breaks.
- `break_structure.md` — Break slot expansion. Determines which slots receive traffic-selected candidates.

---

## Terminology

### Candidate Pool

The set of interstitial assets that are eligible for traffic selection at a given moment. The pool is constructed by querying the asset catalog for assets that have `interstitial_type` in their editorial payload, are in `ready` state, and have valid `duration_ms` within the requested bounds. The pool is the input to the traffic policy evaluation pipeline.

### Traffic Policy

A resolved set of channel-level traffic rules that govern candidate filtering and selection. Contains `allowed_types`, `default_cooldown_seconds`, `type_cooldowns_seconds`, and `max_plays_per_day`. Instantiated from a TrafficProfile declared in the channel DSL.

### Play History

An ordered list of `PlayRecord` entries representing historical interstitial plays on a channel. Used for cooldown evaluation, daily cap counting, and rotation ordering. Play history accumulates across breaks within a single block.

### Rotation

The deterministic ordering of eligible candidates by least-recently-played. Ensures even distribution of interstitial plays across the available inventory over time.

### Cooldown

The minimum elapsed time between consecutive plays of the same asset on the same channel. Prevents viewer fatigue from repeated exposure to the same interstitial within a short window.

### Daily Cap

The maximum number of times a single asset may be played on a channel within one traffic day. Prevents over-saturation of any single interstitial across a broadcast day.

### Traffic Day

The 24-hour boundary used for daily cap counting. The day boundary is defined by `day_start_ms`, which may differ from UTC midnight.

---

## Inputs

### Eligible Assets

Assets that have completed the interstitial enrichment pipeline (`interstitial_enrichment.md`). An asset is eligible when:
- `AssetEditorial.payload` contains the key `"interstitial_type"` (stamped by `InterstitialTypeEnricher`)
- `Asset.state` equals `"ready"` (auto-promoted or operator-verified)
- `Asset.duration_ms` is non-null and positive

### Channel Traffic Policy

A `TrafficPolicy` object resolved from the channel YAML. Resolution follows `traffic_dsl.md`: the schedule block's `traffic_profile` override is checked first, then the channel's `default_profile`.

### Play History

`PlayRecord` entries from the `traffic_play_log` table, scoped to the current channel. Each record contains `asset_id`, `asset_type`, and `played_at_ms`.

### Duration Constraint

The `max_duration_ms` parameter specifying the maximum asset duration that fits in the current break slot. Candidates exceeding this duration are excluded from the pool.

### Current Time

`now_ms` (UTC milliseconds) — used for cooldown window evaluation.

### Day Boundary

`day_start_ms` (UTC milliseconds) — the start of the current traffic day, used for daily cap counting.

---

## Required Outcomes

### Candidate Pool Creation

**CP-1.** The candidate pool MUST be constructed by querying assets where `AssetEditorial.payload` contains the key `"interstitial_type"`. Assets without this key MUST NOT appear in the pool.

**CP-2.** The pool MUST include only assets with `state='ready'`. Assets in `new`, `enriching`, or `retired` state MUST be excluded.

**CP-3.** The pool MUST include only assets with non-null, positive `duration_ms` that does not exceed `max_duration_ms`.

**CP-4.** The pool MUST NOT reference collection names, collection UUIDs, source names, or filesystem paths. The `interstitial_type` field in `AssetEditorial.payload` is the sole bridge between storage topology and traffic selection.

**CP-5.** Each candidate in the pool MUST carry `asset_uri`, `duration_ms`, and `asset_type` (the `interstitial_type` value from editorial payload).

### Type Filtering

**TF-1.** A candidate MUST be excluded if its `asset_type` is not in `policy.allowed_types`.

**TF-2.** If `allowed_types` is empty, all candidates MUST be excluded.

**TF-3.** Type filtering MUST be the first filter applied to the candidate pool. Candidates excluded by type filtering MUST NOT be evaluated by subsequent filters.

### Cooldown Enforcement

**CD-1.** A candidate MUST be excluded if a `PlayRecord` exists for the same `asset_id` where `now_ms - played_at_ms` is less than the applicable cooldown.

**CD-2.** The applicable cooldown for a candidate is `policy.type_cooldowns_seconds[asset_type]` if the key exists, otherwise `policy.default_cooldown_seconds`.

**CD-3.** If the applicable cooldown is zero or negative, no cooldown applies to that candidate.

**CD-4.** Cooldown evaluation MUST use the most recent `PlayRecord.played_at_ms` for each `asset_id`. Earlier records for the same asset are irrelevant to cooldown.

**CD-5.** Cooldown filtering MUST be applied after type filtering and before daily cap filtering.

### Daily Play Cap Enforcement

**DC-1.** A candidate MUST be excluded if the count of `PlayRecord` entries for the same `asset_id` with `played_at_ms >= day_start_ms` equals or exceeds `policy.max_plays_per_day`.

**DC-2.** If `max_plays_per_day` is `0`, the daily cap filter MUST be skipped entirely. Zero means unlimited.

**DC-3.** Daily cap filtering MUST be applied after cooldown filtering and before rotation sorting.

### Rotation Enforcement

**RT-1.** Among candidates that pass all filters, selection MUST prefer the candidate whose most recent `PlayRecord.played_at_ms` is oldest (least-recently-played first).

**RT-2.** Candidates with no play history MUST be preferred over candidates with history. A never-played candidate sorts before any previously-played candidate.

**RT-3.** Ties in `played_at_ms` (including multiple never-played candidates) MUST be broken by `asset_id` in lexical ascending order.

### Deterministic Candidate Ordering

**DO-1.** Given identical inputs (`candidates`, `policy`, `play_history`, `now_ms`, `day_start_ms`), `evaluate_candidates` MUST return the same ordered list regardless of the input order of `candidates`.

**DO-2.** `select_next` MUST return the first candidate from `evaluate_candidates`. If the list is empty, it MUST return `None`.

**DO-3.** The evaluation pipeline MUST NOT introduce randomness. No `random.shuffle`, no time-of-day variation, no external state dependency.

### Traffic Policy Configuration

**PC-1.** Traffic policy MUST be resolved from the channel YAML. The resolution order is: (1) schedule block's `traffic_profile` override, (2) channel's `default_profile`.

**PC-2.** When no channel YAML exists for a channel slug, the hardcoded default policy MUST be used. The default includes `allowed_types: ["commercial", "promo", "station_id", "psa", "stinger", "bumper", "filler"]`, `default_cooldown_seconds: 3600`, `type_cooldowns: {}`, `max_plays_per_day: 0`.

**PC-3.** Channel-specific YAML MUST overlay `_defaults.yaml` values. Channel-specific values take precedence over defaults.

**PC-4.** Traffic policy MUST be cached for the session lifetime of the `DatabaseAssetLibrary` instance. Policy MUST NOT be re-loaded from YAML on every `get_filler_assets` call.

**PC-5.** Each `TrafficProfile` declared in the DSL MUST map 1:1 to a `TrafficPolicy` runtime object. Field names and semantics are identical.

### Interaction with Break Filling

**BF-1.** When the traffic manager calls `select_next()` and a candidate is selected, a `PlayRecord` MUST be appended to the working play history before the next selection attempt. This ensures rotation advances within a single break.

**BF-2.** Play history MUST accumulate across breaks within a single block. A candidate selected for break N MUST be visible to the selection logic for break N+1.

**BF-3.** The traffic manager MUST copy the caller's play history before mutation. It MUST NOT mutate the caller's original list.

**BF-4.** When `select_next()` returns `None` (no eligible candidate), the traffic manager MUST stop filling the current interstitial pool. It MUST NOT retry with relaxed policy.

**BF-5.** Bumper and station ID slots MUST NOT be filled through the traffic policy engine. They are structural elements selected by dedicated mechanisms, not subject to cooldown, daily caps, or rotation.

**BF-6.** Traffic fill MUST occur at feed time (approximately 30 minutes before air), not at schedule compile time. The schedule compiler produces blocks with empty filler placeholders. Cooldowns and caps are evaluated against current play history at fill time.

---

## Required Metadata Dependencies

Traffic shaping depends on exactly these metadata fields. No additional metadata is required.

| Field | Source | Used By |
|-------|--------|---------|
| `AssetEditorial.payload["interstitial_type"]` | `InterstitialTypeEnricher` during ingest | Pool creation (CP-1), type filtering (TF-1) |
| `Asset.state` | Enrichment pipeline auto-promotion | Pool creation (CP-2) |
| `Asset.duration_ms` | Probe enricher during ingest | Pool creation (CP-3), duration constraint |
| `PlayRecord.asset_id` | `traffic_play_log` table | Cooldown (CD-1), daily cap (DC-1), rotation (RT-1) |
| `PlayRecord.asset_type` | `traffic_play_log` table | Type-specific cooldown lookup (CD-2) |
| `PlayRecord.played_at_ms` | `traffic_play_log` table | Cooldown window (CD-1), daily cap boundary (DC-1), rotation sort (RT-1) |
| `TrafficPolicy.allowed_types` | Channel YAML via `traffic_dsl.md` | Type filtering (TF-1) |
| `TrafficPolicy.default_cooldown_seconds` | Channel YAML via `traffic_dsl.md` | Cooldown fallback (CD-2) |
| `TrafficPolicy.type_cooldowns_seconds` | Channel YAML via `traffic_dsl.md` | Per-type cooldown (CD-2) |
| `TrafficPolicy.max_plays_per_day` | Channel YAML via `traffic_dsl.md` | Daily cap (DC-1) |

---

## Filter Evaluation Order

Filters MUST be applied in this fixed order. A candidate excluded by an earlier filter MUST NOT be evaluated by later filters.

```
Candidate Pool
     │
     ▼
[1] Type Filter ── allowed_types
     │
     ▼
[2] Cooldown Filter ── play history + cooldown_seconds
     │
     ▼
[3] Daily Cap Filter ── play history + day_start_ms + max_plays_per_day
     │
     ▼
[4] Rotation Sort ── least-recently-played first, ties by asset_id
     │
     ▼
Ordered Eligible Candidates
```

---

## Invariants

### INV-TRAFFIC-SHAPING-POOL-INTERSTITIAL-ONLY-001 — Candidate pool contains only interstitial-typed assets

The candidate pool MUST be constructed by querying for `AssetEditorial.payload` containing the key `"interstitial_type"`. Program content, un-enriched assets, and assets without the interstitial_type key MUST NOT appear in the candidate pool.

### INV-TRAFFIC-SHAPING-POOL-READY-ONLY-001 — Candidate pool contains only ready assets

The candidate pool MUST include only assets with `state='ready'`. Assets in any other state MUST be excluded at the query level.

### INV-TRAFFIC-SHAPING-POOL-DURATION-BOUNDED-001 — Candidate pool respects duration bounds

The candidate pool MUST include only assets with non-null, positive `duration_ms` not exceeding `max_duration_ms`. Assets with null, zero, negative, or excessive duration MUST be excluded at the query level.

### INV-TRAFFIC-SHAPING-FILTER-ORDER-001 — Filter evaluation order is fixed

Filters MUST be applied in this order: (1) allowed type, (2) cooldown, (3) daily cap, (4) rotation sort. A candidate excluded by an earlier filter MUST NOT be evaluated by later filters. Reordering filters would change the eligible set in cases where cooldown and cap interact.

### INV-TRAFFIC-SHAPING-DETERMINISTIC-001 — Selection is deterministic

Given identical inputs, `evaluate_candidates` MUST return the same ordered list. `select_next` MUST return the same candidate. No randomness, no external state dependency, no input-order sensitivity.

### INV-TRAFFIC-SHAPING-STRUCTURAL-EXEMPT-001 — Bumpers and station IDs bypass traffic policy

Bumper and station ID selection MUST NOT be routed through `evaluate_candidates` or `select_next`. They are structural elements filled by dedicated mechanisms. They are not subject to `allowed_types`, cooldown, daily cap, or rotation.

### INV-TRAFFIC-SHAPING-HISTORY-ACCUMULATES-001 — Play history accumulates across breaks within a block

When a candidate is selected for break N, a `PlayRecord` MUST be appended to the working history before break N+1 is processed. The traffic manager MUST NOT reset history between breaks. The traffic manager MUST copy the caller's history before mutation.

### INV-TRAFFIC-SHAPING-LATE-BIND-001 — Selection occurs at feed time

Traffic selection MUST occur at feed time (approximately 30 minutes before air), not at schedule compile time. The schedule compiler MUST produce blocks with empty filler placeholders. Cooldowns and caps are evaluated against current play history, not stale compile-time state.

### INV-TRAFFIC-SHAPING-POLICY-YAML-LAYERED-001 — Policy resolution follows YAML layering

Traffic policy MUST be resolved from: (1) hardcoded defaults, overlaid by (2) `_defaults.yaml` if present, overlaid by (3) channel-specific YAML. Channel-specific values take precedence. Policy MUST be cached for the session lifetime.

### INV-TRAFFIC-SHAPING-NONE-STOPS-FILL-001 — No eligible candidate stops the fill loop

When `select_next` returns `None`, the traffic manager MUST stop filling the current interstitial pool. It MUST NOT retry with relaxed policy, skip cooldowns, or lower the cap. The remaining time becomes pad (if spots exist) or filler fallback (if no spots were selected).

---

## Error Handling Outcomes

### No Candidates in Pool

When the candidate pool query returns zero results (no assets match the eligibility criteria), `get_filler_assets` MUST return an empty list. This is not an error. The traffic manager falls back to the static filler file.

### All Candidates Excluded by Policy

When every candidate is excluded by type filtering, cooldown, or daily cap, `evaluate_candidates` MUST return an empty list and `select_next` MUST return `None`. The traffic manager handles this by stopping the fill loop for the current pool. This is not an error.

### No Channel YAML

When no YAML exists for a channel slug, the hardcoded `DEFAULT_TRAFFIC_POLICY` MUST be used. Policy loading MUST NOT raise an error for missing YAML.

### No Channel Slug

When `DatabaseAssetLibrary` is constructed without a `channel_slug`, cooldown and daily cap enforcement MUST be effectively disabled (empty cooled set, empty capped set). Type filtering still applies using `DEFAULT_TRAFFIC_POLICY`.

### Play History Contains Unknown Asset IDs

`PlayRecord` entries for asset IDs not present in the current candidate pool MUST be silently ignored during cooldown, cap, and rotation evaluation. They do not affect the selection outcome.

---

## Required Tests

### Candidate Pool Creation

- A query against assets with `interstitial_type` in editorial payload, `state='ready'`, and valid `duration_ms` MUST return matching assets.
- An asset without `interstitial_type` in editorial payload MUST NOT appear in the pool regardless of state or duration.
- An asset with `state='new'` MUST NOT appear in the pool.
- An asset with null `duration_ms` MUST NOT appear in the pool.
- An asset with `duration_ms` exceeding `max_duration_ms` MUST NOT appear in the pool.
- The pool query MUST NOT reference `collection_uuid` or `collection_name`.

### Type Filtering

- A candidate with `asset_type` in `allowed_types` MUST pass the type filter.
- A candidate with `asset_type` not in `allowed_types` MUST be excluded.
- An empty `allowed_types` list MUST exclude all candidates.
- Type filtering MUST be applied before cooldown filtering (a type-excluded candidate must not be checked for cooldown).

### Cooldown Enforcement

- A candidate played 1 hour ago with `default_cooldown_seconds=3_600` MUST pass cooldown (exactly at boundary).
- A candidate played 59 minutes ago with `default_cooldown_seconds=3_600` MUST be excluded.
- A candidate with a type-specific cooldown MUST use the type cooldown, not the default.
- A candidate with no play history MUST pass cooldown.
- A candidate with `default_cooldown_seconds=0` and no type-specific cooldown MUST pass cooldown regardless of history.

### Daily Play Cap

- A candidate played 2 times today with `max_plays_per_day=3` MUST pass the cap filter.
- A candidate played 3 times today with `max_plays_per_day=3` MUST be excluded.
- `max_plays_per_day=0` MUST skip the cap filter entirely (unlimited).
- Only plays with `played_at_ms >= day_start_ms` MUST count toward the daily cap.

### Rotation

- Among three never-played candidates, they MUST be ordered by `asset_id` lexically ascending.
- A never-played candidate MUST be ordered before a previously-played candidate.
- Among two played candidates, the one played longer ago MUST be ordered first.
- The same candidate set with different input ordering MUST produce the same output order.

### Deterministic Ordering

- Two calls to `evaluate_candidates` with identical inputs MUST return identical output.
- `select_next` MUST return the first element of `evaluate_candidates`, or `None` if empty.

### Policy Configuration

- A channel with YAML traffic config MUST have its policy resolved from the YAML.
- A channel without YAML MUST use `DEFAULT_TRAFFIC_POLICY`.
- A schedule block with `traffic_profile` override MUST use that profile's policy, not the channel default.
- `_defaults.yaml` values MUST be overlaid by channel-specific YAML values.

### Break Filling Interaction

- After selecting a candidate, a `PlayRecord` MUST be appended to the working history.
- A candidate selected for break 1 MUST be visible in the history during break 2 selection.
- The caller's original play history list MUST NOT be mutated.
- When `select_next` returns `None`, no more spots MUST be added to the current pool.
- Bumper selection MUST NOT route through `evaluate_candidates`.
- Station ID selection MUST NOT route through `evaluate_candidates`.

---

## Enforcement Evidence

TODO
