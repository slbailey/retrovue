## Overview

For any `(channel_id, now)`, all schedule consumers that answer "what is on now?"
MUST resolve from the same canonical revision authority before selecting content.
EPG and AIR runtime selection MUST derive the same revision identity for current-time
lookup so guide truth and playout truth cannot diverge.

## Invariants

### 1) Canonical revision authority

- `ChannelActiveRevision` is the canonical authority for selecting the active revision for a given `(channel_id, broadcast_day)`.
- Consumers MUST NOT infer canonical truth from broad `ScheduleRevision.status == "active"` scans alone.

### 2) EPG/AIR revision identity consistency

- For a given `(channel_id, now)`, EPG and AIR MUST resolve the same `broadcast_day`.
- For a given `(channel_id, now)`, EPG and AIR MUST resolve the same `schedule_revision_id`.
- EPG and AIR MUST NOT independently choose different revisions for the same current-time lookup.

### 3) Pointer-first runtime hydration

- Runtime timeline hydration MUST load `ScheduleItem` rows from the revision selected by `ChannelActiveRevision`.
- Broad active-row joins MAY be used for validation/debugging only and MUST NOT be used as authority for runtime current-content selection.

### 4) Duplicate-active protection

- Multiple `ScheduleRevision.status == "active"` rows for the same `(channel_id, broadcast_day)` is an invariant violation.
- Runtime MUST NOT silently choose an arbitrary active row under duplicate-active conditions.

### 5) Current-content consistency

- If EPG says program `X` is airing at `now`, AIR MUST resolve a block/segment chain originating from the same canonical revision and corresponding schedule item at `now`.

### 6) Boundary consistency

- Broadcast-day derivation for EPG and AIR MUST use the same timezone and programming-day-start logic.

## Failure conditions

- EPG and AIR resolve different `schedule_revision_id` values for the same `(channel_id, now)`.
- Runtime hydrates from stale active revisions not pointed to by `ChannelActiveRevision`.
- AIR selects content from a different revision than the guide.
- Duplicate active revisions for a day are silently tolerated and arbitrarily chosen.
- EPG and AIR derive different `broadcast_day` values near day-boundary lookup.

## Required tests

- `tests/contracts/test_revision_authority_consistency.py::test_epg_and_runtime_resolve_same_revision_for_now`
  - Invariants: Canonical revision authority; EPG/AIR revision identity consistency.
- `tests/contracts/test_revision_authority_consistency.py::test_runtime_ignores_stale_active_revision_not_pointed`
  - Invariants: Pointer-first runtime hydration.
- `tests/contracts/test_revision_authority_consistency.py::test_runtime_current_content_matches_epg_current_content`
  - Invariants: Current-content consistency; EPG/AIR revision identity consistency.
- `tests/contracts/test_revision_authority_consistency.py::test_duplicate_active_revisions_same_day_are_rejected`
  - Invariants: Duplicate-active protection.
- `tests/contracts/test_revision_authority_consistency.py::test_boundary_derivation_matches_between_epg_and_runtime`
  - Invariants: Boundary consistency; EPG/AIR revision identity consistency.

## Enforcement evidence

TODO
