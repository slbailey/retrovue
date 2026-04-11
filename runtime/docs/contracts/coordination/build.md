# Air build invariants

_Related: [Build and Debug](../../developer/BuildAndDebug.md) • [Phase 8.4 Persistent MpegTS Mux](Phase8-4-PersistentMpegTsMux.md)_

## Purpose

Document non‑negotiable build and codec rules for the RetroVue playout engine (Air). These invariants prevent regressions (e.g. reintroducing runtime codec discovery or LD_LIBRARY_PATH).

## Invariants

1. **All C++ and Air build assets live under `runtime`**  
   This repo is multiplatform; everything C++ and RetroVue Air (sources, CMake, third-party deps, build output, Air-specific scripts) lives under `runtime`. Do not put C++-related paths or scripts outside this root.

2. **Air owns codecs**  
   Encoding and multiplexing use only the codecs and libraries wired in at build time. No system or runtime discovery of codecs.

3. **FFmpeg is built statically**  
   FFmpeg (libavcodec, libavformat, libavutil, libswscale, libswresample) is built as static libraries and linked into Air. x264 is also linked statically from `runtime/third_party/x264/install`. There are no shared FFmpeg/x264 dependencies at runtime.

4. **No runtime codec discovery**  
   Encoder availability (e.g. libx264) is validated at configure/build time. No probing for codecs at process start or during streaming.

5. **No LD_LIBRARY_PATH**  
   Binaries (`retrovue_air`, `contracts_playoutengine_tests`) must run without setting `LD_LIBRARY_PATH`. All required libraries are either static or resolved via RPATH to deterministic paths under `runtime/third_party/`.

6. **`runtime/scripts/build_ffmpeg_static.sh` is authoritative**  
   The canonical way to produce the FFmpeg used by Air is `runtime/scripts/build_ffmpeg_static.sh`. It builds FFmpeg against static x264 from `runtime/third_party/x264/install` and installs into `runtime/third_party/ffmpeg/install`. Do not replace this with system FFmpeg, shared builds, or ad‑hoc scripts without updating this doc and CMake together.

7. **Air build output is always under `runtime/build`**  
   Configure and build from the repo root with `-S runtime -B runtime/build`, or from `runtime` with `-S . -B build`. Do not use a build directory at the repository root (e.g. `/opt/retrovue/build`). Binaries and tests live under `runtime/build`; RPATH and tooling assume that layout.

## Where this is enforced

- **CMake** (`runtime/CMakeLists.txt`): Uses `AIR_ROOT` (runtime); finds only `runtime/third_party/ffmpeg/install` and `runtime/third_party/x264/install`; links static libs; does not use pkg-config for FFmpeg; does not reference any `third_party` outside runtime for linking or runtime.
- **Build script**: `runtime/scripts/build_ffmpeg_static.sh` is the single authoritative FFmpeg build. It creates a minimal `x264.pc` under `runtime/third_party/x264/install` when needed so FFmpeg’s configure can find static x264.

## When changing the build

- Adding a new codec or library: wire it under `runtime/third_party/`, document the install path and any new scripts under `runtime/scripts/`, and keep “no LD_LIBRARY_PATH” and “no runtime codec discovery”.
- Replacing or upgrading FFmpeg/x264: update `runtime/scripts/build_ffmpeg_static.sh` and CMake in lockstep; re‑run the script and a clean Air build (in `runtime/build`) before merging.
