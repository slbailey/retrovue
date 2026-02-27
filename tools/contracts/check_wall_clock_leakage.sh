#!/usr/bin/env bash
# check_wall_clock_leakage.sh
#
# Enforcement script for INV-TIME-MODE-EQUIVALENCE-001.
#
# Scope: The BlockPlan subsystem, which owns the playout tick loop.
# This is where frame timing decisions are made: deadline computation,
# frame index mapping, seam decisions, and switch boundary enforcement.
#
# The invariant requires that these decisions derive exclusively from
# IOutputClock — no direct wall-clock reads for playout decisions.
#
# Out of scope (legitimate wall-clock use elsewhere):
#   - SystemMasterClock / TimingLoop — the real-time timing implementation
#   - FileProducer / BlackFrameProducer — decode backoff sleeps (not frame decisions)
#   - EncoderPipeline — PCR-paced mux (governed by separate INV-P10-PCR-PACED-MUX)
#   - PlayoutEngine / playout_service — lifecycle management
#   - EvidenceEmitter / MetricsExporter — telemetry timestamps
#
# PERMITTED FILES within BlockPlan scope:
#   OutputClock.cpp       — real-time IOutputClock implementation
#   IWaitStrategy.hpp     — real-time wait strategy used by OutputClock
#   PipelineManager.cpp   — diagnostic/observability only (boot gate, fill timing,
#                           tick lateness metric, inter-tick gap detection).
#                           None influence deadline computation, frame index mapping,
#                           seam timing, or switch enforcement.
#
# Usage:  bash tools/contracts/check_wall_clock_leakage.sh
# Returns: 0 if clean, 1 if violations found.
# Run from repo root.

# Patterns that constitute direct wall-clock reads.
GREP_PATTERN='steady_clock::now|sleep_until|sleep_for|system_clock::now'

# Only scan the BlockPlan subsystem (tick loop / playout timing decisions).
SCAN_DIRS="pkg/air/src/blockplan pkg/air/include/retrovue/blockplan"

is_permitted() {
  case "$1" in
    # ── Real-time clock implementation ─────────────────────────────────────
    # All wall-clock reads here are the intended production timing surface.
    pkg/air/src/blockplan/OutputClock.cpp)                    return 0 ;;
    pkg/air/include/retrovue/blockplan/IWaitStrategy.hpp)     return 0 ;;

    # ── Diagnostic / observability only ────────────────────────────────────
    # These files read wall clock solely to measure elapsed durations or
    # rate-limit log output.  None of the reads influence deadline computation,
    # frame index mapping, seam timing, or switch enforcement.

    # PipelineManager: bootstrap audio gate timeout, StopFilling/join duration
    # logging, tick lateness metric (metrics_.late_ticks_total), inter-tick
    # gap detection.
    pkg/air/src/blockplan/PipelineManager.cpp)                return 0 ;;

    # TickProducer: prime_start / elapsed — measures prime duration for logging.
    pkg/air/src/blockplan/TickProducer.cpp)                   return 0 ;;

    # AudioLookaheadBuffer: t0 for rate-limited depth logging (once per second).
    pkg/air/src/blockplan/AudioLookaheadBuffer.cpp)           return 0 ;;

    # VideoLookaheadBuffer: fill_start_time_ for GetRefillRate() metrics;
    # `now` in fill loop for rate-limited MEM_WATCHDOG log;
    # decode_start/end for per-decode latency metrics.
    pkg/air/src/blockplan/VideoLookaheadBuffer.cpp)           return 0 ;;

    # RealAssetSource: open_start/end, stream_info_start/end — asset open
    # latency diagnostics.
    pkg/air/src/blockplan/RealAssetSource.cpp)                return 0 ;;

    *) return 1 ;;
  esac
}

violations=0

while IFS= read -r hit; do
  filepath="${hit%%:*}"
  filepath="${filepath#./}"

  # Skip lines that are pure comments (leading whitespace then //).
  # This avoids flagging documentation comments in headers that mention
  # wall-clock primitives by name.
  line_content="${hit#*:}"       # strip "filepath:"
  line_content="${line_content#*:}"  # strip "linenum:"
  stripped="${line_content#"${line_content%%[! ]*}"}"  # ltrim whitespace
  case "$stripped" in
    //*) continue ;;
  esac

  if ! is_permitted "$filepath"; then
    echo "VIOLATION [INV-TIME-MODE-EQUIVALENCE-001]: wall-clock primitive in BlockPlan file outside clock implementation:"
    echo "  $hit"
    violations=$((violations + 1))
  fi
done < <(grep -rn --include="*.cpp" --include="*.hpp" \
    -E "$GREP_PATTERN" \
    $SCAN_DIRS 2>/dev/null || true)

if [ "$violations" -gt 0 ]; then
  echo ""
  echo "FAILED: $violations wall-clock leakage violation(s) in BlockPlan subsystem."
  echo "Frame timing decisions MUST derive from IOutputClock. See:"
  echo "  docs/contracts/invariants/air/INV-TIME-MODE-EQUIVALENCE-001.md"
  exit 1
fi

echo "OK: No wall-clock leakage in BlockPlan tick loop outside permitted clock files."
exit 0
