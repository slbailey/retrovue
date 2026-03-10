# Traffic Inventory — Canonical Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`, `LAW-CONTENT-AUTHORITY`

---

## Overview

Traffic inventory governs how `asset_category` metadata participates in runtime traffic selection. It defines category-aware ordering within a single break to promote diversity without overriding the eligibility filters defined by `traffic_policy.md` and `traffic_shaping.md`.

Category awareness operates exclusively on already-eligible candidates. It does not add or remove candidates from the pipeline. It reorders them to avoid consecutive same-category selections and to distribute categories across break slots.

### Scope

This contract governs:
- Treatment of `asset_category` during candidate evaluation
- Category diversity ordering within a single break
- Consecutive same-category avoidance within a single break
- Interaction between category ordering and the existing filter pipeline

This contract does NOT govern:
- Category assignment during ingest or enrichment (`interstitial_enrichment.md`)
- Type filtering, cooldown enforcement, or daily cap enforcement (`traffic_policy.md`)
- Candidate pool construction or eligibility (`traffic_shaping.md`)
- Break slot expansion, pad distribution, or filler fallback (`break_structure.md`, `traffic_manager.md`)
- YAML schema structure or profile declarations (`traffic_dsl.md`)

### Related Contracts

- `traffic_policy.md` — Upstream: pure domain evaluation. Produces the ordered eligible candidate list that category ordering reorders.
- `traffic_shaping.md` — Upstream: end-to-end selection pipeline. Defines the filter evaluation order. Category ordering operates after all filters in that pipeline.
- `interstitial_enrichment.md` — Origin: defines `interstitial_category` assignment during filesystem discovery.
- `traffic_manager.md` — Consumer: break fill orchestration. Calls `select_next` iteratively and maintains the break working set.

---

## Terminology

### Asset Category

The `asset_category` field on `TrafficCandidate`. Derived from `AssetEditorial.payload["interstitial_category"]`, which is set during filesystem discovery by `FilesystemImporter._infer_tags_from_path()`. Values are canonical category tags: `restaurant`, `auto`, `food`, `insurance`, `retail`, `travel`, `toys`, `tech`, `entertainment`, etc.

### Uncategorized

A candidate whose `asset_category` is `None`. For category evaluation purposes, all uncategorized candidates are treated as belonging to the synthetic category `"uncategorized"`. This synthetic value is used only for ordering decisions and is never persisted.

### Break Working Set

The list of candidates already selected for the current break. Maintained by the traffic manager during iterative `select_next` calls. Used to determine which categories have already been placed in the break.

### Category Diversity

The property of a break containing candidates from distinct categories. Category diversity ordering prefers candidates whose category has not yet appeared in the break working set.

### Effective Category

The normalized category used for evaluation. If `TrafficCandidate.asset_category` is `None`, the effective category is `"uncategorized"`. Otherwise the effective category is the value of `asset_category`.

---

## Inputs

### Eligible Candidates

The ordered list returned by `evaluate_candidates` after type filtering, cooldown, daily cap, and rotation sort have been applied. Category ordering receives only candidates that have already passed all eligibility filters.

### Break Working Set

The categories of candidates already selected in the current break. Represented as an ordered list of `asset_category` values (with `None` normalized to `"uncategorized"`).

### TrafficCandidate.asset_category

An optional string field on `TrafficCandidate`. Populated from `AssetEditorial.payload["interstitial_category"]` during candidate construction in `DatabaseAssetLibrary.get_filler_assets()`. `None` when the editorial payload does not contain the key.

---

## Required Outcomes

### Category Visibility

**CV-1.** `TrafficCandidate` MUST carry `asset_category` as an optional field. The field MUST accept `str | None`.

**CV-2.** When `AssetEditorial.payload` does not contain the key `"interstitial_category"`, `asset_category` MUST be `None`.

**CV-3.** For category evaluation purposes, a `None` `asset_category` MUST be treated as `"uncategorized"`. This normalization MUST NOT mutate the `TrafficCandidate` object.

### Break Category Separation

**CS-1.** When selecting the next candidate for a break, the traffic engine MUST NOT select a candidate whose effective category matches the effective category of the immediately preceding selection in the same break, when at least one alternative category exists among the remaining eligible candidates.

**CS-2.** If all remaining eligible candidates share the same effective category as the preceding selection, the candidate MUST still be selected. Category separation MUST NOT cause a break slot to go unfilled when eligible candidates exist.

**CS-3.** For the first selection in a break (empty working set), no category separation constraint applies.

**CS-4.** Category separation takes precedence over category diversity. When diversity preference would select a candidate that violates the consecutive-category separation rule, the engine MUST select the next candidate that satisfies separation while preserving rotation order within the applicable diversity tier.

### Category Diversity Preference

**DP-1.** Among eligible candidates, those whose effective category has not yet appeared in the break working set MUST be preferred over those whose category has already appeared.

**DP-2.** Among candidates that share the same diversity status (both unseen or both seen), the rotation order from `evaluate_candidates` MUST be preserved. Category diversity MUST NOT override rotation priority within the same diversity tier.

**DP-3.** Category diversity preference MUST be evaluated per break. The break working set MUST be reset at the start of each break. Category appearances in previous breaks within the same block MUST NOT influence diversity ordering in subsequent breaks.

### Category Neutrality

**CN-1.** Category rules MUST NOT add candidates to the eligible set. A candidate excluded by type filtering, cooldown, or daily cap MUST remain excluded regardless of its category.

**CN-2.** Category rules MUST NOT remove candidates from the eligible set. A candidate that passes all eligibility filters MUST remain eligible regardless of its category.

**CN-3.** Category ordering MUST operate after the rotation sort step in the filter pipeline. It MUST NOT be interleaved with type filtering, cooldown filtering, or daily cap filtering.

### Determinism

**DT-1.** Given identical inputs (eligible candidate list, break working set), category-based reordering MUST produce the same output order. No randomness, no external state dependency.

**DT-2.** Candidates with identical effective category and identical rotation priority MUST be ordered by `asset_id` lexical ascending order. This extends the tie-breaking rule from `INV-TRAFFIC-ROTATION-001`.

### Metadata Dependency

**MD-1.** Category evaluation MUST use only `TrafficCandidate.asset_category`. No filesystem paths, collection names, collection UUIDs, source names, or external metadata MUST be referenced.

**MD-2.** Category evaluation MUST NOT query the database. All category information MUST be present on the `TrafficCandidate` object at evaluation time.

---

## Filter Pipeline Position

Category ordering operates after the existing four-stage filter pipeline defined in `traffic_shaping.md`. It does not replace or reorder any existing stage.

```
Candidate Pool
     │
     ▼
[1] Type Filter ── allowed_types
     │
     ▼
[2] Cooldown Filter ── play history + cooldown_ms
     │
     ▼
[3] Daily Cap Filter ── play history + day_start_ms + max_plays_per_day
     │
     ▼
[4] Rotation Sort ── least-recently-played first, ties by asset_id
     │
     ▼
[5] Category Ordering ── diversity preference + separation (this contract)
     │
     ▼
Ordered Eligible Candidates
```

---

## Invariants

### INV-TRAFFIC-INVENTORY-NEUTRALITY-001 — Category does not influence eligibility

Category rules MUST NOT add or remove candidates from the eligible set. A candidate's `asset_category` MUST NOT be evaluated during type filtering, cooldown enforcement, or daily cap enforcement. Category ordering operates only on the already-filtered candidate list.

### INV-TRAFFIC-INVENTORY-DIVERSITY-001 — Category diversity preference within break

Among eligible candidates, those whose effective category has not yet appeared in the break working set MUST be preferred over those whose category has already appeared. Within the same diversity tier (both unseen or both seen), the rotation order from `evaluate_candidates` MUST be preserved.

### INV-TRAFFIC-INVENTORY-SEPARATION-001 — Consecutive same-category avoidance

The traffic engine MUST NOT select a candidate whose effective category matches the effective category of the immediately preceding selection in the same break, when at least one alternative category exists among the remaining eligible candidates. When no alternative exists, the candidate MUST still be selected.

### INV-TRAFFIC-INVENTORY-BREAK-SCOPE-001 — Break working set is per-break

The break working set MUST be reset at the start of each break. Category appearances from previous breaks within the same block MUST NOT influence category ordering in subsequent breaks.

### INV-TRAFFIC-INVENTORY-DETERMINISTIC-001 — Category ordering is deterministic

Given identical inputs (eligible candidates and break working set), category ordering MUST produce the same output. Ties within the same diversity tier MUST be broken by rotation priority, then by `asset_id` lexical ascending order.

### INV-TRAFFIC-INVENTORY-UNCATEGORIZED-001 — Missing category treated as uncategorized

A `TrafficCandidate` with `asset_category = None` MUST be treated as effective category `"uncategorized"` for all category evaluation. This normalization MUST NOT mutate the `TrafficCandidate` object. Multiple uncategorized candidates are considered to share the same category.

---

## Edge Cases

| Condition | Result |
|-----------|--------|
| All candidates share the same category | Selection proceeds in rotation order. Category ordering has no effect. |
| All candidates are uncategorized (`None`) | Treated as same category. Selection proceeds in rotation order. |
| Single candidate | Selected regardless of category. |
| Two candidates, same category, previous selection was same category | First by rotation order is selected (no alternative exists). |
| Two candidates, different categories, previous selection matches one | The non-matching candidate is selected. |
| First selection in break | No category constraint. Rotation order applies. |
| Break working set contains all categories present in candidate list | Separation still applies to the immediately preceding selection. Diversity preference has no unseen categories to prefer; rotation order is preserved. |

---

## Required Tests

- Break selection prefers candidates from categories not yet used in the break working set over categories already used.
- When the immediately preceding selection has category X and alternatives with category Y exist, the next selection MUST NOT be category X.
- When all remaining candidates share the same category as the preceding selection, the next candidate MUST still be selected.
- When all candidates are uncategorized, selection proceeds in rotation order without error.
- Category ordering MUST be deterministic: identical inputs produce identical output regardless of input order.
- A candidate excluded by type filtering MUST remain excluded regardless of its category.
- A candidate excluded by cooldown MUST remain excluded regardless of its category.
- The break working set MUST be reset between breaks: category used in break 1 MUST NOT affect ordering in break 2.
- A `TrafficCandidate` with `asset_category = None` MUST be treated as `"uncategorized"` for diversity and separation.
- Among candidates in the same diversity tier, rotation order from `evaluate_candidates` MUST be preserved.

---

## Enforcement Evidence

TODO
