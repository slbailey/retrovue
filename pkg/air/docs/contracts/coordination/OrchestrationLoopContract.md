# Orchestration Loop Contract [AIR-016]

> **Status:** Canonicalized from legacy — migrated from `docs/legacy/air/contracts/OrchestrationLoopDomainContract.md` (no longer present as separate file).
> **Canonical home:** This document.
> **Ledger ID:** AIR-016.
> **Governance audit:** 2025-07-14.

---

## Purpose

This contract defines the timing and recovery guarantees for the Air orchestration loop — the central tick-driven mechanism that coordinates producer, renderer, and output pipeline components.

---

## 1. Tick Timing [AIR-016 §Timing]

> *Canonicalized from legacy contract. Meaning preserved exactly.*

- Tick skew MUST remain within ±1 ms for 99% of ticks under normal operation.
- Producer-to-renderer latency (p95) MUST be ≤ 33 ms.
- A missed MasterClock callback MUST trigger an immediate catch-up tick; missed callbacks MUST NOT be silently dropped.

**Violation condition:** Tick skew exceeds ±1 ms for more than 1% of ticks; p95 latency exceeds 33 ms; missed callback produces no catch-up tick.

---

## 2. Underrun and Overrun Recovery [AIR-016 §Recovery]

> *Canonicalized from legacy contract. Meaning preserved exactly.*

- **Underrun:** When the output pipeline drains below threshold, normal output MUST be restored within ≤ 3 ticks.
- **Overrun:** When the output pipeline exceeds capacity, excess MUST be drained within ≤ 3 ticks.
- Recovery time from any underrun or overrun condition MUST be ≤ 100 ms.

**Violation condition:** Underrun takes more than 3 ticks to recover; overrun takes more than 3 ticks to drain; recovery exceeds 100 ms.

---

## 3. Starvation Detection and Teardown [AIR-016 §Starvation]

> *Canonicalized from legacy contract. Meaning preserved exactly.*

- Content starvation (no frames available when expected) MUST be detected within ≤ 100 ms.
- Teardown of the orchestration loop MUST complete within ≤ 500 ms.

**Violation condition:** Starvation not detected within 100 ms; teardown exceeds 500 ms.

---

## Test Requirements (Missing)

The following tests are required but not yet implemented. This is a test authoring gap, not a doc gap.

| Test ID (proposed) | Requirement |
|---------------------|-------------|
| TEST-P10-ORCH-TICK-SKEW | Tick skew ≤ ±1 ms for 99% of ticks over N-tick window |
| TEST-P10-ORCH-RECOVERY | Underrun restores within ≤ 3 ticks; overrun drains within ≤ 3 ticks |
| TEST-P10-ORCH-TEARDOWN | Teardown completes within ≤ 500 ms |

All three are blocked by missing harness infrastructure (deterministic tick injection). See [TEST_ANCHOR_BACKLOG.md](../../../docs/contracts/audit/TEST_ANCHOR_BACKLOG.md) §P3.

---

## Derived From

- **LAW-LIVENESS** — Continuous emission requirement implies the orchestration loop must recover without silent stall.
- **LAW-CLOCK** — MasterClock callbacks drive the tick; missed callbacks must be caught up.

---

## Related

- [OutputBusAndOutputSinkContract.md](OutputBusAndOutputSinkContract.md) — Sink receives frames from the orchestration pipeline.
- [PHASE2_NORMALIZED_RULES.md](../../../docs/contracts/audit/PHASE2_NORMALIZED_RULES.md) — AIR-016 normalized definition.
- [OBS-002 (ledger)](../../../docs/contracts/CANONICAL_RULE_LEDGER.md) — Orchestration telemetry metrics (pending migration).
