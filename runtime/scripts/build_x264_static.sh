#!/usr/bin/env bash
# Build static libx264 into runtime/third_party/x264/install (include/, lib/libx264.a).
# Run from repo root: runtime/scripts/build_x264_static.sh — or from runtime: scripts/build_x264_static.sh
#
# Required environment:
#   X264_EXPECTED_GIT_COMMIT — full SHA; must match HEAD under runtime/third_party/x264/src
# Source path is fixed: runtime/third_party/x264/src (no overrides).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AIR_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
X264_INSTALL="${AIR_ROOT}/third_party/x264/install"
X264_SRC="${AIR_ROOT}/third_party/x264/src"

if [[ -z "${X264_EXPECTED_GIT_COMMIT:-}" ]]; then
  echo "ERROR: X264_EXPECTED_GIT_COMMIT must be set (full git SHA for runtime/third_party/x264/src)." >&2
  exit 1
fi

if [[ ! -f "${X264_SRC}/configure" ]]; then
  echo "x264 source not found at ${X264_SRC} (expected configure)." >&2
  echo "Clone with: git clone https://code.videolan.org/videolan/x264.git \"${X264_SRC}\"" >&2
  exit 1
fi

if [[ ! -d "${X264_SRC}/.git" ]]; then
  echo "ERROR: ${X264_SRC} must be a git checkout (reproducible build)." >&2
  exit 1
fi
_cur="$(git -C "${X264_SRC}" rev-parse HEAD 2>/dev/null || true)"
if [[ "${_cur}" != "${X264_EXPECTED_GIT_COMMIT}" ]]; then
  echo "ERROR: x264 source HEAD does not match X264_EXPECTED_GIT_COMMIT." >&2
  echo "  expected: ${X264_EXPECTED_GIT_COMMIT}" >&2
  echo "  actual:   ${_cur}" >&2
  exit 1
fi

echo "Using X264_EXPECTED_GIT_COMMIT=${X264_EXPECTED_GIT_COMMIT}"

rm -rf "${X264_INSTALL}"
mkdir -p "${X264_INSTALL}"

cd "${X264_SRC}"
if [[ -f Makefile ]]; then
  make distclean 2>/dev/null || make clean 2>/dev/null || true
fi

./configure \
  --prefix="${X264_INSTALL}" \
  --enable-static \
  --disable-opencl

: "${X264_MAKE_JOBS:=$(nproc)}"
make -j"${X264_MAKE_JOBS}"
make install

for f in "${X264_INSTALL}/include/x264.h" "${X264_INSTALL}/include/x264_config.h" "${X264_INSTALL}/lib/libx264.a"; do
  if [[ ! -f "$f" ]]; then
    echo "Expected artifact missing after install: $f" >&2
    exit 1
  fi
done

_xb="$(grep -E '^#define[[:space:]]+X264_BUILD[[:space:]]+[0-9]+' "${X264_INSTALL}/include/x264.h" | head -1 | awk '{print $3}')"
echo "x264 build: X264_BUILD=${_xb}"
echo "x264 installed to ${X264_INSTALL} (static lib + headers)."
