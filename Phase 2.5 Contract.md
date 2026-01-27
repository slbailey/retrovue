# Phase 2.5 — Asset Metadata Contract

## Purpose

Introduce authoritative, measured asset facts (duration, path) into the system **without contaminating scheduling, playout planning, or execution layers**.  
Phase 2.5 **formalizes the boundary** between **conceptual scheduling (Phase 2/3)** and **physical media reality** (later Air execution).  
This phase does **not** read media during runtime; it defines how pre-measured metadata is represented and consumed.

## Scope

**Phase 2.5 owns:**
- Asset identity
- Asset path
- Asset duration (**milliseconds, authoritative**)

**Phase 2.5 does *not* own:**
- Decoding media
- Opening files at runtime
- Scheduling content
- Computing grid math
- Executing playout

## Asset (explicit contract)

```python
@dataclass(frozen=True)
class Asset:
    asset_id: str          # Stable logical identifier
    asset_path: str        # Filesystem or URI path
    duration_ms: int       # Authoritative duration, milliseconds
```

### Duration rules (hard requirements)
- `duration_ms` is **authoritative**
- Measured once (e.g. `ffprobe`)
- Rounded **down** to integer milliseconds
- Never recomputed in runtime logic
- Never inferred from offsets or schedules
- If a duration is wrong, metadata is **corrected**; logic is **not patched**

## Inputs

- Media files exist on disk (out of band)
- Duration is probed once (manual or by tooling)
- Results are **injected as constants or fixtures**

## Outputs

- A **set of Asset objects** available to higher phases

**Example (mock, frozen):**
```python
SAMPLECONTENT = Asset(
    asset_id="samplecontent",
    asset_path="assets/samplecontent.mp4",
    duration_ms=1_499_904,
)
FILLER = Asset(
    asset_id="filler",
    asset_path="assets/filler.mp4",
    duration_ms=3_650_455,
)
```

## Consumption rules

**Phase 3 (Active Item Resolver)**
- Uses `asset.duration_ms` instead of constant guesses
- Does **not** open files
- Does **not** probe duration

**Phase 4 (PlayoutPipeline)**
- Uses `asset.asset_path`
- Uses `asset.duration_ms` for offset math
- Still produces pure PlayoutSegments

**Phase 5 (ChannelManager)**
- Treats assets as opaque facts
- Never inspects duration logic directly

## Execution model

- No runtime execution
- No process
- No file I/O
- Assets are **injected as fixtures or configuration**
- This phase **binds reality to data**, not perform work

## Test scaffolding

- **Unit tests** validate:
  - Asset durations are integers (ms)
  - `duration_ms > 0`
  - `duration_ms < grid_duration_ms` (for samplecontent)
  - Asset objects are **immutable**

**Example assertions:**
```python
assert SAMPLECONTENT.duration_ms == 1_499_904
assert FILLER.duration_ms == 3_650_455
assert SAMPLECONTENT.duration_ms < GRID_DURATION_MS
```
- No ffprobe in tests

## Out of scope

- ❌ No probing logic
- ❌ No media reads
- ❌ No ffmpeg
- ❌ No Air
- ❌ No scheduling rules

## Exit criteria

- Asset durations are **authoritative and frozen**
- All downstream phases consume Asset metadata, not guesses
- Demo output reflects real durations
- Tests pass **without file I/O**
- ✅ Phase 2.5 complete when asset metadata replaces all mocked durations