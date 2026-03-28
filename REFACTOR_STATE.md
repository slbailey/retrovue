# REFACTOR_STATE.md — Live Execution State

> Every agent turn MUST:
> 1. Read this file first
> 2. Do ONE atomic sub-step only
> 3. Mark it done and set the next sub-step
> 4. Commit and report

---

## Overall Goal
Aggressive (L3) complexity reduction. Single source of truth per concern.
Full analysis: `/opt/retrovue/DEEP_ANALYSIS.md`
Full constraints: `/opt/retrovue/SIMPLIFICATION_PLAN_V1.md`
Branch: `refactor/simplify-single-authority-l3`

## The real objective (from DEEP_ANALYSIS.md)
Not just clean up code — lock down the authority model so it cannot drift again.
Every phase must both REMOVE complexity AND STRENGTHEN the boundary that prevented it from forming in the first place.
Phase 9 is mandatory: CLAUDE.md + contracts must explicitly forbid the patterns that caused each problem we fixed.

---

## Current Phase: 4 — Diagnostics Isolation

## Sub-steps (do ONE per turn, mark [x] when done):

- [x] **4a** — Audit StreamingDiagnostics fields in Python runtime + AIR C++. Found: DEAD in both.
- [x] **4b** — Delete StreamingDiagnostics class, diagnostics field from StreamingSchema, defaults.yaml section. 26 lines removed. 330 pass.
- [x] **4c** — Extract `_hls_diag_*` state from ProgramDirector into a `HlsDiagnosticsState` dataclass (per-channel). PD holds one instance per channel and delegates. Does NOT change behavior — makes the boundary explicit and testable. Files: `pkg/core/src/retrovue/runtime/program_director.py`. Run tests (floor 330).
- [x] **4d** — Verify auto-expiry (`_hls_diag_mode_until` check) is the ONLY expiry mechanism — no manual reset paths that could suppress diagnostics. Document result. Commit PHASE4_COMPLETE.md.

## NEXT SUB-STEP: 5a

---

## Phase 5 — Ghost Surface Deletion (ZERO RISK)

- [ ] **5a** — Delete 11 ghost TODO/pass methods from PD (lines 1642–1806). Delete `SystemHealth`, `ChannelInfo`, `ChannelStatus`. Run tests (floor 330).
- [ ] **5b** — Delete 2 dead HTTP 501 stubs (`/test/segment/...`, `/test/channel/...`). Run tests.
- [ ] **5c** — Delete `play_content()` dead method from `BlockPlanProducer` in channel_manager.py. Run tests.
- [ ] **5d** — Move `MockBlockPlanProvider` from `playout_session.py` to `tests/fixtures/mock_block_plan.py`. Update imports. Run tests.
- [ ] **5e** — Delete `_build_producer_for_mode` monkeypatch wrapper in `PD._get_or_create_manager()` (4 lines, zero functional change). Run tests.
- [ ] **5f** — Replace `_start_linger()` fallback branch with `assert self.on_linger_expired is not None`. Add test confirming ChannelManager construction without callback raises. Run tests.
- [ ] **5g** — After all ghost deletions: update CLAUDE.md to add rule: "No TODO/pass methods. If a method is not implemented, do not create it. Ghost scaffolding is forbidden."

---

## Phase 6 — Old HLS Stack Removal (HIGH RISK — BROADCAST MIGRATION)

Treat this as a broadcast infrastructure migration, not a code deletion.
Risk is HIGH operationally — old stack may be masking new stack bugs. Validate before delete.

- [ ] **6a** — Audit: confirm no active production clients use /hls/ endpoints. Check IPTV M3U output, Plex lineup, config files. Smoke test /channels/ returns valid manifests.
- [ ] **6b** — Shadow validation: add temporary response comparison logging — when a request hits /channels/, internally validate old stack would have produced equivalent output. Log any divergence. Run for one 15-min turn.
- [ ] **6c** — Review shadow log. If clean: proceed to 6d. If divergences found: fix in new stack first, then re-run 6b.
- [ ] **6d** — Remove /hls/ endpoint handlers from PD. Remove self._hls_manager instantiation and stop_all() call. Keep hls_writer.py module for now (rollback safety).
- [ ] **6e** — Run tests (floor 330). Confirm HLS clients work against /channels/ endpoints. Confirm no segment ring behavioral differences.
- [ ] **6f** — Delete retrovue.streaming.hls_writer module entirely. Remove dead imports. Run tests.
- [ ] **6g** — Update CLAUDE.md: "There is one HLS delivery stack: SegmentRing + HlsSegmenter at /channels/. No disk-based HLS. INV-HLS-NO-DISK-IO-001 is a hard constraint. Do not re-introduce a parallel HLS stack."

## Phase 7 — Mock Relocation (MEDIUM IMPACT, LOW RISK)

- [ ] **7a** — Move `MockGridScheduleService` and `MockAlternatingScheduleService` from `channel_manager.py` to `tests/fixtures/mock_schedule_services.py`. Update 4 import sites in `program_director.py`. Run tests.
- [ ] **7b** — Move `Playlist`, `PlaylistSegment` from `channel_manager.py` to `retrovue/scheduling/playlist_types.py`. Update import in `scheduling/playlist_schedule_manager.py`. Run tests.
- [ ] **7c** — Move `ProgramDirector` Protocol and `ScheduleService` Protocol from `channel_manager.py` to `retrovue/runtime/protocols.py`. Update import sites. Run tests.
- [ ] **7d** — After relocation: update CLAUDE.md to add rule: "Production modules contain only production code. If a class is only instantiated in tests or behind mock_* flags, it belongs in tests/fixtures/, not in runtime/."

---

## Phase 8 — Consumption Adapter Model (replaces "HLS Activation Unification")

Reframed: HLS and TS are two consumption adapters over one PD-owned lifecycle.
Not just path merger — defines the correct mental model going forward.

- [ ] **8a** — Write contract test: "Channel lifecycle is PD-owned; HLS and TS are consumption adapters that share the same CM activation path." Must FAIL before code change.
- [ ] **8b** — Extract HLS phantom management from _ensure_channel_active_for_hls into HlsConsumptionAdapter._activate_phantom(channel_id, mgr) helper.
- [ ] **8c** — Extract raw TS fanout management into TsConsumptionAdapter._wire_fanout(channel_id, mgr) helper.
- [ ] **8d** — Both adapters call PD.start_channel() as the single lifecycle entry point. Delete _ensure_channel_active_for_hls() body (~190 lines). Run tests (floor 330). Contract test from 8a must PASS.
- [ ] **8e** — Update CLAUDE.md: "Channel lifecycle is PD-owned. HLS and TS are consumption adapters. There is one lifecycle path: start_channel(). Adapters add consumption-model behavior (phantom, fanout) but do not own lifecycle."

## Phase 8.5 — Observability Hardening (BEFORE process gates)

Goal: be able to trace a single viewer session from tune-in to tune-out in the logs.
Required before Phase 9 so we can validate the refactor worked.

- [ ] **8.5a** — Add structured log events (DEBUG level, gated) at: channel activation, first segment produced, viewer join/leave, linger start/expire, teardown.
- [ ] **8.5b** — Add correlation ID (session_id) flowing: PD activation -> CM lifecycle -> HLS phantom -> segments. Must appear in all log lines for a viewer session.
- [ ] **8.5c** — Validate end-to-end: start a channel, join as viewer, leave, confirm full lifecycle traceable in logs. Commit with test.
- [ ] **8.5d** — Update CLAUDE.md: "Runtime lifecycle transitions must emit structured log events at DEBUG level. Viewer sessions must carry a correlation ID traceable end-to-end."

## Phase 9 — Model Lockdown (MOST IMPORTANT FOR FUTURE CONTROL)

This phase is NOT optional. It is the reason all prior phases have lasting value.
Goal: Make CLAUDE.md, contracts, and invariants explicitly forbid every pattern we fixed.
Future AI sessions must be unable to re-introduce these problems without visibly violating a documented rule.

- [ ] **9a** — Add Authority Rule to CLAUDE.md: "For any change touching runtime behavior, define exactly one authority owner per concern (clock, segment window, lifecycle, diagnostics). If a change introduces a second authority for any concern, stop and redesign."
- [ ] **9b** — Add Complexity Budget Rule to CLAUDE.md: "Every non-trivial change must include: what logic is removed, what logic is added, net effect on moving parts. Net-new abstractions require justification. Prefer deletion over layering."
- [ ] **9c** — Add Ghost Prohibition to CLAUDE.md: "No TODO/pass/NotImplemented scaffolding in production code. If its not implemented, dont create it. Ghost methods are forbidden — they create false API surface."
- [ ] **9d** — Add Production Boundary Rule to CLAUDE.md: "Production modules contain only production code. Mocks, fixtures, and test harnesses belong in tests/fixtures/. Never in runtime/."
- [ ] **9e** — Add Required PR Header to CLAUDE.md: Every change must declare: (1) authority concern touched, (2) complexity budget (removed/added/net), (3) contracts affected, (4) rollback unit.
- [ ] **9f** — Add new invariant: INV-SINGLE-ACTIVATION-PATH-001 — "ProgramDirector.start_channel() is the sole channel activation entry point. No parallel activation paths may exist."
- [ ] **9g** — Add new invariant: INV-NO-GHOST-METHODS-001 — "No production module may contain unimplemented (pass/TODO) method stubs. Ghost scaffolding is a contract violation."
- [ ] **9h** — Final: produce REFACTOR_COMPLETE.md with: all-clear status, what was done, what the codebase looks like now, prompt language updates for CLAUDE.md, lessons learned. This is the document handed to Steve.

## NEXT SUB-STEP (after 4c): Continue from current position — now 4d.

---

## Completed Work Log
| Turn | Date | Commit | What Was Done |
|------|------|--------|---------------|
| 0 | 2026-03-28 | 6154e89 | Created branch, committed plan, captured test baseline (328p/2f) |
| 0b | 2026-03-28 | a0168ea | Added REFACTOR_STATE.md |
| 1 | 2026-03-28 | 2488974 | Authority overlap map produced |
| 1b | 2026-03-28 | 293c545 | REFACTOR_STATE.md updated to phase 2 |
| wip | 2026-03-28 | 0683216 | Safety check committed leftover AIR files |
| wip2 | 2026-03-28 | 0687f01 | Safety check recovery (second) |
| 2a | 2026-03-28 | 27d1982 | Contract test INV-LIFECYCLE-PD-SOLE-TEARDOWN-001 (6 RED) |
| 2b | 2026-03-28 | c81d328 | Deleted deferred_teardown_triggered() dead code; 330 pass |
| 2c | 2026-03-28 | 39ded8f | Deleted compute_jip_position() 58 lines; 331 pass |
| 2d | 2026-03-28 | 522b298 | Deleted _mock_grid_* from ChannelManager; 333 pass |
| 2e | 2026-03-28 | e396513 | Add on_linger_expired callback to ChannelManager |
| 2f | 2026-03-28 | 1ce56d8 | Wire PD: inject on_linger_expired; contract GREEN; 334 pass |
| 2g | 2026-03-28 | 652521f | Inject MasterClock into DslScheduleService |
| 2h | 2026-03-28 | 0f326e1 | Audit dsl_schedule_service datetime.now() — CLEAN; Phase 2 complete |
| 3a | 2026-03-28 | (in 0f326e1) | Phase 3 contract audit; PHASE3_CONTRACT_AUDIT.md |
| 3b | 2026-03-28 | be7edd6 | Retire 4 internal tests from test_frame_selection_cadence_contract.py; 330 pass |
| 3c | 2026-03-28 | (state only) | No more retirements viable within floor; Phase 3 complete |
| 3d | 2026-03-28 | 59db9ec | Transition to Phase 4; produce PHASE4_DIAGNOSTICS_AUDIT.md |
| 4a | 2026-03-28 | (in 59db9ec) | StreamingDiagnostics audit — DEAD in both Python and AIR C++ |
| 4b | 2026-03-28 | 0cb53e2 | Delete StreamingDiagnostics, schema field, defaults.yaml section; 330 pass |
| deep | 2026-03-28 | 9e9d5d8 | DEEP_ANALYSIS.md — full architectural diagnosis, revised phase plan |

---

| 4c | 2026-03-28 | d9b02b6 | Extract _hls_diag_* into HlsDiagnosticsState dataclass; 330 pass |
| 4d | 2026-03-28 | 5e7be6a | Expiry audit — auto-expiry sole mechanism; fix stale contract test; PHASE4_COMPLETE.md |
## Blockers / Notes
- Cron was disabled for deep analysis — re-enabled after REFACTOR_STATE.md update
- Phase 9 is mandatory — code cleanup without model lockdown is temporary
- Each phase now ends with a CLAUDE.md update to prevent re-introduction
- Test floor: 330 passing (up from baseline 328)
