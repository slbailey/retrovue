#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

FILES=(
  "$ROOT_DIR/src/blockplan/TickProducer.cpp"
  "$ROOT_DIR/src/blockplan/VideoLookaheadBuffer.cpp"
  "$ROOT_DIR/src/blockplan/OutputClock.cpp"
)

PATTERNS=(
  '1\.0[[:space:]]*/[[:space:]]*[A-Za-z0-9_\.]*fps'
  '1000\.0[[:space:]]*/[[:space:]]*[A-Za-z0-9_\.]*fps'
  "1'000'000\.0[[:space:]]*/[[:space:]]*[A-Za-z0-9_\.]*fps"
)

fail=0
for f in "${FILES[@]}"; do
  [[ -f "$f" ]] || continue
  for p in "${PATTERNS[@]}"; do
    if rg -n --pcre2 "$p" "$f" >/tmp/rfps_guard_hits.txt 2>/dev/null; then
      if [[ -s /tmp/rfps_guard_hits.txt ]]; then
        echo "[RationalFps guard] Forbidden fps-double pattern in $f (pattern: $p)" >&2
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
