# REFACTOR_STATE.md — Live Execution State

> This file is the chain link between turns. Every agent turn MUST:
> 1. Read this file first
> 2. Do ONE atomic sub-step only
> 3. Mark it done and set the next sub-step
> 4. Commit and report

---

## Overall Goal
Aggressive (L3) complexity reduction. Single source of truth per concern.
Full constraints: `/opt/retrovue/SIMPLIFICATION_PLAN_V1.md`
Branch: `refactor/simplify-single-authority-l3`

---

## Current Phase: 3 — Contract Overlap Reduction

## Sub-steps (do ONE per turn, mark [x] when done):

- [x] **3a** — Audit contract files for tests that assert internal sequencing (not required invariants). Produce a candidate list of tests/classes to retire. Write findings to `/opt/retrovue/PHASE3_CONTRACT_AUDIT.md`. Do NOT delete anything yet. Run tests (must stay >= 328). DONE: 334 pass.
- [x] **3b** — Retire 4 internal/meta tests from `test_frame_selection_cadence_contract.py`: test_buggy_cascade_violates_pop_invariant, test_buggy_consumption_ratio_is_1_0, test_accumulator_budget_bounded, test_60_to_30_cadence_half. Expected: 334-4=330 pass (floor 328). DONE: 330 pass. Commit: be7edd6.
- [ ] **3c** — Per audit: no second retirement possible within floor constraint (headroom only 2 after 3b). Update state to reflect this and move to 3d.
- [ ] **3d** — Move to Phase 4: Diagnostics isolation audit.

## NEXT SUB-STEP: 3c

---

## Phase 2 — COMPLETED

Sub-steps completed:
- [x] **2a** — Write contract test: "CM never calls PD.stop_channel directly" (FAIL before code change).
- [x] **2b** — Delete dead code: deferred_teardown_triggered() + poll call in PD._health_check_loop.
- [x] **2c** — Delete dead code: compute_jip_position() from ChannelManager.
- [x] **2d** — Delete dead code: _mock_grid_* methods from ChannelManager.
- [x] **2e** — Invert linger callback: add on_linger_expired: Callable to ChannelManager.__init__.
- [x] **2f** — Wire PD side: inject on_linger_expired=self._stop_channel_internal. Contract GREEN.
- [x] **2g** — Inject MasterClock into DslScheduleService; replace 2x bare datetime.now().
- [x] **2h** — Audit remaining datetime.now() in dsl_schedule_service.py. Result: CLEAN.
  - No bare datetime.now() calls remain.
  - _maybe_extend_horizon receives now_utc_ms from ChannelManager caller correctly.
  - _purge_expired_program_schedule fallback uses self._clock.now_utc() (MasterClock injected).
  - 334 pass, 2 pre-existing failures unrelated to this phase.

---

## Completed Work Log
| Turn | Date | Commit | What Was Done |
|------|------|--------|---------------|
| 0 | 2026-03-28 | 6154e89 | Created branch, committed plan, captured test baseline (328p/2f) |
| 0b | 2026-03-28 | a0168ea | Added REFACTOR_STATE.md |
| 1 | 2026-03-28 | 2488974 | Authority overlap map produced |
| 1b | 2026-03-28 | 293c545 | REFACTOR_STATE.md updated to phase 2 |
| wip | 2026-03-28 | 0683216 | Safety check committed leftover AIR files from pre-branch work |
| 2a | 2026-03-28 | 27d1982 | Contract test INV-LIFECYCLE-PD-SOLE-TEARDOWN-001 added (6 tests RED as expected, 328 still pass) |
| 2b | 2026-03-28 | c81d328 | Deleted deferred_teardown_triggered() and PD poll block (13 lines removed; 330 pass) |
| 2c | 2026-03-28 | 39ded8f | Deleted compute_jip_position() 58 lines; 331 pass |
| 2d | 2026-03-28 | 522b298 | Deleted _mock_grid_* methods; 333 pass |
| 2e | 2026-03-28 | e396513 | Add on_linger_expired callback to ChannelManager, invert linger dep; 333 pass |
| 2f | 2026-03-28 | 1ce56d8 | Wire PD: inject on_linger_expired=self._stop_channel_internal; 334 pass, contract GREEN |
| 2g | 2026-03-28 | 652521f | Inject MasterClock into DslScheduleService; replace 2x bare datetime.now(); 334 pass |
| 2h | 2026-03-28 | 0f326e1 | Audit dsl_schedule_service.py datetime.now() — CLEAN; Phase 2 complete; 334 pass |

---

## Blockers / Notes
- Timeout was 300s — increased to 600s
- One atomic action per turn rule added to prevent timeout mid-work
- AIR files in wip commit (0683216) are pre-existing uncommitted work from main, not part of refactor
- 2 pre-existing test failures in test_interstitial_enrichment.py (unmatched_directory and known_type_directory filler defaults) — NOT caused by this branch
