# Air build invariants

_Related: [Build and Debug](../../developer/BuildAndDebug.md) • [Phase 8.4 Persistent MpegTS Mux](Phase8-4-PersistentMpegTsMux.md)_

## Purpose

Document non‑negotiable build and codec rules for the RetroVue playout engine (Air). These invariants prevent regressions (e.g. reintroducing runtime codec discovery or LD_LIBRARY_PATH).

## Invariants

1. **All C++ and Air build assets live under `pkg/air`**  
   This repo is multiplatform; everything C++ and RetroVue Air (sources, CMake, third-party deps, build output, Air-specific scripts) lives under `pkg/air`. Do not put C++-related paths or scripts outside this root.

2. **Air owns codecs**  
   Encoding and multiplexing use only the codecs and libraries wired in at build time. No system or runtime discovery of codecs.

3. **FFmpeg is built statically**  
   FFmpeg (libavcodec, libavformat, libavutil, libswscale, libswresample) is built as static libraries and linked into Air. x264 is also linked statically from `pkg/air/third_party/x264/install`. There are no shared FFmpeg/x264 dependencies at runtime.

4. **No runtime codec discovery**  
   Encoder availability (e.g. libx264) is validated at configure/build time. No probing for codecs at process start or during streaming.

5. **No LD_LIBRARY_PATH**  
   Binaries (`retrovue_air`, `contracts_playoutengine_tests`) must run without setting `LD_LIBRARY_PATH`. All required libraries are either static or resolved via RPATH to deterministic paths under `pkg/air/third_party/`.

6. **`pkg/air/scripts/build_ffmpeg_static.sh` is authoritative**  
   The canonical way to produce the FFmpeg used by Air is `pkg/air/scripts/build_ffmpeg_static.sh`. It builds FFmpeg against static x264 from `pkg/air/third_party/x264/install` and installs into `pkg/air/third_party/ffmpeg/install`. Do not replace this with system FFmpeg, shared builds, or ad‑hoc scripts without updating this doc and CMake together.

7. **Air build output is always under `pkg/air/build`**  
   Configure and build from the repo root with `-S pkg/air -B pkg/air/build`, or from `pkg/air` with `-S . -B build`. Do not use a build directory at the repository root (e.g. `/opt/retrovue/build`). Binaries and tests live under `pkg/air/build`; RPATH and tooling assume that layout.

## Where this is enforced

- **CMake** (`pkg/air/CMakeLists.txt`): Uses `AIR_ROOT` (pkg/air); finds only `pkg/air/third_party/ffmpeg/install` and `pkg/air/third_party/x264/install`; links static libs; does not use pkg-config for FFmpeg; does not reference any `third_party` outside pkg/air for linking or runtime.
- **Build script**: `pkg/air/scripts/build_ffmpeg_static.sh` is the single authoritative FFmpeg build. It creates a minimal `x264.pc` under `pkg/air/third_party/x264/install` when needed so FFmpeg’s configure can find static x264.

## When changing the build

- Adding a new codec or library: wire it under `pkg/air/third_party/`, document the install path and any new scripts under `pkg/air/scripts/`, and keep “no LD_LIBRARY_PATH” and “no runtime codec discovery”.
- Replacing or upgrading FFmpeg/x264: update `pkg/air/scripts/build_ffmpeg_static.sh` and CMake in lockstep; re‑run the script and a clean Air build (in `pkg/air/build`) before merging.
