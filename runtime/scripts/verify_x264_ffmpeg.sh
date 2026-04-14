#!/usr/bin/env bash
# Verify x264 headers and libx264.a agree on X264_BUILD (API) before linking FFmpeg or AIR.
# Run from repo root: runtime/scripts/verify_x264_ffmpeg.sh
# AIR_ROOT is always the runtime directory containing this script’s ../ (no overrides).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AIR_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
X264_INSTALL="${AIR_ROOT}/third_party/x264/install"
HDR_DIR="${X264_INSTALL}/include"
LIB_A="${X264_INSTALL}/lib/libx264.a"

if [[ ! -f "${LIB_A}" ]]; then
  echo "ERROR: x264 install missing. Run build_x264_static.sh (with X264_EXPECTED_GIT_COMMIT set)." >&2
  exit 1
fi

die() { echo "verify_x264_ffmpeg: $*" >&2; exit 1; }

[[ -f "${HDR_DIR}/x264.h" ]] || die "missing ${HDR_DIR}/x264.h (build x264 into ${X264_INSTALL})"
[[ -f "${HDR_DIR}/x264_config.h" ]] || die "missing ${HDR_DIR}/x264_config.h"

# Upstream x264 defines X264_BUILD in x264.h; some trees may define it in x264_config.h.
hdr_build=""
if def="$(grep -E '^#define[[:space:]]+X264_BUILD[[:space:]]+[0-9]+' "${HDR_DIR}/x264_config.h" 2>/dev/null | head -1)"; then
  hdr_build="$(awk '{print $3}' <<< "${def}")"
fi
if [[ -z "${hdr_build}" ]]; then
  def="$(grep -E '^#define[[:space:]]+X264_BUILD[[:space:]]+[0-9]+' "${HDR_DIR}/x264.h" | head -1)" || true
  hdr_build="$(awk '{print $3}' <<< "${def}")"
fi
[[ -n "${hdr_build}" ]] || die "could not parse X264_BUILD from x264_config.h or x264.h"

# Exactly one defined x264_encoder_open_<N> revision (reject empty, mixed, or corrupt archives).
raw_matches="$(nm "${LIB_A}" 2>/dev/null | sed -n 's/.*[[:space:]]T[[:space:]]x264_encoder_open_\([0-9][0-9]*\)$/\1/p' || true)"
lib_builds="$(printf '%s\n' "${raw_matches}" | grep -E '^[0-9]+$' | sort -u)"
[[ -n "${lib_builds}" ]] || die "zero matches: no symbol x264_encoder_open_<N> in ${LIB_A} (wrong archive or stripped .a)"

unique_count="$(wc -l <<< "${lib_builds}" | tr -d '[:space:]')"
if [[ "${unique_count}" -ne 1 ]]; then
  die "expected exactly one distinct x264_encoder_open_* API revision in ${LIB_A}; found ${unique_count} ($(tr '\n' ' ' <<< "${lib_builds}")). Mixed or corrupt install?"
fi

lib_build="$(head -n1 <<< "${lib_builds}")"
if [[ "${hdr_build}" != "${lib_build}" ]]; then
  die "x264 header/library mismatch: headers X264_BUILD=${hdr_build} but libx264.a has x264_encoder_open_${lib_build}. Rebuild x264 (runtime/scripts/build_x264_static.sh) and reinstall; do not mix prebuilt .a with foreign headers."
fi

echo "x264 build: X264_BUILD=${hdr_build}"
echo "verify_x264_ffmpeg: OK (X264_BUILD=${hdr_build}, symbol x264_encoder_open_${lib_build})"
