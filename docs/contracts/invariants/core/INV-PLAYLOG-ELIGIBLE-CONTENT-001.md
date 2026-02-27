# INV-PLAYLOG-ELIGIBLE-CONTENT-001 — All assets in the active Playlog must be eligible

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-ELIGIBILITY`, `LAW-DERIVATION`

## Purpose

Prevents ineligible content from reaching the execution layer. An asset may become ineligible (e.g., `approved_for_broadcast` revoked) after its Playlist entry was generated. `LAW-ELIGIBILITY` requires the gate to hold at every layer, including runtime. An ineligible asset in the active PlaylogEvent window would be played unconditionally by ChannelManager.

## Guarantee

All assets referenced by PlaylogEvent entries within the active and locked execution window must be eligible (`state=ready` and `approved_for_broadcast=true`) at the time the entry enters that window.

## Preconditions

- The PlaylogEvent entry is within the active or locked execution window (i.e., within the lookahead horizon managed by the PlaylogService).

## Observability

At each rolling-window extension, the PlaylogService MUST verify eligibility of all assets being added to the active window. If an asset has become ineligible since its Playlist entry was generated, the entry MUST be replaced with a declared filler and the violation MUST be logged (asset ID, channel ID, ineligibility reason). Silent use of ineligible content is unconditionally prohibited.

## Deterministic Testability

Create a PlaylogEvent referencing an asset. Downgrade the asset to `state=enriching` via the domain layer. Trigger a rolling-window extension that includes this entry. Assert the entry is replaced with filler and a violation is logged. No real-time waits required; advance clock deterministically to the extension trigger point.

## Failure Semantics

**Runtime fault.** The asset's eligibility changed after the Playlist entry was derived. The PlaylogService must detect and handle this; it is not a planning error.

## Required Tests

- `pkg/core/tests/contracts/test_inv_playlog_eligible_content.py`

## Enforcement Evidence

TODO
