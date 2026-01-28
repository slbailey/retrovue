#!/usr/bin/env bash
# Build FFmpeg with static libs linked against static x264 from pkg/air/third_party/x264/install.
# Installs into pkg/air/third_party/ffmpeg/install (include/, lib/*.a).
# Run from repo root: pkg/air/scripts/build_ffmpeg_static.sh  — or from pkg/air: scripts/build_ffmpeg_static.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AIR_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
FFMPEG_SRC="${AIR_ROOT}/third_party/ffmpeg"
FFMPEG_INSTALL="${AIR_ROOT}/third_party/ffmpeg/install"
X264_INSTALL="${AIR_ROOT}/third_party/x264/install"

if [[ ! -f "${FFMPEG_SRC}/configure" ]]; then
  echo "FFmpeg source not found at ${FFMPEG_SRC}. Expected pkg/air/third_party/ffmpeg with configure." >&2
  exit 1
fi
if [[ ! -f "${X264_INSTALL}/lib/libx264.a" ]]; then
  echo "Static x264 not found at ${X264_INSTALL}/lib/libx264.a. Build and install x264 first." >&2
  exit 1
fi

# FFmpeg configure uses pkg-config for libx264. Ensure x264.pc exists and is visible.
X264_PC_DIR="${X264_INSTALL}/lib/pkgconfig"
mkdir -p "${X264_PC_DIR}"
if [[ ! -f "${X264_PC_DIR}/x264.pc" ]]; then
  cat > "${X264_PC_DIR}/x264.pc" << EOF
prefix=${X264_INSTALL}
exec_prefix=\${prefix}
libdir=\${exec_prefix}/lib
includedir=\${prefix}/include
Name: x264
Description: H.264 encoder (static)
Version: 0.164
Libs: -L\${libdir} -lx264 -lpthread -lm
Cflags: -I\${includedir}
EOF
  echo "Wrote ${X264_PC_DIR}/x264.pc for FFmpeg configure."
fi
export PKG_CONFIG_PATH="${X264_PC_DIR}:${PKG_CONFIG_PATH:-}"

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

make -j"$(nproc)"
make install

echo "FFmpeg installed to ${FFMPEG_INSTALL} (static libs + x264)."
