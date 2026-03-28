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

## Current Phase: 0 — COMPLETE

## Baseline (captured 2026-03-28)
- Branch: `refactor/simplify-single-authority-l3`
- Last commit: `6154e89` (plan file committed)
- Test baseline: **328 passed / 2 failed** (pre-existing failures in `test_interstitial_enrichment.py`)
- AIR C++ contract tests: NOT YET RUN (need build verification first)
- Unstaged on main at branch point: `SeamPreparer.hpp`, `PipelineManager.cpp`, `SeamPreparer.cpp`

---

## Next Phase: 1 — Authority Overlap Map

### What to do next turn:
1. Map current authority holders for each concern:
   - **Clock/timebase** — who decides "what time is it now" for playout decisions?
   - **Segment-window** — who owns the HLS window state?
   - **Channel lifecycle** — who decides start/stop/reconnect?
   - **Diagnostics** — who controls diagnostic mode activation/expiry?
2. Find duplicate decision points (files/classes that have secondary authority over any concern)
3. Write findings to `docs/architecture/AUTHORITY_MAP.md`
4. Commit the map
5. Update this file with: what was found, which overlaps are highest priority to fix, next phase action

### Key files to examine for Phase 1:
- `pkg/core/` — ProgramDirector, ChannelManager, orchestration
- `pkg/air/` — timing, lifecycle, diagnostics
- `docs/contracts/laws/` — LAW-CLOCK, LAW-RUNTIME-AUTHORITY, LAW-CONTENT-AUTHORITY

---

## Completed Work Log
| Turn | Date | Commit | What Was Done |
|------|------|--------|---------------|
| 0 | 2026-03-28 | 6154e89 | Created branch, committed plan, captured test baseline (328p/2f) |

---

## Blockers / Notes
- None currently
- AIR C++ tests need `pkg/air/build` to exist — check before running `ctest`
