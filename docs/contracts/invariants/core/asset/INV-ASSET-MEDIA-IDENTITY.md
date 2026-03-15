# INV-ASSET-MEDIA-IDENTITY — Asset schedules, media plays

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-ELIGIBILITY`

## Purpose

The catalog separates logical programs (Assets) from playable files (Media). Scheduling and execution MUST respect this boundary: editorial decisions apply to Assets; playout consumes Media. Violating this separation would allow scheduling to reference files directly or playout to select content without schedule authority.

## Guarantee

The scheduler MUST schedule Assets only. The scheduler MUST NOT schedule or reference Media directly. Playout MUST resolve a scheduled Asset to a Media variant at runtime. Playout MUST NOT receive or emit schedule slots that reference Media as the unit of scheduling. Media selection MUST occur after scheduling and before playout execution.

## Preconditions

None. This invariant holds for all scheduling and playout operations.

## Observability

Schedule artifacts (SchedulePlan, ScheduleDay, ExecutionEntry, PlaylistEvent) MUST reference Asset identifiers. Playout plans handed to AIR MUST carry Asset-derived references; Media selection (which file to play) MUST occur in Core when building the playout plan or in a defined resolution step before AIR receives the plan.

## Deterministic Testability

Given a ScheduleDay or ExecutionEntry, assert that every program slot references an Asset (or filler policy), not a Media entity. Given a playout plan sent to AIR, assert that the plan was produced by resolving Assets to Media within Core; no path may allow AIR or the scheduler to select Media as the scheduling unit.

## Failure Semantics

**Planning fault.** The scheduler or a scheduling artifact referenced Media as the schedulable unit, or playout selected content by Media without an Asset binding. Correct by ensuring all schedule compilation and horizon expansion uses Asset as the only schedulable entity and that Media appears only as the result of resolution from Asset to playable file.

## Required Tests

- `pkg/core/tests/contracts/test_asset_invariants.py::TestInvAssetMediaIdentity`

## Enforcement Evidence

TODO
