# INV-EXECUTIONENTRY-ELIGIBLE-CONTENT-001 — All assets in the active ExecutionEntry window must be eligible

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-ELIGIBILITY`, `LAW-DERIVATION`

## Purpose

Prevents ineligible content from reaching the execution layer. An asset may become ineligible (e.g., `approved_for_broadcast` revoked) after its TransmissionLogEntry was generated. `LAW-ELIGIBILITY` requires the gate to hold at every layer, including runtime. An ineligible asset in the active ExecutionEntry window would be played unconditionally by ChannelManager.

## Guarantee

All assets referenced by ExecutionEntry records within the active and locked execution window must be eligible (`state=ready` and `approved_for_broadcast=true`) at the time the entry enters that window.

## Preconditions

- The ExecutionEntry is within the active or locked execution window (i.e., within the lookahead horizon managed by HorizonManager).

## Observability

At each rolling-window extension, HorizonManager MUST verify eligibility of all assets being added to the active window. If an asset has become ineligible since its TransmissionLogEntry was generated, the entry MUST be replaced with a declared filler and the violation MUST be logged (asset ID, channel ID, ineligibility reason). Silent use of ineligible content is unconditionally prohibited.

## Deterministic Testability

Create an ExecutionEntry referencing an asset. Downgrade the asset to `state=enriching` via the domain layer. Trigger a rolling-window extension that includes this entry. Assert the entry is replaced with filler and a violation is logged. No real-time waits required; advance clock deterministically to the extension trigger point.

## Failure Semantics

**Runtime fault.** The asset's eligibility changed after the TransmissionLogEntry was derived. HorizonManager must detect and handle this; it is not a planning error.

## Required Tests

- `pkg/core/tests/contracts/test_inv_playlog_eligible_content.py`

## Enforcement Evidence

- **Eligibility gate at plan level:** `test_inv_plan_eligible_assets_only.py` enforces that only assets with `state=ready` and `approved_for_broadcast=true` enter the planning pipeline — ineligible assets are rejected before they reach `ExecutionEntry` generation.
- `ScheduleManagerService` validates asset eligibility during planning pipeline execution, prior to writing entries to `ExecutionWindowStore`.
- **Rolling-window verification:** `HorizonManager` is responsible for re-verifying eligibility at each rolling-window extension — an asset that became ineligible after its `TransmissionLogEntry` was generated must be replaced with declared filler.
- Dedicated contract test (`test_inv_playlog_eligible_content.py`) for runtime-level eligibility verification is referenced in `## Required Tests` but not yet implemented in the current tree.
