# INV-MATERIAL-RESOLVED-BEFORE-HORIZON-ENTRY-001 — All asset references must be resolved to physical paths before execution horizon entry

Status: Invariant
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`, `LAW-RUNTIME-AUTHORITY`

## Purpose

`LAW-RUNTIME-AUTHORITY` guarantees that ChannelManager consumes pre-built, execution-ready data — not data requiring further resolution at playout time. `LAW-ELIGIBILITY` requires that only ready, approved assets appear in any scheduling artifact.

An unresolved asset reference inside the execution horizon — a symbolic program ID, a virtual asset placeholder, a `NULL` path, or an unapproved asset — is a deferred planning obligation smuggled into the execution layer. When ChannelManager encounters it at block boundary, it must either compensate (violating `INV-CHANNELMANAGER-NO-PLANNING-001`) or fail (a planning fault that manifests as a runtime event). Neither outcome is acceptable. The resolution failure belongs at planning time, not at playout time.

See also: `ScheduleHorizonManagementContract_v0.1.md §7`, `ScheduleExecutionInterfaceContract_v0.1.md §6`, `ScheduleManagerPlanningAuthority_v0.1.md §Material Association`.

## Guarantee

Every ExecutionWindowStore entry MUST satisfy all of the following before it is committed to the store:

1. All segment `asset_uri` values are resolved to a physical, addressable path or stable URI — no symbolic references, no virtual asset placeholders, no `NULL`.
2. All referenced assets have `state=ready` and `approved_for_broadcast=true` at the time the entry is committed to the store.
3. All referenced asset paths are reachable and non-empty (validated at build time, not at playout time).

An ExecutionWindowStore entry that fails any of these conditions MUST NOT be added to the store. The failure MUST be surfaced as a planning fault with the unresolved reference identified.

## Preconditions

- `ExecutionWindowStore.add_entries()` is the sole write path for execution entries.
- Asset resolution is performed by the planning pipeline (HorizonManager / schedule compilation) before calling `add_entries()`.
- `lock_horizon_depth` defines the horizon; only entries within the proactive extension window are subject to this invariant at write time.

## Observability

`add_entries()` MUST validate each entry for resolved asset references before accepting it. Any entry with an unresolved reference MUST be rejected with a log entry containing:
- `fault_class = "planning"`
- `block_id` of the rejected entry
- `segment_index` of the offending segment
- `asset_uri` value (or `NULL`) that failed resolution
- Reason: `"unresolved_asset_reference"` or `"asset_ineligible_at_horizon_entry"`

## Deterministic Testability

Using InMemoryAssetLibrary: register an asset as `state=enriching`. Attempt to build an ExecutionEntry using that asset and call `ExecutionWindowStore.add_entries()`. Assert the entry is rejected. Separately, register the asset as `state=ready, approved_for_broadcast=true`. Build the entry. Assert the entry is accepted. No real-time waits required. No network calls required.

## Failure Semantics

**Planning fault.** An unresolved asset reference in the execution horizon is a planning pipeline failure — the planning layer did not complete its work before delivering data to the execution boundary. ChannelManager is not responsible for detecting or recovering from this condition.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_constitution.py` (MATERIAL-RESOLVED-001, MATERIAL-RESOLVED-002)

## Enforcement Evidence

TODO
