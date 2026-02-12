---

# 📘 RetroVue Architectural Roadmap v1.0

**Status:** Updated (as of Q2 2024)  
**Scope:** Core Runtime • Horizon • Execution Integration  
**Intent:** Accurately reflect present architectural maturity and remaining milestones  
**Note:** Checked against main branch, including pkg/core and integration with AIR

**Verification (Feb 2025):** Claims below were checked against the repo. Inline notes mark discrepancies; see "Verification notes" at end.

---

## 0️⃣ Achievements and Current System State (Checked Q2 2024)

### ✔️ Planning (COMPLETE)
- **Planning Pipeline** (`Directive → Locked TransmissionLog`): Implemented and verifiable. **[VERIFIED]**
- **Deterministic episode resolution:** In use; unit-tested in planning pipeline.
- **Synthetic/chapter-driven segmentation:** Deployed via `ScheduleItem` logic.
- **Break filling with AssetLibrary:** Functional with deterministic ordering per current filler contract.
- **TransmissionLog wall-clock alignment:** Confirmed via block plans and active validation harness.

### ✔️ Horizon (MOSTLY COMPLETE)
- **Horizon authority modes:** _legacy_ and _shadow_ removed; _authoritative_ is enforced default.  
  **[VERIFICATION:** Legacy and shadow are *not* removed—`horizon_config.py` still defines `LEGACY`, `SHADOW`, `AUTHORITATIVE`; default is `legacy` via `RETROVUE_HORIZON_AUTHORITY`. In authoritative mode, consumer auto-resolve is prohibited (INV-P5-005), but code paths remain.]**
- **`HorizonManager` exists:** Refactored for block-based extension (see below).  
  **[VERIFICATION:** HorizonManager exists and is used; it extends by *day* (`extend_epg_day`, `extend_execution_day`), not by block. No `ensure_horizon_blocks(channel_id, now, min_blocks_ahead)` API in repo.]**
- **Horizon-backed schedule service:** All runtime queries served from horizon store.
- **Planning failures surfaced in authoritative mode:** All surfaced as exceptions and reported.

### ✔️ Execution (MAINLINE READY)
- **BlockPlan conversion from TransmissionLog:** Stable and determines active segment boundaries. **[VERIFIED: `to_block_plan()`, `HorizonBackedScheduleService`, BlockPlanProducer.]**
- **AIR frame-count authority:** Enforced; integrated with core for playout segment emission.
- **Fence-based block timing:** Active and tested in 24-hour burn-in.
- **Hard-stop (wall-clock) discipline:** All playout plans respect TransmissionLog stop points.

### 🚧 Known Gaps (AS OF Q2 2024)
- **Seam scheduling:** Explicit contracts authored _and validated_ (see SeamContinuityContract_v0.1.md); enforced in 24h harness.  
  **[VERIFICATION:** `docs/contracts/SeamContinuityContract_v0.1.md` does *not* exist. INV-SEAM-* invariants live in `pkg/air/docs/contracts/` (AIR side).]**
- **Horizon extension:** Now block-based (no longer time) – rolled out in mainline. **[VERIFICATION:** HorizonManager is day-based in code; see Phase 1.2.]**
- **Deterministic filler policy:** Deterministic on identical inputs; pool partitioning (bumper/promo/ad) is planned but not yet shipped.
- **As-run logging:** Artifact created, but full reconciliation to TransmissionLog (INV-ASRUN-001) being finalized.
- **Burn-in proof harness:** Exists as `tools/burn_in.py`; continuous integration covers 24h horizon, with test artifacts. **[VERIFICATION:** Burn-in script exists; not run in CI (see Phase 1.4).]**

---

_This baseline reflects all foundational contracts implemented. Remaining gaps tracked and actively being worked._

---

## 🧱 Phase 1 — Structural Integrity Finalization

**Goal:** Broadcast-grade reliability  
**Status:** Most contracts implemented and enforced. See below for residual work.

### 1.1 **Seam Invariants** _(DELIVERED)_
- **`docs/contracts/SeamContinuityContract_v0.1.md` exists.**  
  **[VERIFICATION:** File not found in repo. Seam contracts live under `pkg/air/docs/contracts/`.]**
- All `INV-SEAM-00x` invariants enforced and tested in 24h runs.
- **Validation harness** in CI asserts seam continuity on every commit.  
  **[VERIFICATION:** `pkg/core/.github/workflows/test-workflow.yml` does *not* run burn_in or seam tests; CI runs Source/Enricher/Collection/Asset contract tests only.]**

### 1.2 **Rolling Block-Based Horizon Enforcement** _(DELIVERED)_
- **HorizonManager** now extends by block, not time.  
  **[VERIFICATION:** HorizonManager extends by *day* (`_extend_epg`, `_extend_execution` → `extend_epg_day`, `extend_execution_day`). No block-based extension API in Core.]**
- API `ensure_horizon_blocks(channel_id, now, min_blocks_ahead)` is active and covered by integration tests.  
  **[VERIFICATION:** No such function in `horizon_manager.py` or elsewhere.]**
- **No `HorizonNoScheduleDataError`** observed in authoritative mode since deployment.

### 1.3 **Deterministic Filler Policy** _(IN PROGRESS)_
- Seeded deterministic selection and per-break uniqueness are enforced.
- **Missing:** Pool partitioning (bumper/promo/ad), tracked for next sprint.

### 1.4 **24-Hour Burn-In Validation Harness** _(DELIVERED)_
- `burn_in_channel(channel_id, hours=24)` runs in CI.  
  **[VERIFICATION:** Harness is `tools/burn_in.py` (args: `--horizon`, `--pipeline`, `--schedule`, `--dump`). No function `burn_in_channel`; no `hours=24` parameter. Burn-in is *not* invoked in `pkg/core/.github/workflows/test-workflow.yml`.]**
- All key invariants asserted:
  - Seam continuity
  - Horizon completeness
  - Pad and overlap checks
- Regular 24h runs pass without errors; outputs archived.

---

## 🏛 Phase 2 — Operational Authority Hardening

**Goal:** Remove legacy code; fully contract-driven horizon.

### 2.1 **Remove Consumer Auto-Resolution Path** _(DELIVERED)_
- Legacy and shadow paths deleted.  
  **[VERIFICATION:** Paths are *not* deleted. `schedule_manager_service.py` still branches on `_horizon_mode`; when not AUTHORITATIVE it runs "Legacy / shadow: auto-resolve (INV-P5-002)". Authoritative mode raises instead of resolving.]**
- Only authoritative planning used in prod/runtime.

### 2.2 **As-Run Log Integration** _(PARTIAL/NEARLY COMPLETE)_
- `AsRunLogArtifact` created; logs actual block/segment times and transitions.  
  **[VERIFICATION:** No type or module named `AsRunLogArtifact` in repo. `AsRunLogger` class exists in `pkg/core/src/retrovue/runtime/asrun_logger.py`.]**
- **Remaining TODO:** Automated reconciliation to TransmissionLog on all execution unless error (INV-ASRUN-001).  
  **[VERIFICATION:** No contract file `INV-ASRUN-001` found in repo.]**
- **Target:** Complete artifact checks by end of current milestone.

### 2.3 **Execution Failure Escalation Path** _(DELIVERED)_
- All execution errors (missing block, corrupt segment, asset issues, AIR underrun) classified as planning vs. runtime.
- Contract language resolved; every failure raises clear error class in core and is reflected in test harness.

---

## 🚀 Phase 3 — Feature Expansion Layer

**_(Work may begin after 2.2/INV-ASRUN-001 is fully satisfied; others READY)_**

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
_The baseline (Phase 1), seam/horizon authority, and burn-in validation are all live and tested. As-Run logging reconciliation (2.2) is the only significant open contract; all else in roadmap represents next-growth and is not started. This document is maintained in sync with main pkg/core and integration requirements for AIR._

---

## Verification notes (Feb 2025)

Spot-check against the repo (main, pkg/core and tools):

| Claim | Status |
|-------|--------|
| **Planning:** Pipeline Directive→TransmissionLog | ✅ Verified: `planning_pipeline.py`, `run_planning_pipeline()`; contract tests in `test_planning_pipeline_contract.py`. |
| **Planning:** Deterministic episode resolution, break filling, AssetLibrary | ✅ Verified: `BreakFillPolicy`, break fill stage, `_deterministic_random_select` in schedule_manager; pipeline contract tests cover break fill. |
| **Planning:** TransmissionLog wall-clock alignment | ✅ Verified: assembly and lock stages; `to_block_plan()` in pipeline. |
| **Execution:** BlockPlan from TransmissionLog, fence-based timing | ✅ Verified: `horizon_backed_schedule_service` converts TransmissionLog to BlockPlan format; `channel_manager.BlockPlanProducer`, `playout_session.BlockPlan`. |
| **Horizon:** SeamContinuityContract_v0.1.md in docs/contracts | ❌ File does not exist. Seam invariants are in pkg/air. |
| **Horizon:** Block-based extension, ensure_horizon_blocks | ❌ HorizonManager extends by day only; no `ensure_horizon_blocks` API. |
| **Horizon:** Legacy/shadow “removed”, authoritative default | ❌ Legacy/shadow still in code; default is `legacy`. Authoritative is opt-in via env. |
| **Burn-in:** burn_in_channel(…, hours=24) in CI | ❌ Harness is `tools/burn_in.py`; no such function or param; burn_in not run in GitHub Actions. |
| **Seam:** CI asserts seam continuity every commit | ❌ No burn_in or seam tests in test-workflow.yml. |
| **As-Run:** AsRunLogArtifact type | ❌ No such type; `AsRunLogger` exists. INV-ASRUN-001 contract file not found. |
| **Phase 3:** Multi-zone, Traffic, HLS not started | ✅ Verified: no campaign/inventory or HLS implementation in tree. |

**Recommendations:** Align roadmap wording with code: (1) either add `SeamContinuityContract_v0.1.md` under docs/contracts (or point to AIR contracts), (2) describe horizon extension as day-based unless block-based API is added, (3) replace “burn_in_channel(…)” with “tools/burn_in.py” and clarify CI vs manual 24h runs, (4) use “AsRunLogger” and clarify reconciliation contract location.

---