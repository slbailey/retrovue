---

# 📘 RetroVue Architectural Roadmap v1.0

**Status:** Updated (Feb 2025)  
**Scope:** Core Runtime • Horizon • Execution Integration  
**Intent:** Accurately reflect present architectural maturity and remaining milestones  
**Note:** Checked against main branch, including pkg/core and integration with AIR

**Verification (Feb 2025):** Claims aligned with codebase. See "Verification notes" at end.

---

## 0️⃣ Achievements and Current System State (Checked Feb 2025)

### ✔️ Planning (COMPLETE)
- **Planning Pipeline** (`Directive → Locked TransmissionLog`): Implemented and verifiable. **[VERIFIED]**
- **Deterministic episode resolution:** In use; unit-tested in planning pipeline.
- **Synthetic/chapter-driven segmentation:** Deployed via `segment_blocks`, `SyntheticBreakProfile`, and `MarkerInfo` in planning pipeline.
- **Break filling with AssetLibrary:** Functional with deterministic ordering per current filler contract.
- **TransmissionLog wall-clock alignment:** Confirmed via block plans and active validation harness.

### ✔️ Horizon (MOSTLY COMPLETE)
- **Why “mostly”:** Extension is day-based only; a block-based extension API is not implemented (see Known Gaps).
- **Horizon authority:** HorizonManager is sole planning trigger; consumers read only. Consumer-triggered planning is prohibited; missing data raises `HorizonNoScheduleDataError`. (`horizon_config.py` — no LEGACY/SHADOW/AUTHORITATIVE modes.)
- **`HorizonManager` exists:** Extends by day (`extend_epg_day`, `extend_execution_day`). No block-based extension API.
- **Horizon-backed schedule service:** All runtime queries served from horizon store.
- **Planning failures surfaced:** Missing data surfaced as exceptions and reported.

### ✔️ Execution (MAINLINE READY)
- **BlockPlan conversion from TransmissionLog:** Stable and determines active segment boundaries. **[VERIFIED: `to_block_plan()`, `HorizonBackedScheduleService`, BlockPlanProducer.]**
- **AIR frame-count authority:** Enforced; integrated with core for playout segment emission.
- **Fence-based block timing:** Active and tested in 24-hour burn-in.
- **Hard-stop (wall-clock) discipline:** All playout plans respect TransmissionLog stop points.
- **Runway Min (INV-RUNWAY-MIN-001):** When queue_depth ≥ 3, AIR must not enter PADDED_GAP due to "no next block" except when ScheduleService returns None (true planning gap). **[VERIFIED: `docs/contracts/core/RunwayMinContract_v0.1.md`; INVARIANTS_INDEX Cross-Domain.]**

### ✔️ As-Run Reconciliation (CONTRACT DELIVERED)
- **AsRunReconciliationContract v0.1** and reconciler: Plan-vs-actual comparison (TransmissionLog vs AsRunLog); INV-ASRUN-001..005; structured report with classification. **[VERIFIED: `docs/contracts/core/AsRunReconciliationContract_v0.1.md`, `asrun_reconciler.py`, `test_asrun_reconciliation_contract.py`.]**
- Optional integration (reconciler invoked on execution path or AsRunLogger exporting AsRunLog) not yet wired.

### 🚧 Known Gaps (AS OF FEB 2025)
- **Core seam contract:** `docs/contracts/core/TransmissionLogSeamContract_v0.1.md` exists; INV-TL-SEAM-001..004 enforced in `lock_for_execution`. AIR frame-level INV-SEAM-* invariants live in `pkg/air/docs/contracts/`.
- **Horizon extension:** Day-based (`extend_epg_day`, `extend_execution_day`). Block-based API not implemented.
- **Deterministic filler policy:** Deterministic on identical inputs; pool partitioning (bumper/promo/ad) is planned but not yet shipped.
- **As-run logging:** `AsRunLogger` exists. **As-run reconciliation:** `docs/contracts/core/AsRunReconciliationContract_v0.1.md` and reconciler (`asrun_reconciler.py`, `asrun_types.py`) implemented; contract tests in `test_asrun_reconciliation_contract.py`. Optional integration (e.g. post-execution reconciliation run or AsRunLogger exporting AsRunLog) not yet wired.
- **Burn-in proof harness:** Exists as `tools/burn_in.py` (args: `--horizon`, `--schedule`, `--dump`). Use `--horizon` for contract-aligned runs; `--pipeline` removed. Not run in CI.

---

_This baseline reflects all foundational contracts implemented. Remaining gaps tracked and actively being worked._

---

## 🧱 Phase 1 — Structural Integrity Finalization

**Goal:** Broadcast-grade reliability  
**Status:** Most contracts implemented and enforced. See below for residual work.

### 1.1 **Seam Invariants** _(DELIVERED)_
- **`docs/contracts/core/TransmissionLogSeamContract_v0.1.md`** exists; wall-clock seam invariants INV-TL-SEAM-001..004 enforced in `transmission_log_validator.py` and `lock_for_execution`. Contract tests in `test_transmission_log_seam_contract.py`.
- AIR frame-level INV-SEAM-* invariants live in `pkg/air/docs/contracts/`.
- Seam contract tests run via pytest; burn-in runs manually via `tools/burn_in.py`.

### 1.2 **Rolling Horizon Enforcement** _(DELIVERED)_
- **HorizonManager** extends by day (`extend_epg_day`, `extend_execution_day`). No block-based API.
- Depth enforced via `min_epg_days` and `min_execution_hours`; horizon extension triggered when below thresholds.

### 1.3 **Deterministic Filler Policy** _(IN PROGRESS)_
- Seeded deterministic selection and per-break uniqueness are enforced.
- **Missing:** Pool partitioning (bumper/promo/ad), tracked for next sprint.

### 1.4 **24-Hour Burn-In Validation Harness** _(DELIVERED)_
- Harness: `tools/burn_in.py` with args `--horizon`, `--schedule`, `--dump`. `--horizon` is the contract-aligned mode; `--pipeline` has been removed. Not invoked in CI.
- All key invariants asserted:
  - Seam continuity
  - Horizon completeness
  - Pad and overlap checks
- Manual 24h runs pass; outputs archived.

---

## 🏛 Phase 2 — Operational Authority Hardening

**Goal:** Remove legacy code; fully contract-driven horizon.

### 2.1 **Remove Consumer Auto-Resolution Path** _(DELIVERED)_
- Missing schedule/execution data raises `HorizonNoScheduleDataError`; no consumer-triggered auto-resolve. (`ScheduleManagerBackedScheduleService`, `HorizonBackedScheduleService`.)

### 2.2 **As-Run Log Integration** _(RECONCILIATION DELIVERED)_
- `AsRunLogger` exists (`pkg/core/src/retrovue/runtime/asrun_logger.py`); logs actual block/segment times and transitions.
- **As-run reconciliation (DELIVERED):** `docs/contracts/core/AsRunReconciliationContract_v0.1.md`; INV-ASRUN-001..005; `asrun_types.py`, `asrun_reconciler.py`; contract tests in `test_asrun_reconciliation_contract.py`. Deterministic plan-vs-actual comparison with structured report (no auto-correct).
- **Optional follow-up:** Wire reconciler into execution path (e.g. post-playout reconciliation run or AsRunLogger exporting AsRunLog) — not required for contract closure.

### 2.3 **Execution Failure Escalation Path** _(DELIVERED)_
- All execution errors (missing block, corrupt segment, asset issues, AIR underrun) classified as planning vs. runtime.
- Contract language resolved; every failure raises clear error class in core and is reflected in test harness.

---

## 🚀 Phase 3 — Feature Expansion Layer

**_(Work may begin now that 2.2 As-Run reconciliation contract and reconciler are delivered; optional execution-path integration may follow in parallel.)_**

### 3.1 **Multi-Zone Authoring Enhancements** _(NOT STARTED)_
- Awaiting contract and spec refinement.
- Day-of-week filtering, inheritance, zone overrides _not yet in tree_.

### 3.2 **Traffic Manager (Basic)** _(NOT STARTED)_
- All core inventory/fill logic still located in AssetLibrary.
- No campaign/inventory pool or constraints present.
- Break slot rule engine under proposal.

### 3.3 **HLS / Multi-Viewer Scalability Layer** _(NOT STARTED)_
- Tooling for HLS block/segment alignment to be developed after traffic/horizon work.
- Contract written, implementation pending.

---

## 🧭 Locked Development Rules (All Enforced)

- **No new feature work outside current phase/milestone**
- **No UI expansion until Phase 2 complete**
- **No monetization/billing/reporting subsystems in repo**
- **Every subsystem requires contract doc**
- **Contracts define outcomes, not procedures**
- **Horizon is sole planning authority from Phase 2 onward**

---

**Summary:**  
_The baseline (Phase 1), seam/horizon authority, and burn-in validation are all live and tested. As-Run reconciliation (2.2) is delivered (contract + reconciler + contract tests). Optional integration of the reconciler into the execution path remains. Phase 3 (multi-zone, traffic, HLS) is not started. This document is maintained in sync with main pkg/core and integration requirements for AIR._

---

## Verification notes (Feb 2025)

Spot-check against the repo (main, pkg/core and tools):

| Claim | Status |
|-------|--------|
| **Planning:** Pipeline Directive→TransmissionLog | ✅ Verified: `planning_pipeline.py`, `run_planning_pipeline()`; contract tests in `test_planning_pipeline_contract.py`. |
| **Planning:** Deterministic episode resolution, break filling, AssetLibrary | ✅ Verified: `BreakFillPolicy`, break fill stage, `_deterministic_random_select` in schedule_manager; pipeline contract tests cover break fill. |
| **Planning:** TransmissionLog wall-clock alignment | ✅ Verified: assembly and lock stages; `to_block_plan()` in pipeline; seam validation in `lock_for_execution`. |
| **Execution:** BlockPlan from TransmissionLog, fence-based timing | ✅ Verified: `horizon_backed_schedule_service` converts TransmissionLog to BlockPlan format; `channel_manager.BlockPlanProducer`, `playout_session.BlockPlan`. |
| **Core seam contract:** TransmissionLogSeamContract_v0.1.md | ✅ Verified: `docs/contracts/core/TransmissionLogSeamContract_v0.1.md`; `transmission_log_validator.py`; contract tests in `test_transmission_log_seam_contract.py`. |
| **Horizon:** Day-based extension | ✅ Verified: `extend_epg_day`, `extend_execution_day`; no block-based API. |
| **Horizon:** Authority model | ✅ Verified: HorizonManager sole trigger; consumer reads only; `HorizonNoScheduleDataError` for missing data. |
| **Burn-in:** tools/burn_in.py | ✅ Verified: harness exists; `--horizon` primary, `--pipeline` removed; not run in CI. |
| **As-Run:** AsRunLogger | ✅ Verified: `AsRunLogger` in `asrun_logger.py`. |
| **As-Run reconciliation:** Contract + reconciler | ✅ Verified: `docs/contracts/core/AsRunReconciliationContract_v0.1.md`; `asrun_types.py`, `asrun_reconciler.py`; `reconcile_transmission_log()`; contract tests in `test_asrun_reconciliation_contract.py`. |
| **Runway Min (INV-RUNWAY-MIN-001)** | ✅ Verified: `docs/contracts/core/RunwayMinContract_v0.1.md`; operational promise (queue_depth ≥ 3 ⇒ no starvation PADDED_GAP except ScheduleService returns None). |
| **Phase 3:** Multi-zone, Traffic, HLS not started | ✅ Verified: no campaign/inventory or HLS implementation in tree. |

_Audit re-run: roadmap checked against current code (contracts, Core runtime, tools). Burn-in updated to reflect --pipeline removal._

---