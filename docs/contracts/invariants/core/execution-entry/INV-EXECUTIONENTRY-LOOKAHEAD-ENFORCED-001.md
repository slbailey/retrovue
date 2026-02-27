# INV-EXECUTIONENTRY-LOOKAHEAD-ENFORCED-001 — ExecutionEntry window extension is triggered by clock progression, not consumer demand

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-RUNTIME-AUTHORITY`

## Purpose

Ensures the ExecutionEntry window is extended proactively by clock advancement, not reactively by playout consumer requests. A demand-driven extension model allows the lookahead window to collapse silently when no consumer is active. When a viewer joins a dormant channel, the ExecutionEntry depth may be insufficient — leaving ChannelManager with no authorized execution content at the moment it is most needed. This invariant makes `LAW-RUNTIME-AUTHORITY` robust to viewer absence.

## Guarantee

ExecutionEntry rolling-window extension MUST be triggered by clock progression (specifically: when remaining execution window depth falls below `min_execution_hours` as measured against the current MasterClock time), not by consumer requests for content.

Extension MUST NOT be triggered when current depth already satisfies `min_execution_hours`. Redundant extension cycles waste compute and may produce duplicate entries.

## Preconditions

- Channel has an active playout session (a playout session has been started, regardless of whether viewers are currently connected).
- `min_execution_hours` is declared as a deployment-configurable value, injected into HorizonManager at initialization.

## Observability

HorizonManager MUST log the reason code for each extension attempt. Reason code MUST be `clock_progression`. Reason code `consumer_demand` or any variant is a violation. Extension cycles that fire when depth >= `min_execution_hours` are logged as redundant extension violations.

## Deterministic Testability

Using FakeAdvancingClock: advance the clock without simulating any playout consumer requests. Assert that extension is triggered when remaining depth falls below `min_execution_hours`. Assert that no extension is triggered when depth is already >= `min_execution_hours`. Assert extension reason code is `clock_progression` in all triggered cases. No real-time waits required.

## Failure Semantics

**Runtime fault.** Extension triggered by consumer demand indicates a design flaw in the HorizonManager trigger model. Extension triggered when depth is already sufficient indicates a redundant cycle bug.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_constitution.py` (HORIZON-001, HORIZON-002)

## Enforcement Evidence

TODO
