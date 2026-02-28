# INV-PLAN-ELIGIBLE-ASSETS-ONLY-001 — Only eligible assets may be resolved from an active plan

Status: Invariant
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`, `LAW-CONTENT-AUTHORITY`

## Purpose

Prevents ineligible content from entering the scheduling derivation chain. Once an ineligible asset propagates into ScheduleDay, it contaminates Playlist and ExecutionEntry, creating a `LAW-ELIGIBILITY` violation at every downstream layer. This invariant enforces the gate at the earliest resolution point.

## Guarantee

All SchedulableAssets resolved from an active SchedulePlan's zones must be eligible (`state=ready` and `approved_for_broadcast=true`) at the time of ScheduleDay generation.

## Preconditions

- Plan `is_active = true`.
- ScheduleDay generation has been triggered for the channel and date covered by this plan.

## Observability

During ScheduleDay generation, each resolved SchedulableAsset is checked for eligibility. An ineligible asset MUST NOT be placed into the generated ScheduleDay. The violation (asset ID, ineligibility reason) MUST be logged. The affected zone must be filled with a declared filler or the generation must halt with an explicit eligibility fault.

## Deterministic Testability

Place an asset with `state=enriching` in a zone of an active plan. Trigger ScheduleDay generation. Assert that the ineligible asset is excluded from the output and a fault is raised. No real-time waits required.

## Failure Semantics

**Planning fault** if the operator placed an ineligible asset in a zone. **Runtime fault** if the asset was eligible at plan-creation time but became ineligible before ScheduleDay generation. In both cases the outcome is the same: the asset must not appear in the generated ScheduleDay.

## Required Tests

- `pkg/core/tests/contracts/test_inv_plan_eligible_assets_only.py` (test_reject_ineligible_asset_in_zone: ineligible asset rejected with invariant tag)
- `pkg/core/tests/contracts/test_inv_plan_eligible_assets_only.py` (test_accept_eligible_assets_in_zone: eligible assets accepted without error)
- `pkg/core/tests/contracts/test_inv_plan_eligible_assets_only.py` (test_reject_mixed_eligible_and_ineligible: mixed set rejected, ineligible asset identified)
- `pkg/core/tests/contracts/test_inv_plan_eligible_assets_only.py` (test_skip_check_when_no_resolver: backward compatible when no resolver provided)

## Enforcement Evidence

- **Guard function:** `check_asset_eligibility()` in `pkg/core/src/retrovue/usecases/zone_coverage_check.py`. Iterates all `schedulable_assets` in each enabled zone and calls the injected `asset_eligibility_checker(asset_id)` callable. Returns violations tagged `INV-PLAN-ELIGIBLE-ASSETS-ONLY-001-VIOLATED` for each ineligible asset.
- **Integration point:** `validate_zone_plan_integrity()` in the same file. Called from `zone_add.py` and `zone_update.py` before `db.commit()`. Accepts an optional `asset_eligibility_checker` parameter. When provided, eligibility is enforced after grid/overlap/coverage checks.
- **Violation tag:** `INV-PLAN-ELIGIBLE-ASSETS-ONLY-001-VIOLATED` with zone name and asset ID in the message.
- **Test file:** `pkg/core/tests/contracts/test_inv_plan_eligible_assets_only.py` — 4 tests, all pass.
