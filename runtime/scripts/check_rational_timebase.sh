#!/usr/bin/env bash
# INV-FPS-RATIONAL-001: Fail CI if blockplan hot path contains float/double/ToDouble/floating literals.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BLOCKPLAN_SRC="${SCRIPT_DIR}/../src/blockplan"

if [[ ! -d "$BLOCKPLAN_SRC" ]]; then
  echo "[check_rational_timebase] Blockplan src not found: $BLOCKPLAN_SRC" >&2
  exit 1
fi

fail=0
while IFS= read -r -d '' f; do
  base=$(basename "$f")
  line_no=0
  while IFS= read -r line; do
    ((line_no++)) || true
    # Skip comment-only lines
    trim=$(echo "$line" | sed 's/^[[:space:]]*//')
    if [[ "$trim" == //* || "$trim" == \* || "$trim" == /\* ]]; then
      continue
    fi
    if echo "$line" | grep -qE '\bdouble\b|\bfloat\b'; then
      echo "$f:$line_no: $line" >&2
      fail=1
    fi
    if echo "$line" | grep -qE 'ToDouble\s*\('; then
      echo "$f:$line_no: $line" >&2
      fail=1
    fi
    if echo "$line" | grep -qE '[0-9]+\.[0-9]+([eE][+-]?[0-9]+)?'; then
      echo "$f:$line_no: $line" >&2
      fail=1
    fi
    if echo "$line" | grep -qE '[0-9]+[eE][+-]?[0-9]+'; then
      echo "$f:$line_no: $line" >&2
      fail=1
    fi
    if echo "$line" | grep -qE 'duration\s*<\s*double\s*>'; then
      echo "$f:$line_no: $line" >&2
      fail=1
    fi
  done < "$f"
done < <(find "$BLOCKPLAN_SRC" -type f \( -name '*.cpp' -o -name '*.hpp' \) -print0)

if [[ $fail -ne 0 ]]; then
  echo "[check_rational_timebase] INV-FPS-RATIONAL-001: Forbidden float/double/ToDouble/literals in blockplan hot path" >&2
  exit 1
fi
echo "[check_rational_timebase] PASSED"
