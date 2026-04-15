## Overview

Runtime playout artifacts used to answer "what plays now" MUST be traceable to
the canonical schedule revision selected for `(channel_id, broadcast_day)`.
No artifact is authoritative unless its revision provenance matches
`ChannelActiveRevision` authority for the lookup instant.

Authoritative artifacts include, at minimum:

- runtime-selected block identity
- `PlaylistEvent` rows used for filled playback
- persisted compiled segment/planned playout chains

## Invariants

### 1) Revision provenance required

Every persisted playout artifact used for authoritative runtime lookup MUST
carry `schedule_revision_id`. `NULL` provenance is invalid for authoritative
selection.

### 2) Canonical revision match

For `(channel_id, now)`, runtime MAY select only artifacts whose
`schedule_revision_id` equals the canonical revision selected through
`ChannelActiveRevision` for derived broadcast day.

### 3) No stale artifact eligibility

Artifacts tied to superseded or otherwise non-canonical revisions MUST be
ineligible for runtime "plays now" selection once canonical revision changes.

### 4) Block-to-schedule traceability

A runtime-selected block MUST be traceable to schedule origin:

- `schedule_revision_id`
- schedule source identity (`schedule_item_id` or equivalent deterministic schedule mapping)

Opaque block identities without schedule provenance are invalid for
authoritative runtime selection.

### 5) Revision change invalidation

When a new revision becomes canonical for a day, stale artifacts from older
revisions MUST be invalidated, ignored, or rebuilt before runtime lookup.

### 6) AIR/EPG content consistency

If EPG reports program `X` at `now`, runtime-selected artifact for `now` MUST
originate from the same canonical revision and corresponding schedule source for
`X`.

## Failure conditions

- `PlaylistEvent.schedule_revision_id IS NULL` and row is used as authoritative runtime answer.
- Runtime launches block/artifact whose provenance revision differs from canonical pointer-selected revision.
- Artifact from prior revision remains selectable after canonical revision change.
- Runtime-selected block cannot be traced to schedule provenance.
- EPG current item and runtime current block resolve to different revision provenance.

## Required tests

- `tests/contracts/test_playout_artifact_revision_provenance.py::test_playlist_event_requires_revision_provenance`
  - Invariants: Revision provenance required.
- `tests/contracts/test_playout_artifact_revision_provenance.py::test_runtime_selects_only_canonical_revision_artifacts`
  - Invariants: Canonical revision match.
- `tests/contracts/test_playout_artifact_revision_provenance.py::test_stale_artifacts_are_ineligible_after_revision_change`
  - Invariants: No stale artifact eligibility; Revision change invalidation.
- `tests/contracts/test_playout_artifact_revision_provenance.py::test_selected_block_is_traceable_to_schedule_source`
  - Invariants: Block-to-schedule traceability.
- `tests/contracts/test_playout_artifact_revision_provenance.py::test_epg_and_runtime_content_share_revision_provenance`
  - Invariants: AIR/EPG content consistency; Canonical revision match.
- `tests/contracts/test_playout_artifact_revision_provenance.py::test_null_provenance_artifact_rejected_for_current_lookup`
  - Invariants: Revision provenance required; No stale artifact eligibility.
