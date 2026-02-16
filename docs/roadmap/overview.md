# RetroVue Roadmap Overview

This roadmap tracks the "what" (contracts), validation (tests), and implementation (code) pipeline for major Retrovue initiatives. Each phase is documented separately so any assistant or engineer can open the phase file, see the current contract, build/tests status, and pick up the next task.

## Status Legend
- **Planned** – Contract draft in progress.
- **In Flight** – Contract approved, tests being written/executed.
- **Implemented** – Code merged, telemetry validated.

## Phases
| Phase | Focus | Status | Detail |
| --- | --- | --- | --- |
| 01 | Programming DSL & compiler | Planned | [phase-01-programming-dsl.md](phase-01-programming-dsl.md) |
| 02 | Ads, promos, and movie packaging | Planned | [phase-02-ads-packaging.md](phase-02-ads-packaging.md) |
| 03 | Operator workflows & UI | Planned | [phase-03-operator-ui.md](phase-03-operator-ui.md) |
| 04 | Runtime integration & telemetry | Planned | [phase-04-runtime-integration.md](phase-04-runtime-integration.md) |

## Working Agreements
1. **Contracts → Tests → Code**: we never ship code without an approved contract doc and corresponding tests.
2. **Docs stay ahead of code**: roadmap + invariants updated before opening PRs.
3. **Single source of truth**: the files in `docs/roadmap/` and `docs/invariants/` are canonical references for assistants (OpenClaw, Claude, Cursor, etc.).

## Using this Roadmap
- Want to know "what's next"? Open the active phase file and jump to the **Next Up** section.
- Need invariants or acceptance criteria? Each phase links to its invariant doc.
- Writing code/tests? Reference the phase file's **Open Tasks** checklist and update it as you go.
