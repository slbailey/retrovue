# INV-PACING-SINGLE-AUTHORITY-001

## Behavioral Guarantee

Wall-clock pacing of playout emission (first paced byte onward) has **exactly one authority**: **`OutputClock`**. No other AIR component may delay, burst-correct, or resynchronize emission to repair **pre-bootstrap** A/V phase error. **Mux, encoder, `MpegTSOutputSink`, and `ProgramOutput` MUST NOT** apply timing or A/V skew repair for conditions that **INV-BOOTSTRAP-AV-PHASE-001** requires to be resolved **before** pacing begins.

## Authority Model

- **`OutputClock`**: Sole owner of wall-time pacing once started.
- **`PipelineManager`**: Owns **ordering only** — it MUST establish **phase-valid** upstream state per **INV-BOOTSTRAP-AV-PHASE-001**, then start **`OutputClock`**, then open the **emission gate** (TS bytes held until bootstrap complete — ordering implemented in `PipelineManager` and `SocketSink`). Canonical emission ordering is: **bootstrap phase valid → `OutputClock::Start` → gate open**.
- **`VideoLookaheadBuffer` fill thread**: Owns **fill-domain** A/V lead enforcement per **INV-FILL-AV-LEAD-CLAMP-001**; it does **not** replace `OutputClock` pacing.

## Boundary / Constraint

1. **`OutputClock` MUST NOT** be started until **INV-BOOTSTRAP-AV-PHASE-001** handoff conditions are satisfied **or** **INV-BOOTSTRAP-AV-PHASE-001** failure path has been taken (session teardown — see that invariant).
2. The **emission gate** (bytes reaching the transport consumer) MUST remain **closed** until after **`OutputClock::Start`** completes in the successful bootstrap path.
3. **Downstream** (mux, PCR interleaving, TS packetization) MUST **assume** upstream PTS/timebase is already consistent with editorial intent at gate open; they MUST NOT add **bootstrap-phase** A/V catch-up logic.

## Violation

- `OutputClock` started while bootstrap **phase-invalid** per **INV-BOOTSTRAP-AV-PHASE-001**.
- Emission gate opened before `OutputClock` epoch is established.
- Encoder, mux, or sink code path that **adjusts timing or sample cadence** specifically to fix **pre-existing** bootstrap A/V skew (as opposed to format-compliant encode/mux of already-valid timelines).

## Derives From

- `LAW-CLOCK`
- `LAW-RUNTIME-AUTHORITY`

## Relationship

- Supersedes the informal backlog label **INV-PACING-001** for the **single pacing authority** slice. Other pacing topics (decode rate, segment content) remain separate invariants if promoted from backlog.

## Required Tests

- Contract tests proving: (1) no `OutputClock::Start` when bootstrap phase gate fails; (2) no emission gate open before clock start; (3) no new A/V repair hooks in mux/encoder for bootstrap skew — **to be added** under `runtime/tests/contracts/BlockPlan/` (exact filenames TBD in test pass).

## Enforcement Evidence

TODO
