#!/usr/bin/env bash
# Build FFmpeg with static libs linked against static x264 from runtime/third_party/x264/install.
# Installs into runtime/third_party/ffmpeg/install (include/, lib/*.a).
# Run from repo root: runtime/scripts/build_ffmpeg_static.sh  — or from runtime: scripts/build_ffmpeg_static.sh
#
# verify_x264_ffmpeg.sh always runs first; there is no way to skip it.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AIR_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
FFMPEG_SRC="${AIR_ROOT}/third_party/ffmpeg"
FFMPEG_INSTALL="${AIR_ROOT}/third_party/ffmpeg/install"
X264_INSTALL="${AIR_ROOT}/third_party/x264/install"

"${SCRIPT_DIR}/verify_x264_ffmpeg.sh" || exit 1

if [[ ! -f "${FFMPEG_SRC}/configure" ]]; then
  echo "FFmpeg source not found at ${FFMPEG_SRC}. Expected runtime/third_party/ffmpeg with configure." >&2
  exit 1
fi

# FFmpeg configure uses pkg-config for libx264; regenerate from the verified install (no hardcoded API version).
X264_PC_DIR="${X264_INSTALL}/lib/pkgconfig"
mkdir -p "${X264_PC_DIR}"
x264_pc_version=""
if [[ -f "${X264_INSTALL}/include/x264_config.h" ]]; then
  # X264_POINTVER example: 0.165.3223 0480cb0 → pkg-config Version 0.165
  _pv="$(grep -E '^#define[[:space:]]+X264_POINTVER[[:space:]]+' "${X264_INSTALL}/include/x264_config.h" | head -1 | sed 's/^[^"]*"\([^"]*\)".*/\1/')"
  _pv="${_pv%% *}"
  if [[ -n "${_pv}" ]]; then
    x264_pc_version="$(echo "${_pv}" | awk -F. '{printf "%s.%s", $1, $2}')"
  fi
fi
[[ -n "${x264_pc_version}" ]] || x264_pc_version="0.0"
cat > "${X264_PC_DIR}/x264.pc" << EOF
prefix=${X264_INSTALL}
exec_prefix=\${prefix}
libdir=\${exec_prefix}/lib
includedir=\${prefix}/include
Name: x264
Description: H.264 encoder (static)
Version: ${x264_pc_version}
Libs: -L\${libdir} -lx264 -lpthread -lm
Cflags: -I\${includedir}
EOF
echo "Wrote ${X264_PC_DIR}/x264.pc for FFmpeg configure (Version=${x264_pc_version})."
export PKG_CONFIG_PATH="${X264_PC_DIR}:${PKG_CONFIG_PATH:-}"

# Log pinned API for build logs / postmortems (matches verify_x264_ffmpeg.sh)
if def="$(grep -E '^#define[[:space:]]+X264_BUILD[[:space:]]+[0-9]+' "${X264_INSTALL}/include/x264.h" 2>/dev/null | head -1)"; then
  _xb="$(awk '{print $3}' <<< "${def}")"
  echo "x264 build: X264_BUILD=${_xb} (linking FFmpeg against ${X264_INSTALL})"
fi

cd "${FFMPEG_SRC}"
./configure \
  --prefix="${FFMPEG_INSTALL}" \
  --enable-static \
  --disable-shared \
  --enable-pic \
  --enable-gpl \
  --enable-libx264 \
  --pkg-config-flags="--static" \
  --extra-cflags="-I${X264_INSTALL}/include" \
  --extra-ldflags="-L${X264_INSTALL}/lib" \
  --disable-programs \
  --disable-doc \
  --disable-debug

# Parallel builds can trigger GCC ICE on some files (e.g. mpegaudiodec_fixed.c). Override with FFMPEG_MAKE_JOBS.
: "${FFMPEG_MAKE_JOBS:=2}"
make -j"${FFMPEG_MAKE_JOBS}"
make install

echo "FFmpeg installed to ${FFMPEG_INSTALL} (static libs + x264)."
