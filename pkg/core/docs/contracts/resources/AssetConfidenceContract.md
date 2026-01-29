# Asset Confidence & Auto-State Contract

## Purpose

Define confidence-based, automatic lifecycle and broadcast-approval behavior for assets
created or updated during ingest. High-confidence assets become broadcast-ready without
manual review; low-confidence assets require human review.

---

## Scope

Applies during ingest (source/collection) when creating new assets or detecting updates.
This contract defines scoring, thresholds, and the state/approval effects that result.

Status: ACTIVE. `CollectionIngestContract.md` and `SourceIngestContract.md` have been
updated to allow auto-ready creation with approval when confidence ≥ threshold.

---

## Definitions

- Confidence score: floating value in [0.0, 1.0].
- Thresholds:
  - `auto_ready_threshold` (default: 0.80) — at or above this value, an asset is considered
    broadcast-ready with no human intervention.
  - `review_threshold` (default: 0.50) — below this value, an asset MUST enter a review
    queue (implementation-specific), or be flagged for operator attention.
  - Values between `review_threshold` and `auto_ready_threshold` are accepted but not
    auto-approved; they require enrichment or explicit operator approval.
- Importer policy: Importer types MAY have default threshold overrides (e.g., Plex media
  metadata tends to be high quality and can use the defaults without reduction).

---

## Behavior Contract Rules (B-#)

- B-1: For each asset enumerated by ingest, the system MUST compute a deterministic
       confidence score from normalized metadata and content signals. The computation MUST
       not perform writes.
- B-2: New asset creation:
  - If score >= `auto_ready_threshold`: set `state=ready` AND `approved_for_broadcast=true`.
  - If `review_threshold` <= score < `auto_ready_threshold`: set `state=new`,
    `approved_for_broadcast=false`.
  - If score < `review_threshold`: set `state=new`, `approved_for_broadcast=false`,
    and flag for human review (operator attention list).
- B-3: Existing asset updates that change content or effective enricher:
  - MUST first downgrade in-session: `ready` → `enriching`, `approved_for_broadcast=false`.
  - `enriching` is a transient state used only while enrichment is actively running.
  - Re-scoring MAY be computed, but MUST NOT re-promote within the same ingest transaction.
    Re-promotion occurs only after enrichment or explicit operator action.
- B-4: Confidence score, thresholds used, and decision outcome MUST be recorded in JSON
       ingest stats for operator visibility.
- B-5: Human-readable output MUST summarize counts for `auto_ready`, `needs_enrichment`,
       and `needs_review` per collection and in aggregate.
- B-6: With `--json`, per-collection results MUST include per-bucket counts and thresholds.
- B-7: Thresholds are operator-configurable (CLI flag or configuration), but defaults MUST
       be stable and documented. Changing thresholds does not retroactively update existing
       assets; it only affects current ingest runs.

---

## Data Contract Rules (D-#)

- D-1: State and approval decisions MUST occur in the same Unit of Work that creates the
       asset, without intermediate commits.
- D-2: For updates, in-place downgrades (ready→enriching and approval=false) MUST occur in
       the current session; no commit inside helpers.
- D-3: The JSON stats object MUST include deterministic keys:
  - `assets_auto_ready`
  - `assets_needs_enrichment`
  - `assets_needs_review`
  - `thresholds`: `{ "auto_ready": float, "review": float }`
- D-4: Confidence scores and decisions SHOULD be stored in an audit trail but MUST NOT be
       required for minimal operation of ingest.

---

## Signals (non-normative examples)

Implementations MAY consider signals such as: presence of duration, valid container/codec,
title/year/season/episode completeness, artwork, chapters/subtitles availability, and
consistent media properties. This section is illustrative and NOT a normative requirement.

---

## Examples

```bash
# Default thresholds (auto_ready=0.80, review=0.50)
retrovue source ingest "My Plex Server" --json

# Stricter auto-ready threshold
retrovue collection ingest "TV Shows" --auto-ready-threshold 0.9 --json
```

Example JSON (per-collection snippet):

```json
{
  "thresholds": { "auto_ready": 0.8, "review": 0.5 },
  "stats": {
    "assets_auto_ready": 120,
    "assets_needs_enrichment": 30,
    "assets_needs_review": 5
  }
}
```

---

## Test Coverage Mapping

Planned tests (activated when ingest contracts are revised to allow auto-approval):

- CLI: `tests/contracts/test_asset_confidence_contract.py` — B-1..B-7
- Data: `tests/contracts/test_asset_confidence_data_contract.py` — D-1..D-4

---

## See Also

- [Asset Contract](AssetContract.md)
- [Collection Ingest](CollectionIngestContract.md)
- [Source Ingest](SourceIngestContract.md)


