# INV-EXECUTIONENTRY-LOOKAHEAD-ENFORCED-001 — ExecutionEntry window extension is triggered by clock progression, not consumer demand

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-RUNTIME-AUTHORITY`

## Purpose

Ensures the ExecutionEntry window is extended proactively by clock advancement, not reactively by playout consumer requests. A demand-driven extension model allows the lookahead window to collapse silently when no consumer is active. When a viewer joins a dormant channel, the ExecutionEntry depth may be insufficient — leaving ChannelManager with no authorized execution content at the moment it is most needed. This invariant makes `LAW-RUNTIME-AUTHORITY` robust to viewer absence.

## Guarantee

ExecutionEntry rolling-window extension MUST be triggered by clock progression (specifically: when remaining execution window depth falls below `min_execution_hours` as measured against the current MasterClock time), not by consumer requests for content.

Extension MUST NOT be triggered when current depth already satisfies `min_execution_hours`. Redundant extension cycles waste compute and may produce duplicate entries.

This guarantee is subsumed by `INV-HORIZON-PROACTIVE-EXTEND-001` (extension fires only when `remaining_ms <= proactive_extend_threshold_ms`, triggered via `HorizonManager.evaluate_once()` which is clock-driven) and `INV-HORIZON-EXECUTION-MIN-001` (enforces `exec_depth_h >= min_execution_hours` at every evaluation exit). Together, these two invariants enforce the identical constraint: extension is clock-driven and does not fire when depth already satisfies the minimum.

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

- `pkg/core/tests/contracts/test_inv_horizon_proactive_extend.py` (TPX-001: no extension when remaining > proactive threshold)
- `pkg/core/tests/contracts/test_inv_horizon_proactive_extend.py` (TPX-002: extension when crossing threshold; depth increased)
- `pkg/core/tests/contracts/test_inv_horizon_proactive_extend.py` (TPX-005: idempotent per tick; no duplicate at same clock)
- `pkg/core/tests/contracts/test_inv_horizon_execution_min.py` (THEM-001: depth meets minimum after initialization)
- `pkg/core/tests/contracts/test_inv_horizon_execution_min.py` (THEM-002: depth maintained across 24h walk)

## Enforcement Evidence

- **Subsumed by:** `INV-HORIZON-PROACTIVE-EXTEND-001` + `INV-HORIZON-EXECUTION-MIN-001`. No dedicated guard exists for this invariant. The clock-driven extension model is enforced by the combination of these two horizon invariants.
- **Clock-only trigger:** `HorizonManager.evaluate_once()` in `pkg/core/src/retrovue/runtime/horizon_manager.py`. `_check_proactive_extend()` fires only when `remaining_ms <= proactive_extend_threshold_ms` — a pure clock comparison. No consumer-request code path triggers extension.
- **No-redundant-extension:** `_check_proactive_extend()` compares remaining time against the threshold. When depth already satisfies the minimum, no extension attempt is logged. TPX-001 and TPX-005 verify this directly.
- **Observability:** `HorizonManager.extension_attempt_log` records every attempt with `reason_code`. All successful extensions carry `reason_code="REASON_TIME_THRESHOLD"`, confirming clock-driven trigger. `extension_forbidden_trigger_count` tracks any attempted consumer-driven triggers.
- **Test files:** `test_inv_horizon_proactive_extend.py` (TPX-001..005) and `test_inv_horizon_execution_min.py` (THEM-001..004).
