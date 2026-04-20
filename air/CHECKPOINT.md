# AIR vNext — Session Checkpoint

**Last updated:** end of session 2026-04-19.
**State:** 44/44 tests passing. Slices 1–5 complete. Ready to pick up at emission OR session-lifecycle.

## Summary

A parallel vNext subsystem has been built at `/opt/retrovue/air/`, separate from `/opt/retrovue/runtime/`. It validates the vault's dual-buffer + per-source Normalizer + aspect-preserving scaling architecture end-to-end against real H.264 media, with no code coupling to the legacy runtime.

The model is proven in isolation. It has not been wired to Core and has not produced bytes on a wire.

## What exists

```
/opt/retrovue/air/
├── CMakeLists.txt          cmake -S air -B air/build ... ; ctest --test-dir air/build
├── include/                (flat, 11 headers)
│   ├── channel_canonical.hpp        ChannelCanonical, Rational, NthStepPtsUs
│   ├── frame_types.hpp              VideoFrame, AudioBlock
│   ├── source_producer.hpp          ISourceProducer interface
│   ├── pad_source_producer.hpp      concrete: pad (broadcast black + silence)
│   ├── synthetic_source_producer.hpp concrete: programmatic test source
│   ├── file_source_producer.hpp     concrete: libav decode (YUV420P + AAC)
│   ├── normalizer.hpp               INormalizer interface, ChannelOrigin, ReanchorTier
│   ├── identity_normalizer.hpp      passthrough (rate+format identity)
│   ├── standard_normalizer.hpp      cadence + SRC + aspect-preserving scaling
│   ├── preview_buffer.hpp           Video/AudioPreviewBuffer (BufferStore preview role)
│   └── playback_director.hpp        minimal: active-assignment owner only
├── src/                    (6 impls)
└── tests/contracts/        (4 test files, 44 tests)
    ├── pad_preview_slice_test.cpp      slice 1 — contract shape
    ├── cadence_and_src_test.cpp        slice 2 + 4 — cadence, SRC, NTSC
    ├── promotion_test.cpp              slice 3 — dual-buffer promotion
    └── file_decode_test.cpp            slice 5 — real media + scaling
```

**Build:**
```
cmake -S air -B air/build \
  -DCMAKE_TOOLCHAIN_FILE="$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake" \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build air/build -j$(nproc)
ctest --test-dir air/build --output-on-failure
```

Dependencies: gtest (vcpkg); libav* + libx264 static from `runtime/third_party/` (shared deps, no code coupling); system pthread/m/dl/z/lzma/bz2/drm.

## Slice-by-slice status

| Slice | Scope | Evidence |
|---|---|---|
| 1 | Pad producer + identity normalizer + preview buffer end-to-end | 17 tests. Contract shape + lifecycle + re-anchor tiers + A/V shared origin. |
| 2 | Real Normalizer: cadence (24→30, 60→30, passthrough) + audio SRC (44.1→48 linear interp) | 10 tests. Pattern correctness for pulldown/decimation; SRC constant + ramp preservation; audio PTS monotonic. |
| 3 | Dual-buffer promotion via PlaybackDirector | 6 tests. Continuous channel PTS across pad→content promotion; re-anchor under mistimed promotion; source identity invisible on PTS. |
| 4 | NTSC fractional framerate (30000/1001 from `cheers-24-7.yaml`) | 5 tests. Rational::NthStepPtsUs at NTSC; 24→NTSC pulldown; 60000/1001→30000/1001 decimation; passthrough. |
| 5 | File-backed H.264 decode + aspect-preserving scaling | 6 tests. Real SampleA/B at 720×480 → 968×720 channel canonical with letterbox bars; all rates + PTS verified against real decoded media. |

## Architectural decisions made (and the corrections)

Three things drifted and were corrected mid-session; they're worth remembering because they shaped the final shape:

1. **`IdentityNormalizer` was deriving channel PTS from source PTS.** Fixed mid-session. Channel PTS now computed from the Normalizer's own channel frame/sample index via `Rational::NthStepPtsUs`. Source PTS survives only as opaque metadata. This was a `INV-DOWNSTREAM-SOURCE-PTS-OPAQUE-001` violation caught by user review, not by tests (tests passed because PadSourceProducer's source PTS happens to equal `NthStepPtsUs(k)`).

2. **Standalone `LivePointer` class was owning active-assignment truth.** Fixed. Renamed to `PlaybackDirector` — a minimal vault-named authority implementation. Method names aligned (`PromoteToAssignment`, `HasActiveAssignment`, `ActiveAssignment`, `PreviousAssignment`). PTS-computation helpers moved off the class onto the `LiveSegment` struct. Authority-ownership violation caught by user review.

3. **Aspect-stretch scaling in `StandardNormalizer`.** Fixed. Now fit-to-contain with broadcast-black letterbox/pillarbox bars. Integer-math layout with even-alignment for YUV420P chroma. No stretching.

Each drift came from picking "the convenient shape" without cross-checking the vault. The new `VAULT-COMPLIANCE PRE-CHECK` section in `/opt/retrovue/CLAUDE.md` is intended to prevent the pattern.

## Vault updates made this session

These vault docs reflect the current (post-correction) state:

- `04_truths/Truth - Source Time Is Producer-Local, Channel Time Is Canonical.md` — added "Current instantiation (air/)" subsection.
- `00_components/Normalizer.md` — added "Current Implementation Status" section + rewrote Migration Notes to distinguish air/ parallel-implementation from runtime/ migration path.
- `00_components/SourceProducer.md` — added "Current Implementation Status (vNext)" listing three concrete conformers.
- `00_components/BufferStore.md` — Current-State Conformance split into vNext + Legacy. PlaybackDirector owns active-assignment (retracted "LivePointer" language).
- `00_components/PlaybackDirector.md` — added "Current Implementation Status (vNext, minimal)" section scoping the minimal slice-3 implementation.
- `02_flows/Flow - Tune-In.md` — added resolved-since-earlier entries for slice 1-5 mechanics (Normalizer, dual-buffer promotion, file-backed decode).

Root `/opt/retrovue/CLAUDE.md` has a new `VAULT-COMPLIANCE PRE-CHECK` section at the bottom — governing rule for pre-verifying vault compliance before implementation decisions.

## What's NOT done (honest gap list)

**In `air/`:**
- No encoder / muxer / byte emission. Live-buffer frames exist; nothing turns them into MPEG-TS bytes on a wire.
- No Core integration. No gRPC server, no `PlayoutEngine` boundary, no session-start path.
- PlaybackDirector is minimal — only active-assignment ownership. No `prepare` / `activate` / `retire` lifecycle intents. No kickoff coordination. No seam coordination.
- No `BootstrapContentGate`, `ReadinessController`, `SeamController`, `PacingController` in `air/`.
- No `Clock` — tests don't do wall-clock math. Real sessions will need an injected clock authority.
- Audio channel-layout assumed 1:1 (stereo source → stereo channel). No upmix/downmix.
- Only YUV420P source pixel format. `FileSourceProducer` rejects others at `Prepare`.
- Linear-interp audio SRC (contract-correct, not production-quality). Polyphase/libsamplerate is a future swap.
- Single-threaded. No concurrency contract.

**In `runtime/`:** unchanged. air/ hasn't replaced, migrated, or modified any of it.

## Next-step options

Two independent branches, either is viable:

### Option A: Emission (frame → MPEG-TS bytes)

- Encoder: x264 for video, AAC or similar for audio.
- Muxer: avformat MPEG-TS output.
- Sink: pluggable output (socket, file, fanout).
- Proves: can air/ actually produce viewable bytes?
- New dependency surface: x264 encoder (already linked), avformat mux context, possibly an output-sink abstraction.
- Biggest unknown: encoder/muxer pacing model (continuous real-time, pull-based, push-based).

### Option B: Session lifecycle (Core↔AIR wiring)

- gRPC server implementing the existing `playout.proto` surface.
- Session-start handshake consuming channel config + block plan.
- Spawnable as a binary (like `retrovue_air`).
- Proves: can air/ be dropped into an existing Core flow?
- Mostly mirrors runtime/ patterns; wiring heavy, architectural reasoning light.

**No strong recommendation from me** — depends on which question you want answered first. If "does this produce real output?" is higher-value, do A. If "does this integrate with Core?" is higher-value, do B.

A third possibility: pause building, audit what you have end-to-end against the vault one more time, then decide. Slices 3 and 5 both surfaced real correctness drift. A quiet audit pass before continuing might reveal more.

## Resuming

Pick up by:
1. `cmake --build /opt/retrovue/air/build -j$(nproc) && ctest --test-dir /opt/retrovue/air/build --output-on-failure` — confirm 44/44 still green.
2. Read this file + `/opt/retrovue/CLAUDE.md` `VAULT-COMPLIANCE PRE-CHECK` section.
3. Greenlight option A, B, or audit pass.

## Memory pointer

A matching entry lives in `/home/steve/.claude/projects/-opt/memory/` under `project_retrovue_air_vnext.md`.
