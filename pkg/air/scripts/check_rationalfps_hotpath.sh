#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SCOPES=(
  "$ROOT_DIR/src/blockplan"
  "$ROOT_DIR/tests/contracts/BlockPlan/VideoLookaheadBufferTests.cpp"
  "$ROOT_DIR/tests/contracts/BlockPlan/LookaheadBufferContractTests.cpp"
  "$ROOT_DIR/tests/contracts/BlockPlan/BufferConfigTests.cpp"
  "$ROOT_DIR/tests/contracts/BlockPlan/SegmentAdvanceOnEOFTests.cpp"
  "$ROOT_DIR/tests/contracts/PrimitiveInvariants/PacingInvariantContractTests.cpp"
)

PATTERNS=(
  '1\.0[[:space:]]*/[[:space:]]*fps\b'
  '1000\.0[[:space:]]*/[[:space:]]*fps\b'
  "1'000'000\.0[[:space:]]*/[[:space:]]*fps\b"
  'DeriveRationalFPS\(30\.0\)'
  'DeriveRationalFPS\(29\.97\)'
  'DeriveRationalFPS\(59\.94\)'
  'DeriveRationalFPS\(23\.976\)'
)

fail=0
for scope in "${SCOPES[@]}"; do
  [[ -e "$scope" ]] || continue
  for p in "${PATTERNS[@]}"; do
    if rg -n --pcre2 "$p" "$scope" >/tmp/rfps_guard_hits.txt 2>/dev/null; then
      if [[ -s /tmp/rfps_guard_hits.txt ]]; then
        echo "[RationalFps guard] Forbidden pattern in $scope (pattern: $p)" >&2
        cat /tmp/rfps_guard_hits.txt >&2
        fail=1
      fi
    fi
  done
done

if [[ $fail -ne 0 ]]; then
  echo "RationalFps hot-path guard FAILED" >&2
  exit 1
fi

echo "RationalFps hot-path guard PASSED"
