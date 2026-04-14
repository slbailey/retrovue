# Runtime third-party trees

This directory holds source trees and install prefixes used by the AIR runtime build (FFmpeg, x264, etc.).

## x264 / FFmpeg build contract (required)

- x264 **must** be built only via `runtime/scripts/build_x264_static.sh` into `runtime/third_party/x264/install`. The environment variable **`X264_EXPECTED_GIT_COMMIT`** **must** be set to the full git SHA documented below; the script **must** refuse to run if it is unset or if `runtime/third_party/x264/src` is not a git checkout at that commit.
- Source **must** live at **`runtime/third_party/x264/src`** only (fixed path; no alternate locations).
- The install directory **`runtime/third_party/x264/install`** is removed and recreated at the start of every x264 build so stale headers, mixed archives, and partial installs are **prohibited**.
- Headers (`x264.h`, `x264_config.h`) and `lib/libx264.a` **must** come from the **same** install produced by that single build; mixing artifacts across versions or machines is **prohibited**.
- FFmpeg **must** be built only with `runtime/scripts/build_ffmpeg_static.sh`. That script **must** run `runtime/scripts/verify_x264_ffmpeg.sh` first on every invocation; skipping verification is **prohibited**. FFmpeg **must not** be configured or linked against x264 unless verify has passed.
- Copying x264 headers or libraries from outside this tree (including `pkg/air` or other prebuilt trees) into `runtime/third_party/x264/install` is **prohibited**; verification and CI are intended to catch drift.
- **Pinned x264 revision (required for reproducible builds):**  
  `X264_EXPECTED_GIT_COMMIT=0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee`  
  Clone upstream with `git clone https://code.videolan.org/videolan/x264.git runtime/third_party/x264/src`, then `git checkout 0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee`, then export the variable above and run `runtime/scripts/build_x264_static.sh`.
- **CI:** builds x264 from source at the pinned commit, then runs `runtime/scripts/verify_x264_ffmpeg.sh`; the pipeline **must not** assume a pre-existing `install/` tree.
