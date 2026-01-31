# Migration Plan Validation Report — pkg/air/docs

**Source of truth:** [docs-layout-migration-plan.md](docs-layout-migration-plan.md)  
**Validation date:** Against current repository state (no files moved).

---

## Checklist by target directory

### contracts/laws/

| # | Source path | Source exists? | Dest dir exists? | Dest dir action | Filename collision? |
|---|-------------|----------------|------------------|-----------------|----------------------|
| 1 | `contracts/PlayoutInvariants-BroadcastGradeGuarantees.md` | ✅ Yes | ❌ No | **Create** `contracts/laws/` | No |

**Summary:** 1 move. Destination directory must be created. No blockers.

---

### contracts/semantics/

| # | Source path | Source exists? | Dest dir exists? | Dest dir action | Filename collision? |
|---|-------------|----------------|------------------|-----------------|----------------------|
| 1 | `contracts/architecture/MasterClockContract.md` | ✅ Yes | ❌ No | **Create** `contracts/semantics/` | No |
| 2 | `contracts/architecture/OutputContinuityContract.md` | ✅ Yes | ❌ No | (same dir) | No |
| 3 | `contracts/architecture/OutputTimingContract.md` | ✅ Yes | ❌ No | (same dir) | No |
| 4 | `contracts/architecture/FileProducerContract.md` | ✅ Yes | ❌ No | (same dir) | No |
| 5 | `contracts/architecture/RendererContract.md` | ✅ Yes | ❌ No | (same dir) | No |
| 6 | `contracts/architecture/PlayoutInstanceAndProgramFormatContract.md` | ✅ Yes | ❌ No | (same dir) | No |
| 7 | `contracts/architecture/PlayoutEngineContract.md` | ✅ Yes | ❌ No | (same dir) | No |
| 8 | `contracts/architecture/MetricsAndTimingContract.md` | ✅ Yes | ❌ No | (same dir) | No |
| 9 | `contracts/architecture/MetricsExportContract.md` | ✅ Yes | ❌ No | (same dir) | No |
| 10 | `contracts/phases/Phase8-Invariants-Compiled.md` | ✅ Yes | ❌ No | (same dir) | No |
| 11 | `contracts/AirArchitectureReference.md` | ✅ Yes | ❌ No | (same dir) | No |
| 12 | `contracts/architecture/README.md` | ✅ Yes | ❌ No | (same dir) | No |

**Summary:** 12 moves. Destination directory must be created. No filename collisions. No blockers.

---

### contracts/coordination/

| # | Source path | Source exists? | Dest dir exists? | Dest dir action | Filename collision? |
|---|-------------|----------------|------------------|-----------------|----------------------|
| 1 | `contracts/architecture/ProducerBusContract.md` | ✅ Yes | ❌ No | **Create** `contracts/coordination/` | No |
| 2 | `contracts/architecture/PlayoutControlContract.md` | ✅ Yes | ❌ No | (same dir) | No |
| 3 | `contracts/architecture/OutputSwitchingContract.md` | ✅ Yes | ❌ No | (same dir) | No |
| 4 | `contracts/architecture/BlackFrameProducerContract.md` | ✅ Yes | ❌ No | (same dir) | No |
| 5 | `contracts/architecture/OutputBusAndOutputSinkContract.md` | ✅ Yes | ❌ No | (same dir) | No |
| 6 | `contracts/build.md` | ✅ Yes | ❌ No | (same dir) | No |
| 7 | `contracts/phases/Phase6A-Contract.md` | ✅ Yes | ❌ No | (same dir) | No |
| 8 | `contracts/phases/Phase8-Overview.md` | ✅ Yes | ❌ No | (same dir) | No |
| 9 | `contracts/phases/Phase8-0-Transport.md` | ✅ Yes | ❌ No | (same dir) | No |
| 10 | `contracts/phases/Phase8-1-AirOwnsMpegTs.md` | ✅ Yes | ❌ No | (same dir) | No |
| 11 | `contracts/phases/Phase8-1-5-FileProducerInternalRefactor.md` | ✅ Yes | ❌ No | (same dir) | No |
| 12 | `contracts/phases/Phase8-2-SegmentControl.md` | ✅ Yes | ❌ No | (same dir) | No |
| 13 | `contracts/phases/Phase8-3-PreviewSwitchToLive.md` | ✅ Yes | ❌ No | (same dir) | No |
| 14 | `contracts/phases/Phase8-4-PersistentMpegTsMux.md` | ✅ Yes | ❌ No | (same dir) | No |
| 15 | `contracts/phases/Phase8-5-FanoutTeardown.md` | ✅ Yes | ❌ No | (same dir) | No |
| 16 | `contracts/phases/Phase8-6-RealMpegTsE2E.md` | ✅ Yes | ❌ No | (same dir) | No |
| 17 | `contracts/phases/Phase8-7-ImmediateTeardown.md` | ✅ Yes | ❌ No | (same dir) | No |
| 18 | `contracts/phases/Phase8-8-FrameLifecycleAndPlayoutCompletion.md` | ✅ Yes | ❌ No | (same dir) | No |
| 19 | `contracts/phases/Phase8-9-AudioVideoUnifiedProducer.md` | ✅ Yes | ❌ No | (same dir) | No |
| 20 | `contracts/phases/Phase9-OutputBootstrap.md` | ✅ Yes | ❌ No | (same dir) | No |
| 21 | `contracts/phase10/INV-P10-PIPELINE-FLOW-CONTROL.md` | ✅ Yes | ❌ No | (same dir) | No |
| 22 | `contracts/phases/README.md` | ✅ Yes | ❌ No | (same dir) | No |

**Summary:** 22 moves (plan lists 23; Phase8-Invariants-Compiled is under semantics, not coordination). Destination directory must be created. No filename collisions. No blockers.

---

### contracts/ (root — no moves)

| # | Path | Exists? | Action |
|---|------|---------|--------|
| 1 | `contracts/README.md` | ✅ Yes | Stays; no move. |
| 2 | `contracts/INVARIANTS-INDEX.md` | ✅ Yes | Stays; no move. |

**Summary:** No moves. No action required for these two files.

---

### overview/, developer/, archive/

Per plan: no moves. All listed paths exist. No validation needed beyond confirming no moves.

---

### Other (operations/, runtime/, root README)

Per plan: unchanged or optional fold. No moves required for validation.

---

## Filename collision check (all proposed paths)

All proposed destination paths were compared. **No two sources map to the same destination path.**  
Distinct destinations: `contracts/laws/` (1 file), `contracts/semantics/` (12 files, 12 distinct names), `contracts/coordination/` (22 files, 22 distinct names).

---

## Blockers

**None.** Every source file exists. No filename collisions. The only prerequisite for executing moves is creating the three new directories:

1. `contracts/laws/`
2. `contracts/semantics/`
3. `contracts/coordination/`

---

## Notes (non-blocking)

### Potential misclassification (plan unchanged)

- **Phase8-Invariants-Compiled.md → semantics:** The document is a compiled list of Phase 8 invariants that includes both semantic (e.g. INV-P8-001–INV-P8-OUTPUT-001) and coordination (e.g. INV-P8-007, INV-P8-SWITCH-*) entries. Placing it in semantics is consistent with “mostly semantic; used as lookup”; readers may also expect it alongside Phase 8 coordination docs. Not a blocker; plan stands.

### Destination directories

- **contracts/laws/** — Does not exist. Create before moving `PlayoutInvariants-BroadcastGradeGuarantees.md`.
- **contracts/semantics/** — Does not exist. Create before moving the 12 semantics files.
- **contracts/coordination/** — Does not exist. Create before moving the 22 coordination files.

---

**Validation complete.** No files were moved; no content was modified.
