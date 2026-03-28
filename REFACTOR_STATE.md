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

## Current Phase: 2 — Lifecycle Hardening

## Sub-steps (do ONE per turn, mark [x] when done):

- [ ] **2a** — Write contract test: "CM never calls PD.stop_channel directly" (test must FAIL before code change). File: `tests/contracts/test_lifecycle_authority.py`
- [ ] **2b** — Delete dead code: `deferred_teardown_triggered()` in `pkg/core/runtime/channel_manager.py` + its poll call in `ProgramDirector._health_check_loop`. Run tests (must stay >= 328).
- [ ] **2c** — Delete dead code: `compute_jip_position()` from `pkg/core/runtime/channel_manager.py`. Run tests.
- [ ] **2d** — Delete dead code: `_mock_grid_*` methods from `pkg/core/runtime/channel_manager.py` (`_floor_to_grid`, `_calculate_join_offset`, `_calculate_filler_offset`, `_determine_active_content`, `_build_mock_grid_playout_plan`). Run tests.
- [ ] **2e** — Invert linger callback: add `on_linger_expired: Callable` param to `ChannelManager.__init__`. Update `_linger_expire()` and `_start_linger()` to call `self.on_linger_expired()` instead of `program_director.stop_channel()`. Run tests.
- [ ] **2f** — Wire PD side: update `ProgramDirector._create_channel_manager()` to inject `on_linger_expired=self._stop_channel_internal`. Run tests. Contract test from 2a should now PASS.
- [ ] **2g** — Inject MasterClock into DslScheduleService: replace bare `datetime.now(timezone.utc)` in `_purge_expired_program_schedule` and `_maybe_extend_horizon`. Run tests.

## NEXT SUB-STEP: 2a

---

## Completed Work Log
| Turn | Date | Commit | What Was Done |
|------|------|--------|---------------|
| 0 | 2026-03-28 | 6154e89 | Created branch, committed plan, captured test baseline (328p/2f) |
| 0b | 2026-03-28 | a0168ea | Added REFACTOR_STATE.md |
| 1 | 2026-03-28 | 2488974 | Authority overlap map produced |
| 1b | 2026-03-28 | 293c545 | REFACTOR_STATE.md updated to phase 2 |
| wip | 2026-03-28 | 0683216 | Safety check committed leftover AIR files from pre-branch work |

---

## Blockers / Notes
- Timeout was 300s — increased to 600s
- One atomic action per turn rule added to prevent timeout mid-work
- AIR files in wip commit (0683216) are pre-existing uncommitted work from main, not part of refactor — may need review
