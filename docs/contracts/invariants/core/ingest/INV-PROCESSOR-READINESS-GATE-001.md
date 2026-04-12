# INV-PROCESSOR-READINESS-GATE-001 — Required processors must complete before ready

Status: Invariant
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`, `LAW-DERIVATION`

## Purpose

An asset that reaches `ready` without all required processors having run creates a false eligibility signal. Scheduling would select content with incomplete metadata, producing unreliable block plans. This invariant ensures that processors declared with `required_for_readiness=True` act as explicit gates on the `ready` transition.

## Guarantee

An asset MUST NOT transition to `state = 'ready'` unless every processor with `required_for_readiness=True` in `CAPABILITY_REGISTRY` has completed and its `produced_metadata` fields are populated on the asset.

## Preconditions

`CAPABILITY_REGISTRY` MUST contain at least one processor with `required_for_readiness=True`. The validation pipeline MUST include a readiness gate check before auto-approval.

## Observability

When an asset is blocked because a required processor has not run, the validation result MUST include an error entry identifying the missing processor (error code: `READINESS_PROCESSOR_INCOMPLETE`, message includes processor_id).

## Deterministic Testability

Construct a `SimpleNamespace` asset with all ffprobe-produced metadata populated and assert the readiness gate passes. Repeat with `duration_ms=None` (ffprobe field missing) and assert the gate fails with `READINESS_PROCESSOR_INCOMPLETE`. No real database, media files, or wall-clock waits required.

## Failure Semantics

**Enrichment fault.** A required processor has not yet run or failed to produce its declared metadata. The asset remains in its current state for re-processing or manual investigation.

## Required Tests

- `server/tests/contracts/ingest/test_readiness_gate.py`

## Enforcement Evidence

TODO
