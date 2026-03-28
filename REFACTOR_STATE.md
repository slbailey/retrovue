# REFACTOR_STATE.md — Live Execution State

> This file is the chain link between turns. Every agent turn MUST read this first, do work, then update this file last before exiting.

---

## Overall Goal
Aggressive (L3) complexity reduction of Retrovue codebase.
- Single source of truth per concern (clock, segment window, lifecycle, diagnostics)
- No backward compat. Delete dead paths.
- Separate branch: `refactor/simplify-single-authority-l3`
- PR-sized rollback units
- Done when: single ownership map enforced, contract overlap reduced, reconnect hardened, fewer cross-component touches per feature

Full locked constraints: `/opt/retrovue/SIMPLIFICATION_PLAN_V1.md`

---

## Current Phase: 1 — COMPLETE

## Phase 1 Summary (2026-03-28)
- Commit: `2488974`
- File: `docs/architecture/AUTHORITY_MAP.md`
- Authority map produced for 4 concerns: clock, segment-window, lifecycle, diagnostics
- Baseline tests: 328 passed / 2 failed (pre-existing)

---

## Next Phase: 2 — Lifecycle Hardening

### What to do next turn:
1. **Invert the linger callback** in `runtime/channel_manager.py`:
   - CM currently calls `program_director.stop_channel()` directly from `_linger_expire()`
   - Change: CM exposes `on_linger_expired: Callable` injected by PD at creation
   - CM calls `self.on_linger_expired()` instead of `program_director.stop_channel()`
   - PD registers a handler that calls `_stop_channel_internal`
   - This removes the CM→PD dependency
2. **Delete dead code** (L3 rule — no legacy):
   - `deferred_teardown_triggered()` in ChannelManager (BlockPlan path always returns False)
   - Remove the poll loop call in `ProgramDirector._health_check_loop`
   - `compute_jip_position()` in ChannelManager (deprecated, legacy)
   - `_mock_grid_*` methods on ChannelManager (`_floor_to_grid`, `_calculate_join_offset`, `_calculate_filler_offset`, `_determine_active_content`, `_build_mock_grid_playout_plan`)
3. **Add contract test**: "PD is sole teardown decision point — CM never calls PD.stop_channel directly"
4. **Run tests**: `cd /opt/retrovue && pkg/core/.venv/bin/python -m pytest tests/contracts -m "contract and not soak" -q --tb=no`
5. **Update this file** and commit all changes together

### Key files:
- `pkg/core/runtime/channel_manager.py`
- `pkg/core/runtime/program_director.py`
- `tests/contracts/` (add new test)

---

## Completed Work Log
| Turn | Date | Commit | What Was Done |
|------|------|--------|---------------|
| 0 | 2026-03-28 | 6154e89 | Created branch, committed plan, captured test baseline (328p/2f) |
| 0b | 2026-03-28 | a0168ea | Added REFACTOR_STATE.md chain state file |
| 1 | 2026-03-28 | 2488974 | Authority overlap map — 4 concerns mapped, 3 dead paths identified, HIGH overlap in lifecycle |

---

## Blockers / Notes
- Anthropic API overload error killed last turn before REFACTOR_STATE.md could be updated — state manually corrected
- Phase 2 is the highest-risk phase (lifecycle inversion). Contract test must come BEFORE code change.
