# Phase 03 – Operator Workflows & UI

**Status:** Planned

## Objective
Provide an approachable operator experience (CLI + web) for editing schedules, viewing compiled days, and previewing ad/packaging decisions.

## Deliverables
1. Enhanced CLI workflow (`programming edit/apply/history`).
2. FastAPI endpoint + lightweight frontend for calendar/grid editing and previews.
3. Simulation tool that renders a "day of air" timeline (JSON + optional HTML report).

## Dependencies
- Phase 01 compiler and Phase 02 ad/packaging logic must be stable.
- UI contract documented under `docs/contracts/core/operator_ui.md`.

## Key Tasks
- [ ] Define operator workflows + permissions.
- [ ] Implement CLI enhancements with tests.
- [ ] Build API + frontend prototype (likely React/Vue) served from `pkg/core/src/retrovue/web/`.
- [ ] Add integration tests covering end-to-end edit → compile → preview.

## Next Up
Blocked on Phase 01/02 completion; revisit once those phases move to "Implemented".
