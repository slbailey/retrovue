# Phase 8 Decommission Contract

**Status:** Normative  
**Component:** Architecture (Core + AIR boundary)  
**Created:** 2026-02-12  
**Reference:** Phase8 removal; single playout authority

---

## Purpose

This contract defines exactly what **"Phase 8 removed"** means. It is the authoritative rulebook for the decommission: no component may rely on Phase 8 playout semantics, and the only valid runtime path is blockplan.

---

## Normative Outcomes

### 1. Single runtime playout authority: blockplan

There is **exactly one** runtime playout authority: **blockplan**.

- Core produces **BlockPlans** (via ScheduleManager / ScheduleService chain).
- AIR (or the single playout engine) consumes BlockPlans and executes frame-accurate playout.
- No other playout control path is permitted at runtime.

### 2. Forbidden: LoadPreview / SwitchToLive and related

No component may **issue** or **depend on**:

- **LoadPreview** / **SwitchToLive** (per-segment preview/live switching RPCs or their equivalents),
- **Per-segment switching orchestrated by Core** (Core must not drive segment boundaries via LoadPreview/SwitchToLive or equivalent),
- **Boundary lifecycle state machine for playlist execution** (e.g. `BoundaryState`, `SwitchState`, and the state machine that drives LoadPreview → SwitchToLive for playlist-driven playout).

After decommission, Core does not orchestrate segment boundaries; it hands a BlockPlan to the playout engine and the engine owns execution.

### 3. Forbidden: non-blockplan schedule sources

No channel config may support:

- `schedule_source: "mock"`, or
- Any **non-blockplan** schedule source.

The **only** valid schedule inputs are those that produce **BlockPlans** via the ScheduleManager / ScheduleService chain (e.g. `schedule_source: "phase3"` as the config-driven activation for the service that yields BlockPlans).

- Valid: schedule sources that resolve to ScheduleManagerBackedScheduleService (or equivalent) and produce BlockPlans.
- Invalid: `"mock"`, `"file"` (if it does not produce BlockPlans), or any source that drives legacy playlist/segment switching.

### 4. Valid schedule inputs

The only valid schedule inputs are the ones that produce **BlockPlans** via the ScheduleManager / ScheduleService chain. Configuration must restrict `schedule_source` to the single blockplan schedule source (e.g. `"phase3"`). Validation must reject any other value at config load or use.

---

## Required Deletions (Checklist)

Before the decommission is complete, the following must be removed or replaced.

### Core – ProgramDirector / embedded registry

**Contract (runtime registry):** The embedded registry registers only BlockPlan path services. Mock/playlist schedule services are not available in production paths.

| Item | Location / name |
|------|------------------|
| ~~Phase8 schedule service registration~~ | Removed: no `Phase8MockScheduleService`, `Phase8ScheduleService` in `_init_embedded_registry` |
| ~~Phase8 program director~~ | Removed: ProgramDirector passes `self` to ChannelManager; no `Phase8ProgramDirector` |
| Phase8 producer factory path | Any code path that constructs or returns `Phase8AirProducer` (to be removed later) |

### Core – ChannelManager

| Item | Location / name |
|------|------------------|
| Phase8AirProducer | `channel_manager.Phase8AirProducer` class and all references |
| LoadPreview / SwitchToLive usage | All calls to LoadPreview / SwitchToLive from ChannelManager (or equivalent) |
| Playlist-driven producer selection | `_build_producer_for_mode` path that returns Phase8AirProducer when playlist is active |
| Boundary state machine (playlist execution) | `BoundaryState`, `SwitchState`, `_boundary_state`, `_switch_state`, `_transition_boundary_state`, and all transitions that drive LoadPreview / SwitchToLive |
| load_playlist entry point | `ChannelManager.load_playlist()` (remove or make no-op that raises) |
| Playlist tick / playlist bootstrap | `_ensure_producer_running_playlist`, `_tick_playlist`, and related playlist-driven tick logic |

### Core – Schedule / config

| Item | Location / name |
|------|------------------|
| Phase8 schedule services | `Phase8MockScheduleService`, `Phase8ScheduleService` (in `channel_manager` or equivalent) |
| Mock schedule source | Support for `schedule_source: "mock"` in channel config and any provider |
| Non-blockplan schedule source support | Any `schedule_source` value other than the blockplan one (e.g. `"phase3"`) |

### Core – Tests and tools

| Item | Location / name |
|------|------------------|
| Tests importing Phase8AirProducer | All tests that `import Phase8AirProducer` or use Phase8ProgramDirector / Phase8* services |
| Tests using LoadPreview / SwitchToLive | Tests that assert or call LoadPreview / SwitchToLive behavior |
| Burn-in / tools using mock schedule | `tools/burn_in.py` and any tool using `schedule_source="mock"`; switch to blockplan schedule source |

### AIR (reference only; changes may be in separate PRs)

| Item | Location / name |
|------|------------------|
| LoadPreview / SwitchToLive RPC handling | If retained for compatibility, they must not be used by Core; removal is out of scope for this contract’s checklist |

---

## Tests Required (by name)

The following contract tests **must** exist and enforce this contract:

- **ProgramDirector registry:** ProgramDirector does not register Phase8 services (no Phase8ScheduleService, Phase8MockScheduleService, Phase8ProgramDirector in the embedded registry code path).
- **ChannelConfig schedule source:** ChannelConfig (or validation) rejects `schedule_source != "phase3"` (or the canonical blockplan schedule source).
- **load_playlist canonical exception:** Attempting to call `load_playlist()` on a channel that must use blockplan raises a canonical exception type/message (e.g. `RuntimeError` with `INV-CANONICAL-BOOT` or equivalent).
- **No Phase8AirProducer import:** No production code under Core imports or references `Phase8AirProducer` (enforce via grep-style or import-graph test; test code may be excluded or required to migrate).

See: `pkg/core/tests/contracts/architecture/test_phase8_decommission_contract.py`.

---

## Verification Gate

- This PR (contract + tests) may be merged **before** deletions are complete.
- Tests that assert “Phase 8 absent” may be marked `xfail` until the deletion PR lands, if the workflow allows.
- Otherwise, land contract + tests after stubbing behavior as fast-fail in a follow-up PR.
- **Rollback:** Revert this document and the contract test file; no runtime behavior change until Phase 8 code is removed.

---

## Deprecated Contracts (removed by this decommission)

The following contracts described behavior that is no longer available; they are marked deprecated and retained for reference only:

- **PlaylistScheduleManagerContract.md** — Playlist execution via `load_playlist()` and playlist-driven tick. Deprecated → Removed by Phase8DecommissionContract.
- **ScheduleManagerContract.md** § LoadPreview / § SwitchToLive and related (CT-domain switching, INV-PLAYOUT-SWITCH-BEFORE-EXHAUSTION, INV-PLAYOUT-NO-PAD-WHEN-PREVIEW-READY) — Per-segment LoadPreview/SwitchToLive RPC orchestration by Core. Deprecated → Removed by Phase8DecommissionContract.
- **Segment transitions** (prebuffering, LoadPreview/SwitchToLive ordering) — formerly ScheduleManagerPhase7Contract; deprecated → Removed by Phase8DecommissionContract.
- **Timeline Controller** (segment mapping for preview/live switching) — formerly ScheduleManagerPhase8Contract; deprecated → Removed by Phase8DecommissionContract.

---

## References

- `pkg/core/docs/contracts/runtime/INV-CANONICAL-BOOTSTRAP.md` — Single bootstrap path (blockplan_only guard)
- `docs/architecture/decisions/ADR-012-BlockPlan-Contract-Layer.md` — BlockPlan contract layer
- `pkg/core/docs/contracts/PlayoutAuthorityContract.md` — Playlist vs blockplan authority
