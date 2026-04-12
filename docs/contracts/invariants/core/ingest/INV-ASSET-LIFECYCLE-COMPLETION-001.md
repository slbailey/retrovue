# INV-ASSET-LIFECYCLE-COMPLETION-001 — Asset state must not remain "enriching" after job completion

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring every asset reaches a terminal or actionable state after its processor jobs complete. An asset stuck in "enriching" is invisible to scheduling (not "ready") and invisible to operator review (not "new"), creating a silent deadlock that requires manual SQL intervention.

## Guarantee

After `execute_job()` completes — whether successfully, partially, or by exception — the target asset's state MUST be one of:

- `"ready"`: all completion conditions met (duration_ms > 0)
- `"new"`: completion conditions not met but no permanent failure
- `"retired"`: operator-initiated removal

The state MUST NOT remain `"enriching"`. The state transition MUST execute on every code path through `execute_job()`, including the exception path.

## Preconditions

- The asset exists and is not soft-deleted.
- At least one processor job was enqueued for the asset.

## Observability

`SELECT COUNT(*) FROM assets WHERE state = 'enriching'` MUST trend toward zero after worker drains the queue. Any non-zero count after queue drain is a violation.

## Deterministic Testability

1. Simulate `execute_job()` with a processor that raises.
2. Assert asset state is not "enriching" after the exception.
3. Simulate `execute_job()` with all processors succeeding but no duration_ms.
4. Assert asset state is "new" (not "enriching").
5. Simulate `execute_job()` with duration_ms set.
6. Assert asset state is "ready".

## Failure Semantics

**Planning fault.** Assets stuck in "enriching" are excluded from all scheduling pipelines and operator review queues.

## Required Tests

- `server/tests/contracts/test_inv_asset_lifecycle_completion.py`

## Enforcement Evidence

TODO
