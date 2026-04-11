# INV-AUTHORITY-SINGLE-OWNER-001

## Behavioral Guarantee

For each designated concern in Core runtime, exactly one component MUST own write authority. Other components MAY read from that authority but MUST NOT write to it. The designated authority slices are:

- **Clock/timebase authority** — MasterClock (`runtime/clock.py`)
- **Segment window authority** — SegmentRing (`runtime/hls/segment_ring.py`)
- **Channel lifecycle authority** — ProgramDirector (`runtime/program_director.py`)
- **Diagnostics authority** — HlsDiagnosticsState (per-channel, held by PD)

## Authority Model

Each authority domain is self-owning. No external arbiter selects or rotates ownership. The owner is fixed by architectural contract, not by runtime negotiation.

## Boundary / Constraint

- A component other than MasterClock MUST NOT invent, reset, or locally reinterpret wall-clock time for playout decisions.
- A component other than SegmentRing MUST NOT own the HLS sliding window state.
- A component other than ProgramDirector MUST NOT make channel teardown or activation decisions.
- Diagnostics state MUST NOT be scattered across multiple components; it MUST be delegated to the designated per-channel diagnostics holder.
- Cross-domain changes MUST be staged: one domain per PR unless explicitly coordinated at the system level.

## Violation

Any component that writes to a concern it does not own. Any change that introduces a second decision-maker for a designated authority domain. Silent `now()` calls that bypass MasterClock. Duplicate teardown logic outside ProgramDirector.

## Derives From

`LAW-RUNTIME-AUTHORITY`, `LAW-CLOCK`

## Required Tests

- `server/tests/contracts/runtime/test_evidence_server_clock_authority.py` — V6: DurableAckStore and AsRunWriter use injected MasterClock, not `datetime.now()`
- `server/tests/contracts/runtime/test_pd_staleness_clock_authority.py` — V7: ProgramDirector staleness check uses MasterClock, not `time.time()`
- Authority boundary enforcement is partially covered by import-graph tests in `server/tests/contracts/test_scheduling_constitution.py`.

## Enforcement Evidence

- V6 (evidence_server `datetime.now` bypass): Fixed in `evidence_server.py` — injected `clock` parameter into `DurableAckStore` and `AsRunWriter`, replaced 3 `datetime.now(timezone.utc)` calls with `self._clock.now_utc()`.
- V7 (PD `time.time` bypass): Fixed in `program_director.py` — replaced `int(time.time() * 1000)` with `int(self._embedded_clock.now_utc().timestamp() * 1000)` in HLS staleness check.
